import logging
import json
import os
import random
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "render-farm-simulator")
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
PRODUCTION_ID = os.getenv("PRODUCTION_ID", "neon-horizon-trailer")
TICK_SECONDS = float(os.getenv("SIM_TICK_SECONDS", "2"))
DEADLINE_MINUTES = int(os.getenv("DELIVERY_DEADLINE_MINUTES", "360"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/ai-production.db")

resource = Resource.create(
    {
        "service.name": SERVICE_NAME,
        "service.version": "0.1.0",
        "deployment.environment": "demo",
        "production.id": PRODUCTION_ID,
    }
)

trace_provider = TracerProvider(resource=resource)
trace_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True)))
trace.set_tracer_provider(trace_provider)

metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=OTLP_ENDPOINT, insecure=True), export_interval_millis=5000
)
metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))

logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(
    BatchLogRecordProcessor(OTLPLogExporter(endpoint=OTLP_ENDPOINT, insecure=True))
)
handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger(SERVICE_NAME)

tracer = trace.get_tracer(SERVICE_NAME)
meter = metrics.get_meter(SERVICE_NAME)


@dataclass
class RenderState:
    scenario: str = "healthy"
    total_scenes: int = 252
    completed_scenes: int = 184
    queue_depth: int = 12
    gpu_workers_total: int = 200
    gpu_workers_active: int = 196
    gpu_memory_utilization: float = 68.0
    average_scene_seconds: float = 42.0
    retries_total: int = 3
    added_cost_usd: float = 0.0
    predicted_delay_minutes: float = -48.0
    recovery_progress: float = 0.0
    failed_scenes: int = 0
    storage_utilization: float = 61.0
    network_latency_ms: float = 12.0
    asset_error_rate: float = 0.0
    estimated_cost_usd: float = 840.0


SCENARIOS = {
    "healthy": ("normal", "pipeline", "Nominal render-farm operation"),
    "queue_surge": ("warning", "scheduler", "Incoming work exceeds render capacity"),
    "gpu_oom": ("critical", "gpu", "CUDA memory exhaustion causes retries"),
    "gpu_overheating": ("critical", "gpu", "Thermal throttling reduces GPU throughput"),
    "worker_loss": ("critical", "workers", "A large part of the worker pool is unavailable"),
    "render_stalled": ("critical", "pipeline", "Scenes stop completing while work remains queued"),
    "storage_slow": ("warning", "storage", "Slow asset reads increase render duration"),
    "storage_full": ("critical", "storage", "Output storage capacity is exhausted"),
    "network_latency": ("warning", "network", "High inter-service latency slows dispatch and uploads"),
    "asset_corruption": ("critical", "assets", "Invalid assets cause deterministic scene failures"),
    "dependency_down": ("critical", "dependency", "A required production service is unavailable"),
    "license_failure": ("critical", "licensing", "Renderer license checkout failures block workers"),
    "cost_overrun": ("warning", "finance", "Cloud burst capacity exceeds the approved budget"),
    "deadline_risk": ("warning", "delivery", "Forecast has crossed the delivery deadline"),
    "recovering": ("info", "pipeline", "Approved remediation is being executed"),
    "recovered": ("normal", "pipeline", "Service restored and deadline risk cleared"),
}


