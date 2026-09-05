import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
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
from pydantic import BaseModel, Field

from domain import ProductionEngine, RECOVERY_SPECS, calculate_delivery_impact, calculate_recovery_option, calculate_what_if

SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "render-farm-simulator")
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
TICK_SECONDS = float(os.getenv("SIM_TICK_SECONDS", "2"))
resource = Resource.create({"service.name": SERVICE_NAME, "production.id": "project-nova"})
trace_provider = TracerProvider(resource=resource)
trace_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True)))
trace.set_tracer_provider(trace_provider)
reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=OTLP_ENDPOINT, insecure=True), export_interval_millis=5000)
metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=OTLP_ENDPOINT, insecure=True)))
logging.basicConfig(level=logging.INFO, handlers=[LoggingHandler(logger_provider=logger_provider)])
logger = logging.getLogger(SERVICE_NAME)
tracer = trace.get_tracer(SERVICE_NAME)
meter = metrics.get_meter(SERVICE_NAME)
engine = ProductionEngine()


def add_gauge(metric_name: str, status_field: str, unit: str) -> None:
    def callback(_):
        return [metrics.Observation(engine.status()[status_field], {"production.id": "project-nova"})]
    meter.create_observable_gauge(metric_name, callbacks=[callback], unit=unit)


add_gauge("render.queue.depth", "queue_depth", "{frame}")
add_gauge("render.queue.critical.depth", "critical_queue_depth", "{frame}")
add_gauge("render.gpu.workers.active", "gpu_workers_active", "{worker}")
add_gauge("render.gpu.memory.utilization", "gpu_memory_utilization", "%")


def impact_observation(field: str):
    def callback(_):
        return [metrics.Observation(engine.status()["impact"][field], {"production.id": "project-nova"})]
    return callback


meter.create_observable_gauge("render.current.throughput", callbacks=[impact_observation("current_throughput_fph")], unit="{frame}/h")
meter.create_observable_gauge("render.required.throughput", callbacks=[impact_observation("required_throughput_fph")], unit="{frame}/h")
meter.create_observable_gauge("render.predicted.delay", callbacks=[impact_observation("projected_delay_minutes")], unit="min")
meter.create_observable_gauge("render.recovery.progress", callbacks=[lambda _: [metrics.Observation(engine.status()["recovery_progress"], {"production.id": "project-nova"})]], unit="%")


def production_metric(value):
    def callback(_):
        state = engine.status()
        return [metrics.Observation(value(state), {"production.id": "project-nova"})]
    return callback


meter.create_observable_gauge("render.storage.utilization", callbacks=[production_metric(lambda _: 61)], unit="%")
meter.create_observable_gauge("render.network.latency", callbacks=[production_metric(lambda _: 12)], unit="ms")
meter.create_observable_gauge("render.asset.error.rate", callbacks=[production_metric(lambda state: 18 if state["scenario"] == "corrupted_asset" else 0)], unit="%")
meter.create_observable_gauge("render.cost.estimated", callbacks=[production_metric(lambda state: state["impact"]["baseline_cost_usd"])], unit="USD")
meter.create_observable_gauge("render.failures", callbacks=[production_metric(lambda _: engine.production.scenes["SC-87"].failed_frames)], unit="{failure}")


def condition_observation(_):
    state = engine.status()
    scenario = state["scenario"]
    return [metrics.Observation(1, {"production.id": "project-nova", "scenario": scenario,
                                    "severity": "critical" if state["incident_active"] else "normal",
                                    "component": "gpu" if scenario == "gpu_oom" else "pipeline"})]


meter.create_observable_gauge("render.condition", callbacks=[condition_observation], unit="1")


class RecoveryRequest(BaseModel):
    approval_id: str
    approved_by: str = "operator-dashboard"


class WhatIfRequest(BaseModel):
    workers_added: int = Field(default=0, ge=0, le=10)
    deadline_minutes: int | None = Field(default=None, ge=15)
    quality_percent: int = Field(default=100, ge=50, le=100)
    prioritize_critical: bool = False


class CopilotRequest(BaseModel):
    message: str


app = FastAPI(title="AI Production Director — Project Nova", version="1.0.0")
FastAPIInstrumentor.instrument_app(app, tracer_provider=trace_provider)


def simulation_loop() -> None:
    while True:
        with tracer.start_as_current_span("render.pipeline.tick") as span:
            engine.tick()
            state = engine.status()
            span.set_attribute("production.id", "project-nova")
            span.set_attribute("render.workflow_state", state["workflow_state"])
            span.set_attribute("render.critical_queue_depth", state["critical_queue_depth"])
        time.sleep(TICK_SECONDS)


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=simulation_loop, daemon=True).start()
    engine.record("simulator_started", workflow_state="ON_TRACK")


@app.get("/health")
def health(): return {"status": "ok", "service": SERVICE_NAME}


@app.post("/simulation/start")
def start():
    engine.production.running = True
    engine.record("simulation_started")
    return engine.status()


@app.post("/simulation/reset")
@app.post("/reset")
def reset():
    engine.reset()
    return engine.status()


def flush_incident_evidence():
    """Export the new incident before the agent begins its investigation."""
    trace_provider.force_flush(timeout_millis=3000)
    logger_provider.force_flush(timeout_millis=3000)
    reader.collect()


@app.post("/simulation/incidents/gpu-oom")
def gpu_oom():
    with tracer.start_as_current_span("incident.gpu_oom") as span:
        span.set_attribute("scene.id", "SC-87")
        span.set_attribute("error.type", "cuda_oom")
        engine.inject_gpu_oom()
        engine.production.incident_trace_id = format(span.get_span_context().trace_id, "032x")
        logger.error(json.dumps({"message": "CUDA out of memory", "scene_id": "SC-87", "worker_pool": "gpu-b",
                                 "error_type": "cuda_oom", "production_id": "project-nova"}))
    flush_incident_evidence()
    return engine.status()


@app.post("/simulation/incidents/corrupted-asset")
def corrupted_asset():
    with tracer.start_as_current_span("incident.corrupted_asset") as span:
        span.set_attribute("scene.id", "SC-94")
        span.set_attribute("asset.name", "nova_city.exr")
        engine.inject_corrupted_asset()
        engine.production.incident_trace_id = format(span.get_span_context().trace_id, "032x")
        logger.error(json.dumps({"message": "Corrupted EXR asset checksum mismatch", "scene_id": "SC-94",
                                 "asset": "nova_city.exr", "error_type": "asset_corruption",
                                 "production_id": "project-nova"}))
    flush_incident_evidence()
    return engine.status()


@app.post("/simulation/recovery/fail-next")
def fail_next_recovery():
    engine.production.fail_next_recovery = True
    engine.record("recovery_failure_armed")
    return {"armed": True}


@app.get("/simulation/status")
@app.get("/state")
def status(): return engine.status()


@app.get("/simulation/workers")
def workers():
    with engine.lock:
        return {"workers": [asdict(worker) for worker in engine.production.workers.values()]}


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics():
    state = engine.status()
    return "\n".join([
        "# HELP render_current_throughput_fph Trailer render throughput",
        "# TYPE render_current_throughput_fph gauge",
        f"render_current_throughput_fph{{production_id=\"project-nova\"}} {state['impact']['current_throughput_fph']}",
        f"render_required_throughput_fph{{production_id=\"project-nova\"}} {state['impact']['required_throughput_fph']}",
        f"render_critical_queue_depth{{production_id=\"project-nova\"}} {state['critical_queue_depth']}",
        f"render_scene_failures{{production_id=\"project-nova\",scene_id=\"SC-87\"}} {engine.production.scenes['SC-87'].failed_frames}",
    ]) + "\n"


@app.get("/production/context")
def production_context():
    with engine.lock:
        return {"status": engine.status(), "scenes": [asdict(scene) for scene in engine.production.scenes.values()]}


@app.get("/impact")
def impact(): return calculate_delivery_impact(engine.production)


@app.post("/impact/what-if")
def what_if(request: WhatIfRequest):
    return calculate_what_if(engine.production, request.workers_added, request.deadline_minutes,
                             request.quality_percent, request.prioritize_critical)