RECOVERY_LIBRARY = {
    "gpu": [
        ("restart_gpu_workers", "Restart affected GPU workers", 8, 12.0, "low"),
        ("reduce_scene_batch", "Reduce scene batch size and memory footprint", 15, 4.0, "low"),
        ("burst_gpu_pool", "Burst workloads to standby GPU capacity", 5, 85.0, "medium"),
    ],
    "workers": [
        ("replace_workers", "Replace unhealthy workers from the standby pool", 10, 40.0, "low"),
        ("rebalance_queue", "Rebalance priority scenes across healthy workers", 18, 8.0, "medium"),
    ],
    "scheduler": [
        ("prioritize_delivery", "Prioritize delivery-critical scenes", 12, 17.0, "medium"),
        ("burst_gpu_pool", "Add temporary GPU capacity", 6, 95.0, "low"),
    ],
    "storage": [
        ("clean_render_cache", "Clean expired render cache and temporary outputs", 12, 2.0, "medium"),
        ("expand_storage", "Attach emergency output storage", 8, 45.0, "low"),
    ],
    "network": [
        ("reroute_network", "Reroute traffic through the standby path", 7, 6.0, "low"),
        ("localize_assets", "Stage active assets near GPU workers", 20, 25.0, "medium"),
    ],
    "assets": [
        ("restore_assets", "Restore affected assets from the last valid version", 18, 5.0, "low"),
        ("skip_failed_scenes", "Quarantine failed scenes and continue unaffected work", 5, 1.0, "high"),
    ],
    "dependency": [
        ("failover_dependency", "Fail over to the standby production service", 6, 15.0, "low"),
        ("degraded_mode", "Continue rendering in dependency-degraded mode", 3, 2.0, "high"),
    ],
    "licensing": [
        ("refresh_licenses", "Refresh renderer license leases", 8, 0.0, "low"),
        ("failover_license_server", "Switch to the backup license server", 5, 8.0, "low"),
    ],
    "finance": [
        ("cap_cloud_burst", "Cap cloud burst capacity at the approved budget", 5, -80.0, "medium"),
        ("prioritize_delivery", "Retain only delivery-critical capacity", 10, -45.0, "medium"),
    ],
    "delivery": [
        ("prioritize_delivery", "Prioritize delivery-critical scenes", 12, 17.0, "medium"),
        ("burst_gpu_pool", "Add temporary GPU capacity", 6, 95.0, "low"),
    ],
    "pipeline": [
        ("restart_pipeline", "Restart stalled pipeline stages", 10, 5.0, "medium"),
        ("resume_checkpoint", "Resume from the latest valid render checkpoint", 15, 3.0, "low"),
    ],
}


state = RenderState()
state_lock = threading.Lock()
database_lock = threading.Lock()
history_lock = threading.Lock()
telemetry_history = []
deadline = datetime.now(timezone.utc) + timedelta(minutes=DEADLINE_MINUTES)

scene_completed = meter.create_counter("render.scenes.completed", unit="{scene}")
retry_counter = meter.create_counter("render.retries", unit="{retry}")
cost_counter = meter.create_counter("render.cost.added", unit="USD")
failure_counter = meter.create_counter("render.failures", unit="{failure}")


def observe_queue(_):
    with state_lock:
        return [metrics.Observation(state.queue_depth, {"production.id": PRODUCTION_ID, "scenario": state.scenario})]


def observe_workers(_):
    with state_lock:
        return [metrics.Observation(state.gpu_workers_active, {"production.id": PRODUCTION_ID, "pool": "gpu-b"})]


def observe_memory(_):
    with state_lock:
        return [metrics.Observation(state.gpu_memory_utilization, {"production.id": PRODUCTION_ID, "pool": "gpu-b"})]


def observe_duration(_):
    with state_lock:
        return [metrics.Observation(state.average_scene_seconds, {"production.id": PRODUCTION_ID})]


def observe_delay(_):
    with state_lock:
        return [metrics.Observation(state.predicted_delay_minutes, {"production.id": PRODUCTION_ID})]


def observe_progress(_):
    with state_lock:
        return [metrics.Observation(state.recovery_progress, {"production.id": PRODUCTION_ID})]


def observe_storage(_):
    with state_lock:
        return [metrics.Observation(state.storage_utilization, {"production.id": PRODUCTION_ID})]


def observe_network(_):
    with state_lock:
        return [metrics.Observation(state.network_latency_ms, {"production.id": PRODUCTION_ID})]


def observe_asset_errors(_):
    with state_lock:
        return [metrics.Observation(state.asset_error_rate, {"production.id": PRODUCTION_ID})]


def observe_cost(_):
    with state_lock:
        return [metrics.Observation(state.estimated_cost_usd, {"production.id": PRODUCTION_ID})]


def observe_condition(_):
    with state_lock:
        active_scenario = state.scenario
        return [
            metrics.Observation(1 if scenario == active_scenario else 0, {
                "production.id": PRODUCTION_ID,
                "scenario": scenario,
                "severity": details[0],
                "component": details[1],
            })
            for scenario, details in SCENARIOS.items()
        ]