@app.get("/verification/comparison")
def verification_comparison():
    before = engine.production.recovery_baseline
    after = engine.production.verification_snapshot or engine.status()
    if not before:
        return {"available": False}
    return {"available": True, "passed": engine.production.verification_complete,
            "status": "passed" if engine.production.verification_complete else "failed" if engine.production.recovery_failed else "pending",
            "before": {"throughput_fph": before["impact"]["current_throughput_fph"],
                       "healthy_workers": before["gpu_workers_active"], "critical_queue": before["critical_queue_depth"],
                       "delay_minutes": before["impact"]["projected_delay_minutes"]},
            "after": {"throughput_fph": after["impact"]["current_throughput_fph"],
                      "healthy_workers": after["gpu_workers_active"], "critical_queue": after["critical_queue_depth"],
                      "delay_minutes": after["impact"]["projected_delay_minutes"]}}


@app.get("/agent/investigation")
def investigation():
    state = engine.status()
    active = state["workflow_state"] in {"INVESTIGATING", "DECISION_REQUIRED"}
    decided = state["workflow_state"] == "DECISION_REQUIRED"
    corrupted = state["scenario"] == "corrupted_asset"
    scene = "Scene 94" if corrupted else "Scene 87"
    evidence = ({"metric": "render asset retries increased to 3 for SC-94",
                 "log": "Scene 94: nova_city.exr checksum mismatch",
                 "trace": "incident.corrupted_asset → render.pipeline.tick"}
                if corrupted else {"metric": "render.gpu.memory.utilization > 99% on 8 workers",
                                    "log": "Scene 87: CUDA out of memory",
                                    "trace": "incident.gpu_oom → render.pipeline.tick"})
    return {"mode": "mock-fallback", "workflow_state": state["workflow_state"], "steps": [
        {"id": "metrics", "label": "Query Grafana metrics", "status": "complete" if active else "idle"},
        {"id": "logs", "label": f"Search {scene} logs", "status": "complete" if decided else ("running" if active else "idle")},
        {"id": "traces", "label": "Inspect correlated render trace", "status": "complete" if decided else "idle"},
        {"id": "impact", "label": "Calculate deterministic delivery impact", "status": "complete" if decided else "idle"},
    ], "evidence": evidence if active else {}}


def sse_message(text: str) -> StreamingResponse:
    event = json.dumps({"content": {"parts": [{"text": text}]}})
    return StreamingResponse(iter([f"data: {event}\n\n"]), media_type="text/event-stream")


@app.post("/agent-fallback/apps/{app_name}/users/{user_id}/sessions/{session_id}")
def mock_agent_session(app_name: str, user_id: str, session_id: str):
    """Compatibility session for a dashboard tab opened before the optional ADK service."""
    return {"id": session_id, "app_name": app_name, "user_id": user_id, "mode": "mock-fallback"}


@app.post("/agent-fallback/run_sse")
def mock_agent_run(payload: dict):
    """Keep the local demo operable when ADK is intentionally not running.

    This endpoint accepts only the legacy, already-approved recovery prompt. It
    never permits a model-created action or bypasses the existing approval ID.
    """
    parts = payload.get("newMessage", {}).get("parts", [])
    prompt = " ".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    match = re.search(r"human operator approves\s+(add-workers|prioritize-scenes|restart-workers|reduce-preview-quality)", prompt, re.I)
    approval_match = re.search(r"approval ID\s+([a-f0-9-]{36})", prompt, re.I)
    if match and approval_match:
        action = match.group(1).lower()
        try:
            outcome = engine.execute(action, approval_match.group(1), "operator-dashboard")
            return sse_message(f"mock-fallback executed approved {outcome['action']}; Grafana verification is in progress.")
        except ValueError as error:
            return sse_message(f"mock-fallback could not execute recovery: {error}")
    return sse_message("mock-fallback investigation complete. Use deterministic recovery options and human approval.")


def recovery_options() -> list[dict]:
    delay = engine.status()["impact"]["projected_delay_minutes"]
    rationale = {"add-workers": "Adds elastic capacity without changing creative priorities.",
                 "prioritize-scenes": "Moves full-film-only work behind the trailer-critical queue.",
                 "restart-workers": "Restores failed capacity, but the original fault could recur.",
                 "reduce-preview-quality": "Trades preview fidelity for fewer frames to render."}
    candidates = []
    for action, spec in RECOVERY_SPECS.items():
        projection = calculate_recovery_option(engine.production, action)
        candidates.append({"plan_id": action, "title": spec["title"], "risk": spec["risk"],
                           "requires_approval": True, "rationale": rationale[action], **projection})
    on_time = [option for option in candidates if option["projected_delay_minutes"] == 0]
    recommended_id = min(on_time or candidates, key=lambda option: option["estimated_added_cost_usd"])["plan_id"]
    options = [{**option, "recommended": option["plan_id"] == recommended_id,
                "recommendation_source": "deterministic-calculator" if option["plan_id"] == recommended_id else None}
               for option in candidates]
    options.append({"plan_id": "take-no-action", "title": "Take no action", "estimated_added_cost_usd": 0,
                    "risk": "high", "deadline_result": f"{int(delay // 60)}h {int(delay % 60)}m late",
                    "recommended": False, "requires_approval": False,
                    "rationale": "Preserves budget but accepts the full delivery delay."})
    return options


def copilot_briefing() -> dict:
    state = engine.status()
    impact = state["impact"]
    if not state["incident_active"]:
        return {"status": "on_track", "headline": "Trailer delivery is protected.",
                "summary": f"{state['gpu_workers_active']} healthy workers are delivering {impact['current_throughput_fph']} frames/hour, above the {impact['required_throughput_fph']} frames/hour required rate.",
                "evidence": ["GPU memory is within its normal operating band.", "Trailer-critical queue is draining ahead of deadline."],
                "next_step": "Continue monitoring. Ask the copilot for a schedule, cost, or scene-level update."}
    scene = "Scene 94" if state["scenario"] == "corrupted_asset" else "Scene 87"
    cause = "the corrupted nova_city.exr asset is forcing retries" if state["scenario"] == "corrupted_asset" else "GPU memory exhaustion has taken eight workers out of service"
    return {"status": "decision_required", "headline": f"{scene} threatens the trailer delivery window.",
            "summary": f"{cause.capitalize()}. Throughput is {impact['current_throughput_fph']} frames/hour against {impact['required_throughput_fph']} required; without intervention the trailer is projected {impact['projected_delay_minutes']} minutes late.",
            "evidence": [f"GPU memory: {state['gpu_memory_utilization']}%", f"Healthy workers: {state['gpu_workers_active']}/{state['gpu_workers_total']}", f"Trailer-critical queue: {state['critical_queue_depth']} frames"],
            "next_step": "Ask for a recovery recommendation or choose a plan; every execution still needs one human approval."}


@app.get("/copilot/briefing")
def copilot_live_briefing():
    return {**copilot_briefing(), "source": "live-project-context"}


@app.post("/copilot/chat")
def copilot_chat(request: CopilotRequest):
    """Grounded local copilot fallback; real Gemini can replace this endpoint later."""
    message = request.message.strip().lower()
    if not message:
        raise HTTPException(400, "message is required")
    state = engine.status()
    briefing = copilot_briefing()
    plans = recovery_options() if state["incident_active"] else []
    suggested_action = None
    if state["incident_active"]:
        if any(word in message for word in ("fix", "recommend", "recover", "option", "do")):
            suggested_action = next((plan["plan_id"] for plan in plans if plan.get("recommended")), None)
        for action, keywords in {"prioritize-scenes": ("priorit", "trailer"), "add-workers": ("worker", "capacity"),
                                 "restart-workers": ("restart",), "reduce-preview-quality": ("quality", "preview")}.items():
            if any(keyword in message for keyword in keywords):
                suggested_action = action
                break
    if "cost" in message and state["incident_active"]:
        answer = "I recalculated the available recovery paths from the current queue and worker capacity. The cards below show their live added cost and delivery result."
    elif any(word in message for word in ("why", "cause", "happen", "diagnos")):
        answer = briefing["summary"] + " The diagnosis is grounded in the active metric, matching structured log, and correlated incident trace."
    elif suggested_action:
        plan = next(plan for plan in plans if plan["plan_id"] == suggested_action)
        answer = f"I recommend {plan['title']}: {plan['rationale']} Its current projection is {plan['deadline_result']} at an added ${plan['estimated_added_cost_usd']}. I can prepare it for your approval."
    else:
        answer = briefing["summary"] + " " + briefing["next_step"]
    return {"answer": answer, "source": "live-project-context", "briefing": briefing,
            "suggested_action": suggested_action, "plans": plans}