meter.create_observable_gauge("render.queue.depth", callbacks=[observe_queue], unit="{job}")
meter.create_observable_gauge("render.gpu.workers.active", callbacks=[observe_workers], unit="{worker}")
meter.create_observable_gauge("render.gpu.memory.utilization", callbacks=[observe_memory], unit="%")
meter.create_observable_gauge("render.scene.duration", callbacks=[observe_duration], unit="s")
meter.create_observable_gauge("render.predicted.delay", callbacks=[observe_delay], unit="min")
meter.create_observable_gauge("render.recovery.progress", callbacks=[observe_progress], unit="%")
meter.create_observable_gauge("render.storage.utilization", callbacks=[observe_storage], unit="%")
meter.create_observable_gauge("render.network.latency", callbacks=[observe_network], unit="ms")
meter.create_observable_gauge("render.asset.error.rate", callbacks=[observe_asset_errors], unit="%")
meter.create_observable_gauge("render.cost.estimated", callbacks=[observe_cost], unit="USD")
meter.create_observable_gauge("render.condition", callbacks=[observe_condition], unit="1")


def database_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    os.makedirs(os.path.dirname(DATABASE_PATH) or ".", exist_ok=True)
    with database_lock, database_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                production_id TEXT NOT NULL,
                details_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                title TEXT NOT NULL,
                severity TEXT NOT NULL,
                component TEXT NOT NULL,
                summary TEXT NOT NULL,
                starts_at TEXT,
                ends_at TEXT,
                updated_at TEXT NOT NULL,
                raw_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS recovery_executions (
                id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                plan_id TEXT NOT NULL,
                plan_title TEXT NOT NULL,
                status TEXT NOT NULL,
                progress REAL NOT NULL,
                approved_by TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (incident_id) REFERENCES incidents(id)
            );
        """)


def record_audit(event_type: str, details: dict) -> dict:
    event = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "production_id": PRODUCTION_ID,
        **details,
    }
    with database_lock, database_connection() as connection:
        connection.execute(
            "INSERT INTO audit_events (id, timestamp, event_type, production_id, details_json) VALUES (?, ?, ?, ?, ?)",
            (event["id"], event["timestamp"], event_type, PRODUCTION_ID, json.dumps(details)),
        )
    return event


def plans_for_scenario(scenario: str) -> list[dict]:
    severity, component, _ = SCENARIOS[scenario]
    if severity == "normal" or scenario == "recovering":
        return []
    templates = RECOVERY_LIBRARY.get(component, RECOVERY_LIBRARY["pipeline"])
    return [
        {
            "plan_id": plan_id,
            "title": title,
            "estimated_recovery_minutes": minutes,
            "estimated_added_cost_usd": cost,
            "risk": risk,
            "recommended": index == 0,
            "requires_approval": True,
            "scenario": scenario,
        }
        for index, (plan_id, title, minutes, cost, risk) in enumerate(templates)
    ]


def plans_for_component(component: str, scenario: str) -> list[dict]:
    templates = RECOVERY_LIBRARY.get(component, RECOVERY_LIBRARY["pipeline"])
    return [
        {
            "plan_id": plan_id,
            "title": title,
            "estimated_recovery_minutes": minutes,
            "estimated_added_cost_usd": cost,
            "risk": risk,
            "recommended": index == 0,
            "requires_approval": True,
            "scenario": scenario,
        }
        for index, (plan_id, title, minutes, cost, risk) in enumerate(templates)
    ]


def sync_recovery_execution(scenario: str, progress: float) -> None:
    now = datetime.now(timezone.utc).isoformat()
    completed = None
    with database_lock, database_connection() as connection:
        active = connection.execute(
            "SELECT id, incident_id, plan_id FROM recovery_executions WHERE status = 'executing' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if not active:
            return
        if scenario == "recovered" or progress >= 100:
            connection.execute(
                "UPDATE recovery_executions SET status='completed', progress=100, completed_at=?, updated_at=? WHERE id=?",
                (now, now, active["id"]),
            )
            resolution = connection.execute(
                "UPDATE incidents SET status='resolved', ends_at=?, updated_at=? WHERE id=? AND status='firing'",
                (now, now, active["incident_id"]),
            )
            completed = dict(active)
            completed["incident_resolved"] = resolution.rowcount > 0
        else:
            connection.execute(
                "UPDATE recovery_executions SET progress=?, updated_at=? WHERE id=?",
                (round(progress, 1), now, active["id"]),
            )
    if completed:
        record_audit("incident_auto_resolved" if completed["incident_resolved"] else "recovery_execution_completed", {
            "incident_id": completed["incident_id"],
            "execution_id": completed["id"],
            "plan_id": completed["plan_id"],
            "scenario": "recovered",
        })


def apply_scenario_tick() -> None:
    with state_lock:
        attrs = {"production.id": PRODUCTION_ID, "scenario": state.scenario}
        if state.scenario == "healthy":
            completed = random.choice([0, 1, 1, 2])
            state.completed_scenes = min(state.total_scenes, state.completed_scenes + completed)
            state.queue_depth = max(4, state.queue_depth + random.choice([-1, 0, 0, 1]))
            state.gpu_workers_active = random.randint(194, 199)
            state.gpu_memory_utilization = random.uniform(62, 73)
            state.average_scene_seconds = random.uniform(38, 46)
            state.predicted_delay_minutes = random.uniform(-55, -35)
            state.storage_utilization = random.uniform(58, 64)
            state.network_latency_ms = random.uniform(8, 18)
            state.asset_error_rate = 0
            if completed:
                scene_completed.add(completed, attrs)

        elif state.scenario == "gpu_oom":
            state.queue_depth = min(180, state.queue_depth + random.randint(4, 9))
            state.gpu_workers_active = max(92, state.gpu_workers_active - random.randint(1, 4))
            state.gpu_memory_utilization = random.uniform(96, 99.8)
            state.average_scene_seconds = min(240, state.average_scene_seconds + random.uniform(7, 15))
            state.retries_total += 1
            state.predicted_delay_minutes = min(378, state.predicted_delay_minutes + random.uniform(15, 28))
            retry_counter.add(1, {**attrs, "error.type": "cuda_oom", "worker.pool": "gpu-b"})
            logger.error(
                "CUDA out of memory; scene retry queued",
                extra={"scene.id": f"SC-{state.completed_scenes + 1:03d}", "worker.pool": "gpu-b"},
            )

        elif state.scenario == "queue_surge":
            state.queue_depth = min(300, state.queue_depth + random.randint(10, 22))
            state.gpu_workers_active = random.randint(190, 199)
            state.gpu_memory_utilization = random.uniform(75, 88)
            state.average_scene_seconds = min(150, state.average_scene_seconds + random.uniform(3, 8))
            state.predicted_delay_minutes = min(300, state.predicted_delay_minutes + random.uniform(10, 20))

        elif state.scenario == "gpu_overheating":
            state.queue_depth = min(220, state.queue_depth + random.randint(5, 12))
            state.gpu_workers_active = max(110, state.gpu_workers_active - random.randint(2, 6))
            state.gpu_memory_utilization = random.uniform(82, 94)
            state.average_scene_seconds = min(260, state.average_scene_seconds + random.uniform(10, 20))
            state.predicted_delay_minutes = min(360, state.predicted_delay_minutes + random.uniform(12, 25))

        elif state.scenario in {"worker_loss", "license_failure"}:
            floor = 45 if state.scenario == "worker_loss" else 20
            state.gpu_workers_active = max(floor, state.gpu_workers_active - random.randint(8, 18))
            state.queue_depth = min(300, state.queue_depth + random.randint(8, 18))
            state.average_scene_seconds = min(300, state.average_scene_seconds + random.uniform(8, 18))
            state.predicted_delay_minutes = min(420, state.predicted_delay_minutes + random.uniform(18, 35))

        elif state.scenario == "render_stalled":
            state.gpu_workers_active = max(1, state.gpu_workers_active - random.randint(12, 25))
            state.queue_depth = min(350, state.queue_depth + random.randint(12, 24))
            state.average_scene_seconds = min(600, state.average_scene_seconds + random.uniform(25, 50))
            state.predicted_delay_minutes = min(600, state.predicted_delay_minutes + random.uniform(30, 55))

        elif state.scenario in {"storage_slow", "storage_full"}:
            increment = random.uniform(1, 3) if state.scenario == "storage_slow" else random.uniform(4, 8)
            state.storage_utilization = min(100, state.storage_utilization + increment)
            state.queue_depth = min(280, state.queue_depth + random.randint(5, 14))
            state.average_scene_seconds = min(360, state.average_scene_seconds + random.uniform(12, 30))
            state.predicted_delay_minutes = min(480, state.predicted_delay_minutes + random.uniform(15, 32))

        elif state.scenario == "network_latency":
            state.network_latency_ms = min(2500, state.network_latency_ms + random.uniform(80, 220))
            state.queue_depth = min(220, state.queue_depth + random.randint(3, 9))
            state.average_scene_seconds = min(220, state.average_scene_seconds + random.uniform(5, 13))
            state.predicted_delay_minutes = min(300, state.predicted_delay_minutes + random.uniform(8, 18))

        elif state.scenario == "asset_corruption":
            state.asset_error_rate = min(100, state.asset_error_rate + random.uniform(4, 10))
            state.failed_scenes += random.randint(1, 3)
            state.retries_total += random.randint(1, 3)
            state.queue_depth = min(250, state.queue_depth + random.randint(4, 10))
            state.predicted_delay_minutes = min(360, state.predicted_delay_minutes + random.uniform(12, 24))

        elif state.scenario == "dependency_down":
            state.gpu_workers_active = max(0, state.gpu_workers_active - random.randint(20, 45))
            state.queue_depth = min(400, state.queue_depth + random.randint(15, 30))
            state.average_scene_seconds = min(600, state.average_scene_seconds + random.uniform(30, 60))
            state.predicted_delay_minutes = min(720, state.predicted_delay_minutes + random.uniform(40, 75))

        elif state.scenario == "cost_overrun":
            added = random.uniform(35, 90)
            state.estimated_cost_usd += added
            state.added_cost_usd += added
            state.gpu_workers_active = min(state.gpu_workers_total, state.gpu_workers_active + random.randint(1, 4))
            cost_counter.add(added, {"production.id": PRODUCTION_ID, "plan": "cloud_burst"})

        elif state.scenario == "deadline_risk":
            state.queue_depth = min(260, state.queue_depth + random.randint(5, 12))
            state.average_scene_seconds = min(240, state.average_scene_seconds + random.uniform(6, 14))
            state.predicted_delay_minutes = min(480, max(5, state.predicted_delay_minutes + random.uniform(15, 30)))

        elif state.scenario == "recovering":
            state.recovery_progress = min(100, state.recovery_progress + random.uniform(5, 12))
            state.queue_depth = max(8, state.queue_depth - random.randint(4, 10))
            state.gpu_workers_active = min(198, state.gpu_workers_active + random.randint(2, 6))
            state.gpu_memory_utilization = max(70, state.gpu_memory_utilization - random.uniform(3, 7))
            state.average_scene_seconds = max(44, state.average_scene_seconds - random.uniform(6, 12))
            state.predicted_delay_minutes = max(-5, state.predicted_delay_minutes - random.uniform(22, 38))
            if state.recovery_progress >= 100:
                state.scenario = "recovered"
                logger.info("Recovery complete; production delivery is back within deadline")
                record_audit("recovery_completed", {
                    "scenario": "recovered",
                    "predicted_delay_minutes": round(state.predicted_delay_minutes, 1),
                })

        elif state.scenario == "recovered":
            state.queue_depth = max(4, state.queue_depth - 1)
            state.gpu_workers_active = random.randint(195, 199)
            state.gpu_memory_utilization = random.uniform(65, 75)
            state.average_scene_seconds = random.uniform(40, 47)
            state.predicted_delay_minutes = random.uniform(-8, -3)


def simulation_loop() -> None:
    while True:
        with tracer.start_as_current_span("render.pipeline.tick") as span:
            with state_lock:
                span.set_attribute("production.id", PRODUCTION_ID)
                span.set_attribute("render.scenario", state.scenario)
                span.set_attribute("render.queue.depth", state.queue_depth)
            with tracer.start_as_current_span("allocate_gpu"):
                time.sleep(0.02)
            with tracer.start_as_current_span("render_scene"):
                apply_scenario_tick()
                with state_lock:
                    recovery_scenario = state.scenario
                    recovery_progress = state.recovery_progress
                    point = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "gpu_memory_utilization": round(state.gpu_memory_utilization, 2),
                        "queue_depth": state.queue_depth,
                    }
                with history_lock:
                    telemetry_history.append(point)
                    del telemetry_history[:-360]
                sync_recovery_execution(recovery_scenario, recovery_progress)
            with tracer.start_as_current_span("update_delivery_forecast"):
                time.sleep(0.01)
        time.sleep(TICK_SECONDS)


app = FastAPI(title="AI Production Director Render Simulator", version="0.1.0")
FastAPIInstrumentor.instrument_app(app, tracer_provider=trace_provider)


@app.on_event("startup")
def start_simulator() -> None:
    initialize_database()
    threading.Thread(target=simulation_loop, daemon=True, name="render-simulation").start()
    logger.info("Render simulator started", extra={"production.id": PRODUCTION_ID})
    record_audit("simulator_started", {"scenario": state.scenario})


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/state")
def get_state():
    with state_lock:
        snapshot = asdict(state)
    snapshot["production_id"] = PRODUCTION_ID
    snapshot["delivery_deadline"] = deadline.isoformat()
    return snapshot


@app.get("/telemetry-history")
def get_telemetry_history(limit: int = 120):
    safe_limit = max(2, min(limit, 360))
    with history_lock:
        points = list(telemetry_history[-safe_limit:])
    return {"production_id": PRODUCTION_ID, "points": points}


@app.get("/diagnosis")
def get_diagnosis():
    with state_lock:
        snapshot = asdict(state)
    severity, component, root_cause = SCENARIOS[snapshot["scenario"]]
    late_minutes = max(0.0, snapshot["predicted_delay_minutes"])
    confidence = 0.99 if snapshot["scenario"] in {"healthy", "recovered"} else 0.92
    diagnosis = {
        "production_id": PRODUCTION_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenario": snapshot["scenario"],
        "severity": severity,
        "affected_component": component,
        "root_cause": root_cause,
        "confidence": confidence,
        "delivery_impact": {
            "predicted_delay_minutes": round(snapshot["predicted_delay_minutes"], 1),
            "deadline_at_risk": late_minutes > 0,
            "minutes_late": round(late_minutes, 1),
        },
        "evidence": {
            "queue_depth": snapshot["queue_depth"],
            "active_gpu_workers": snapshot["gpu_workers_active"],
            "gpu_memory_utilization": round(snapshot["gpu_memory_utilization"], 1),
            "storage_utilization": round(snapshot["storage_utilization"], 1),
            "network_latency_ms": round(snapshot["network_latency_ms"], 1),
            "asset_error_rate": round(snapshot["asset_error_rate"], 1),
        },
        "recommended_plan_id": next(
            (plan["plan_id"] for plan in plans_for_scenario(snapshot["scenario"]) if plan["recommended"]),
            None,
        ),
    }
    return diagnosis


@app.get("/recovery-plans")
def get_recovery_plans():
    with state_lock:
        scenario = state.scenario
    return {"production_id": PRODUCTION_ID, "scenario": scenario, "plans": plans_for_scenario(scenario)}


@app.post("/recovery-plans/{plan_id}/approve")
def approve_recovery_plan(plan_id: str, approved_by: str = "operator"):
    with state_lock:
        scenario = state.scenario
        available = plans_for_scenario(scenario)
        plan = next((candidate for candidate in available if candidate["plan_id"] == plan_id), None)
        if not plan:
            raise HTTPException(status_code=409, detail="plan is not available for the active scenario")
        previous = state.scenario
        state.scenario = "recovering"
        state.recovery_progress = 0
        state.added_cost_usd += plan["estimated_added_cost_usd"]
        if plan["estimated_added_cost_usd"] > 0:
            cost_counter.add(plan["estimated_added_cost_usd"], {
                "production.id": PRODUCTION_ID,
                "plan": plan_id,
            })
    execution_id = str(uuid.uuid4())
    event = record_audit("recovery_plan_approved", {
        "approved_by": approved_by,
        "scenario": previous,
        "plan_id": plan_id,
        "execution_id": execution_id,
        "estimated_recovery_minutes": plan["estimated_recovery_minutes"],
        "estimated_added_cost_usd": plan["estimated_added_cost_usd"],
    })
    logger.warning("Recovery plan %s approved by %s", plan_id, approved_by)
    return {"status": "executing", "execution_id": execution_id, "plan": plan, "audit_event_id": event["id"]}


@app.get("/audit-log")
def get_audit_log(limit: int = 50):
    safe_limit = max(1, min(limit, 200))
    with database_lock, database_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM audit_events ORDER BY timestamp DESC LIMIT ?", (safe_limit,)
        ).fetchall()
    events = [{
        "id": row["id"], "timestamp": row["timestamp"],
        "event_type": row["event_type"], "production_id": row["production_id"],
        **json.loads(row["details_json"]),
    } for row in rows]
    return {"production_id": PRODUCTION_ID, "events": events}


@app.post("/webhooks/grafana")
def receive_grafana_webhook(payload: dict):
    received_at = datetime.now(timezone.utc).isoformat()
    processed = []
    for alert in payload.get("alerts", []):
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        status = alert.get("status", payload.get("status", "firing"))
        fingerprint = alert.get("fingerprint") or "|".join(
            f"{key}={value}" for key, value in sorted(labels.items())
        )
        title = labels.get("alertname", payload.get("title", "Grafana alert"))
        severity = labels.get("severity", "warning")
        component = labels.get("component", "unknown")
        summary = annotations.get("summary", annotations.get("description", title))
        incident_id = str(uuid.uuid4())
        ends_at = alert.get("endsAt") if status == "resolved" else None
        with database_lock, database_connection() as connection:
            existing = connection.execute(
                "SELECT id FROM incidents WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
            if existing:
                incident_id = existing["id"]
                connection.execute("""
                    UPDATE incidents SET status=?, title=?, severity=?, component=?, summary=?,
                    ends_at=?, updated_at=?, raw_json=? WHERE fingerprint=?
                """, (status, title, severity, component, summary, ends_at, received_at,
                      json.dumps(alert), fingerprint))
            else:
                connection.execute("""
                    INSERT INTO incidents (id, fingerprint, status, title, severity, component,
                    summary, starts_at, ends_at, updated_at, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (incident_id, fingerprint, status, title, severity, component, summary,
                      alert.get("startsAt"), ends_at, received_at, json.dumps(alert)))
        with state_lock:
            current_scenario = state.scenario
        record_audit("grafana_alert_received", {
            "incident_id": incident_id, "status": status, "scenario": current_scenario,
            "severity": severity, "component": component, "alertname": title,
        })
        processed.append({"incident_id": incident_id, "status": status, "title": title})
    return {"accepted": len(processed), "incidents": processed}