@app.get("/recovery-plans")
def plans():
    return {"production_id": "project-nova", "plans": recovery_options() if engine.production.incident_active else []}


@app.post("/approvals")
def request_approval(action: str = Query(...)):
    try:
        approval = engine.request_approval(action)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return {**asdict(approval), "created_at": approval.created_at.isoformat(), "expires_at": approval.expires_at.isoformat()}


def run_recovery(action: str, request: RecoveryRequest):
    try:
        return engine.execute(action, request.approval_id, request.approved_by)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.post("/recovery/add-workers")
def add_workers(request: RecoveryRequest): return run_recovery("add-workers", request)


@app.post("/recovery/prioritize-scenes")
def prioritize_scenes(request: RecoveryRequest): return run_recovery("prioritize-scenes", request)


@app.post("/recovery/restart-workers")
def restart_workers(request: RecoveryRequest): return run_recovery("restart-workers", request)


@app.post("/recovery/reduce-preview-quality")
def reduce_quality(request: RecoveryRequest): return run_recovery("reduce-preview-quality", request)


@app.post("/recovery-plans/{plan_id}/approve")
def compatibility_approve(plan_id: str, approved_by: str = "operator-dashboard"):
    try:
        approval = engine.request_approval(plan_id)
        return engine.execute(plan_id, approval.id, approved_by)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.get("/diagnosis")
def diagnosis():
    state = engine.status()
    incident = state["incident_active"]
    delay = state["impact"]["projected_delay_minutes"]
    return {"production_id": "project-nova", "generated_at": datetime.now(timezone.utc).isoformat(),
            "scenario": state["scenario"], "severity": "critical" if incident else "normal",
            "affected_component": ("asset" if state["scenario"] == "corrupted_asset" else "gpu") if incident else "pipeline",
            "root_cause": ("Scene 94 is retrying because nova_city.exr failed its checksum validation." if state["scenario"] == "corrupted_asset" else "Scene 87 is failing because GPU memory exhaustion stopped eight workers.") if incident else "Production is operating normally.",
            "confidence": .94 if incident else .99,
            "delivery_impact": {"predicted_delay_minutes": delay, "deadline_at_risk": delay > 0, "minutes_late": delay},
            "evidence": {"queue_depth": state["queue_depth"], "active_gpu_workers": state["gpu_workers_active"],
                         "gpu_memory_utilization": state["gpu_memory_utilization"], "storage_utilization": 61,
                         "network_latency_ms": 12,
                         "asset_error_rate": 18 if state["scenario"] == "corrupted_asset" else 0},
            "recommended_plan_id": "prioritize-scenes" if incident else None, "source": "mock-fallback"}


@app.get("/telemetry-history")
def telemetry_history(limit: int = 72):
    return {"production_id": "project-nova", "points": engine.history[-max(2, min(limit, 360)):]}


@app.get("/audit-log")
def audit_log(limit: int = 50):
    return {"production_id": "project-nova", "events": list(reversed(engine.audit[-max(1, min(limit, 300)):]))}


@app.post("/scenario/{scenario}")
def compatibility_scenario(scenario: str):
    if scenario == "gpu_oom": return gpu_oom()
    if scenario == "corrupted_asset": return corrupted_asset()
    if scenario in {"healthy", "recovered"}: return reset()
    raise HTTPException(400, "This demo focuses on healthy, gpu_oom, and recovered states")


@app.get("/scenarios")
def scenarios(): return {"healthy": {}, "gpu_oom": {"scene_id": "SC-87"},
                         "corrupted_asset": {"scene_id": "SC-94", "asset": "nova_city.exr"}, "recovered": {}}