@app.get("/incidents")
def get_incidents(limit: int = 50):
    safe_limit = max(1, min(limit, 200))
    with database_lock, database_connection() as connection:
        rows = connection.execute(
            "SELECT id, fingerprint, status, title, severity, component, summary, starts_at, ends_at, updated_at FROM incidents ORDER BY updated_at DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
    return {"production_id": PRODUCTION_ID, "incidents": [dict(row) for row in rows]}


@app.get("/incidents/{incident_id}/recovery-plans")
def get_incident_recovery_plans(incident_id: str):
    with database_lock, database_connection() as connection:
        incident = connection.execute(
            "SELECT id, status, component, title FROM incidents WHERE id = ?", (incident_id,)
        ).fetchone()
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")
    plans = plans_for_component(incident["component"], f"incident:{incident_id}")
    return {
        "production_id": PRODUCTION_ID,
        "incident_id": incident_id,
        "incident_status": incident["status"],
        "can_execute": incident["status"] == "firing",
        "plans": plans,
    }


@app.post("/incidents/{incident_id}/recovery-plans/{plan_id}/approve")
def approve_incident_recovery_plan(incident_id: str, plan_id: str, approved_by: str = "operator"):
    with database_lock, database_connection() as connection:
        incident = connection.execute(
            "SELECT id, status, component, title FROM incidents WHERE id = ?", (incident_id,)
        ).fetchone()
        active = connection.execute(
            "SELECT id FROM recovery_executions WHERE status = 'executing' LIMIT 1"
        ).fetchone()
    if not incident:
        raise HTTPException(status_code=404, detail="incident not found")
    if incident["status"] != "firing":
        raise HTTPException(status_code=409, detail="only firing incidents can start recovery")
    if active:
        raise HTTPException(status_code=409, detail="another recovery execution is already running")
    plans = plans_for_component(incident["component"], f"incident:{incident_id}")
    plan = next((candidate for candidate in plans if candidate["plan_id"] == plan_id), None)
    if not plan:
        raise HTTPException(status_code=404, detail="recovery plan not found for this incident")

    with state_lock:
        previous = state.scenario
        state.scenario = "recovering"
        state.recovery_progress = 0
        state.added_cost_usd += plan["estimated_added_cost_usd"]
        if plan["estimated_added_cost_usd"] > 0:
            cost_counter.add(plan["estimated_added_cost_usd"], {
                "production.id": PRODUCTION_ID,
                "plan": plan_id,
            })

    execution_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    with database_lock, database_connection() as connection:
        connection.execute("""
            INSERT INTO recovery_executions
            (id, incident_id, plan_id, plan_title, status, progress, approved_by, started_at, completed_at, updated_at)
            VALUES (?, ?, ?, ?, 'executing', 0, ?, ?, NULL, ?)
        """, (execution_id, incident_id, plan_id, plan["title"], approved_by, started_at, started_at))

    event = record_audit("incident_recovery_approved", {
        "incident_id": incident_id,
        "approved_by": approved_by,
        "scenario": previous,
        "plan_id": plan_id,
        "execution_id": execution_id,
        "estimated_recovery_minutes": plan["estimated_recovery_minutes"],
        "estimated_added_cost_usd": plan["estimated_added_cost_usd"],
    })
    return {"status": "executing", "execution_id": execution_id, "plan": plan, "audit_event_id": event["id"]}


@app.get("/recovery-executions")
def get_recovery_executions(incident_id: str | None = None, limit: int = 50):
    safe_limit = max(1, min(limit, 200))
    query = "SELECT * FROM recovery_executions"
    parameters = []
    if incident_id:
        query += " WHERE incident_id = ?"
        parameters.append(incident_id)
    query += " ORDER BY started_at DESC LIMIT ?"
    parameters.append(safe_limit)
    with database_lock, database_connection() as connection:
        rows = connection.execute(query, parameters).fetchall()
    return {"production_id": PRODUCTION_ID, "executions": [dict(row) for row in rows]}


@app.post("/scenario/{scenario}")
def set_scenario(scenario: str):
    if scenario not in SCENARIOS:
        raise HTTPException(status_code=400, detail=f"scenario must be one of {sorted(SCENARIOS)}")
    with state_lock:
        previous = state.scenario
        state.scenario = scenario
        if scenario == "healthy":
            state.recovery_progress = 0
        elif scenario == "gpu_oom":
            state.recovery_progress = 0
        elif scenario == "recovering":
            state.added_cost_usd += 17
            cost_counter.add(17, {"production.id": PRODUCTION_ID, "plan": "prioritize_trailer"})
    severity, component, description = SCENARIOS[scenario]
    if severity in {"warning", "critical"}:
        failure_counter.add(1, {
            "production.id": PRODUCTION_ID,
            "scenario": scenario,
            "severity": severity,
            "component": component,
        })
    logger.warning(
        "Scenario changed from %s to %s: %s",
        previous,
        scenario,
        description,
        extra={"scenario": scenario, "severity": severity, "component": component},
    )
    record_audit("scenario_changed", {
        "previous": previous,
        "scenario": scenario,
        "severity": severity,
        "component": component,
    })
    return {
        "previous": previous,
        "scenario": scenario,
        "severity": severity,
        "component": component,
        "description": description,
    }


@app.get("/scenarios")
def list_scenarios():
    return {
        name: {"severity": details[0], "component": details[1], "description": details[2]}
        for name, details in SCENARIOS.items()
    }


@app.post("/reset")
def reset():
    global state
    with state_lock:
        state = RenderState()
    logger.info("Simulation reset to healthy baseline")
    record_audit("simulation_reset", {"scenario": "healthy"})
    return asdict(state)
