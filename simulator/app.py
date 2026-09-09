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

from agent_gateway import AgentGateway, production_safe_reply, recommendation_action, structured_briefing
from domain import (INCIDENT_SCENARIOS, ProductionEngine, RECOVERY_SPECS, calculate_delivery_impact,
                    calculate_recovery_option, calculate_what_if)
from incident_memory import IncidentMemory
from portfolio import StudioPortfolio
from director import Director

SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "render-farm-simulator")
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
TICK_SECONDS = float(os.getenv("SIM_TICK_SECONDS", "2"))
# Local development reaches the published ADK port. Compose overrides this with
# the service-to-service hostname inside the Docker network.
AGENT_URL = os.getenv("PRODUCTION_AGENT_URL", "http://127.0.0.1:8090").rstrip("/")
agent_gateway = AgentGateway(
    AGENT_URL,
    float(os.getenv("PRODUCTION_AGENT_CONNECT_TIMEOUT", "8")),
    float(os.getenv("PRODUCTION_AGENT_RESPONSE_TIMEOUT", "95")),
)
def otlp_exporter(kind):
    protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    if protocol == "http/protobuf":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HttpSpan
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as HttpMetric
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter as HttpLog
        exporter = {"traces":HttpSpan,"metrics":HttpMetric,"logs":HttpLog}[kind]
        return exporter(endpoint=f"{OTLP_ENDPOINT.rstrip('/')}/v1/{kind}")
    exporter = {"traces":OTLPSpanExporter,"metrics":OTLPMetricExporter,"logs":OTLPLogExporter}[kind]
    return exporter(endpoint=OTLP_ENDPOINT, insecure=OTLP_ENDPOINT.startswith("http://"))


resource = Resource.create({"service.name": SERVICE_NAME, "production.id": "project-nova"})
trace_provider = TracerProvider(resource=resource)
trace_provider.add_span_processor(BatchSpanProcessor(otlp_exporter("traces")))
trace.set_tracer_provider(trace_provider)
reader = PeriodicExportingMetricReader(otlp_exporter("metrics"), export_interval_millis=5000)
metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_exporter("logs")))
logging.basicConfig(level=logging.INFO, handlers=[LoggingHandler(logger_provider=logger_provider)])
logger = logging.getLogger(SERVICE_NAME)
tracer = trace.get_tracer(SERVICE_NAME)
meter = metrics.get_meter(SERVICE_NAME)
engine = ProductionEngine()
portfolio = StudioPortfolio()
memory = IncidentMemory()
director = Director(engine, portfolio, memory, agent_gateway)
last_execution = None


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


meter.create_observable_gauge("render.storage.utilization", callbacks=[production_metric(lambda state: state["storage_utilization"])], unit="%")
meter.create_observable_gauge("render.network.latency", callbacks=[production_metric(lambda state: state["network_latency_ms"])], unit="ms")
meter.create_observable_gauge("render.asset.error.rate", callbacks=[production_metric(lambda state: state["asset_error_rate"])], unit="%")
meter.create_observable_gauge("render.cost.estimated", callbacks=[production_metric(lambda state: state["impact"]["baseline_cost_usd"])], unit="USD")
meter.create_observable_gauge("render.failures", callbacks=[production_metric(lambda _: engine.production.scenes["SC-87"].failed_frames)], unit="{failure}")


def condition_observation(_):
    state = engine.status()
    scenario = state["scenario"]
    return [metrics.Observation(1, {"production.id": "project-nova", "scenario": scenario,
                                    "severity": "critical" if state["incident_active"] else "normal",
                                    "component": "gpu" if scenario == "gpu_oom" else "pipeline"})]


meter.create_observable_gauge("render.condition", callbacks=[condition_observation], unit="1")


def portfolio_observation(field: str):
    def callback(_):
        return [metrics.Observation(item[field], {"production.id": item["id"]})
                for item in portfolio.snapshot()["productions"]]
    return callback


meter.create_observable_gauge("render.portfolio.workers.allocated",
                              callbacks=[portfolio_observation("allocated_workers")], unit="{worker}")
meter.create_observable_gauge("render.portfolio.throughput",
                              callbacks=[portfolio_observation("throughput_fph")], unit="{frame}/h")
meter.create_observable_gauge("render.portfolio.required.throughput",
                              callbacks=[portfolio_observation("required_throughput_fph")], unit="{frame}/h")
meter.create_observable_gauge("render.portfolio.predicted.delay",
                              callbacks=[portfolio_observation("delay_minutes")], unit="min")


class RecoveryRequest(BaseModel):
    approval_id: str
    approved_by: str = "operator-dashboard"


class WhatIfRequest(BaseModel):
    workers_added: int = Field(default=0, ge=0, le=10)
    deadline_minutes: int | None = Field(default=None, ge=15)
    quality_percent: int = Field(default=100, ge=50, le=100)
    prioritize_critical: bool = False


class CopilotRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    incident_id: str | None = None


class PortfolioAllocationRequest(BaseModel):
    approval_id: str
    approved_by: str = "operator-dashboard"


def friendly_briefing(state: dict, plans: list[dict]) -> dict:
    incident_type = state["scenario"]
    scenario = next((item for item in INCIDENT_SCENARIOS.values()
                     if item["issue_type"] == incident_type), INCIDENT_SCENARIOS["gpu-oom"])
    recommended = next((plan for plan in plans if plan.get("recommended")), None)
    affected_area = scenario["affected_area"]
    symptoms = scenario["condition"]
    similar = memory.similar_case(incident_type, affected_area, symptoms) if state["incident_active"] else None
    condition = scenario["condition"]
    impact = scenario["impact"]
    facts = [f"{scenario['scene_id'].replace('SC-', 'Scene ')} is affected", scenario["threshold"],
             f"The current forecast is {round(state['impact']['projected_delay_minutes'])} minutes late"]
    if state.get("recovery_failed"):
        phase = "reassessment"
        status_line = "The first recovery did not protect the schedule, so I've prepared a revised decision."
    elif state.get("recovery_progress", 0) > 0:
        phase = "monitoring"
        status_line = "I'm monitoring the approved recovery and will confirm the delivery forecast when it finishes."
    elif state["workflow_state"] == "INVESTIGATING":
        phase = "investigating"
        status_line = "I've detected a production issue and I'm checking the effect on the trailer."
    else:
        phase = "recommendation"
        status_line = "Here's what I recommend."
    recommendation = None
    if recommended:
        recommendation = {
            "action": recommended["plan_id"], "title": recommended["title"],
            "reason": recommended["rationale"], "deadline_result": recommended["deadline_result"],
            "added_cost_usd": recommended["estimated_added_cost_usd"], "risk": recommended["risk"],
        }
    past_case = None
    if similar:
        past_case = {
            "production_title": similar["production_title"],
            "deliverable_title": similar["deliverable_title"],
            "summary": similar["condition_summary"],
            "action": similar["recovery_action"],
            "outcome": similar["outcome_summary"],
        }
    assistant_message = (f"{status_line} I’ll keep the recommendation updated as the schedule changes. "
                         "Ask me about the impact, cost, risks, alternatives, or similar earlier productions.")
    return {
        "phase": phase, "status_line": status_line, "condition": condition, "impact": impact,
        "production_title": state["production_title"], "deliverable_title": state["trailer"]["title"],
        "scene": scenario["scene_id"].replace("SC-", "Scene "),
        "recommendation": recommendation, "similar_case": past_case, "facts": facts,
        "next_step": "Review the recommendation, ask me a question, or compare the alternatives before approving anything.",
        "assistant_message": assistant_message,
    }


def analysis_facts():
    state = engine.status()
    incident = memory.incident(director.incident_id) if director.incident_id else None
    previous_case = memory.similar_case(incident['incident_type']) if incident else None
    return {"production": state, "portfolio": portfolio.snapshot(),
            "previous_incident": previous_case,
            "forecast_windows": {"portfolio": "12-hour Nova / 24-hour Silverline planning window", "incident": "immediate trailer delivery window"},
            "plans": recovery_options(excluded_actions={state['last_failed_action']} if state.get('last_failed_action') else None) if state['incident_active'] else [],
            "verification": verification_comparison() if state.get('recovery_progress') else {"available": False}}


def start_incident_review(phase="investigation"):
    facts = analysis_facts()
    actions = [p['plan_id'] for p in facts['plans'] if p.get('requires_approval')]
    return director.start(phase, facts, actions)


def begin_reassessment(state):
    start_incident_review("reassessment")


def emit_evidence_event(scope_id, event_type):
    with tracer.start_as_current_span(event_type) as span:
        span.set_attribute("production.id", "project-nova")
        span.set_attribute("scope.id", scope_id)
        trace_id = format(span.get_span_context().trace_id, "032x")
        director.set_event(scope_id, trace_id)
        engine.production.incident_trace_id = trace_id
        log = logger.error if event_type.endswith(('injected', 'failed')) else logger.info
        log(json.dumps({"event_type": event_type, "scope_id": scope_id,
            "trace_id": trace_id, "production_id": "project-nova", "condition": engine.status()['scenario']}))
    flush_incident_evidence()


def start_verification(execution_id, portfolio_mode=False, retry=False):
    if not retry:
        emit_evidence_event(director.scope_id, "allocation.completed" if portfolio_mode else "recovery.completed")
    facts = analysis_facts()
    facts['execution_id'] = execution_id
    def complete(result):
        if not portfolio_mode and result.get('ok') and engine.production.verification_complete:
            memory.resolve_active('project-nova', last_execution['action'] if last_execution else None,
                                  'Simulator recovery and fresh Grafana evidence verified the trailer forecast.')
    key = f'{director.scope_id}:verification:{execution_id}' + (f':retry:{time.time_ns()}' if retry else '')
    return director.start('verification', facts, [], key=key, on_complete=complete)


app = FastAPI(title="AI Production Director — Project Nova", version="1.0.0")
FastAPIInstrumentor.instrument_app(app, tracer_provider=trace_provider)


def simulation_loop() -> None:
    while True:
        with director.lock:
            before = engine.status()
            engine.tick()
            state = engine.status()
            if state['verification_complete'] and not before['verification_complete'] and last_execution:
                start_verification(last_execution['execution_id'])
            if state['recovery_failed'] and not before['recovery_failed']:
                emit_evidence_event(director.scope_id, 'recovery.failed')
                begin_reassessment(state)
        time.sleep(TICK_SECONDS)


@app.on_event("startup")
def startup() -> None:
    state = engine.status()
    memory.upsert_production(state["production_id"], state["production_title"])
    memory.resolve_active(state["production_id"], None,
                          "The simulator restarted before live recovery verification; no success was recorded.")
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
    global last_execution
    with director.lock:
        memory.resolve_active("project-nova", None, "The demonstration was reset before a verified recovery.")
        director.reset()
        last_execution = None
        return engine.status()


def flush_incident_evidence():
    """Export the new incident before the agent begins its investigation."""
    trace_provider.force_flush(timeout_millis=3000)
    logger_provider.force_flush(timeout_millis=3000)
    reader.collect()


def raise_scenario(scenario_id: str):
    scenario = INCIDENT_SCENARIOS.get(scenario_id)
    if not scenario:
        raise HTTPException(404, "Incident scenario not found")
    with director.lock:
        if engine.production.incident_active or (director.public_run() or {}).get('status') == 'running':
            raise HTTPException(409, "Finish the current live review before raising another issue")
        engine.inject_incident(scenario_id)
        state = engine.status()
        briefing = friendly_briefing(state, recovery_options())
        incident = memory.raise_incident('project-nova', state['production_title'], scenario['issue_type'],
                                        scenario['scene_id'], scenario['condition'], briefing)
        director.incident_id = incident['id']
        emit_evidence_event(incident['id'], f"incident.{scenario['issue_type']}")
        start_incident_review()
        return {**engine.status(), "incident_id": incident['id'], "agent_run_status": "investigating"}


@app.get("/simulation/incidents/catalog")
def incident_catalog():
    return {"scenarios": [{"id": scenario_id, **scenario}
                           for scenario_id, scenario in INCIDENT_SCENARIOS.items()]}


@app.get("/simulation/thresholds")
def production_thresholds():
    state = engine.status()
    readings = {"gpu_memory_percent": state["gpu_memory_utilization"],
                "healthy_worker_percent": round(state["gpu_workers_active"] / state["gpu_workers_total"] * 100, 1),
                "storage_percent": state["storage_utilization"], "network_latency_ms": state["network_latency_ms"],
                "asset_error_percent": state["asset_error_rate"],
                "available_throughput_fph": state["impact"]["current_throughput_fph"],
                "required_throughput_fph": state["impact"]["required_throughput_fph"]}
    return {"production_id": state["production_id"], "readings": readings,
            "active_breaches": [scenario["threshold"] for scenario in INCIDENT_SCENARIOS.values()
                                if state["incident_active"] and scenario["issue_type"] == state["scenario"]]}


@app.post("/simulation/incidents/gpu-oom")
def gpu_oom(): return raise_scenario("gpu-oom")


@app.post("/simulation/incidents/corrupted-asset")
def corrupted_asset(): return raise_scenario("corrupted-asset")


@app.post("/simulation/incidents/{scenario_id}")
def inject_incident_scenario(scenario_id: str): return raise_scenario(scenario_id)


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
    portfolio_state = portfolio.snapshot()
    portfolio_lines = []
    for production in portfolio_state["productions"]:
        labels = f'production_id="{production["id"]}"'
        portfolio_lines.extend([
            f'render_portfolio_workers_allocated{{{labels}}} {production["allocated_workers"]}',
            f'render_portfolio_throughput_fph{{{labels}}} {production["throughput_fph"]}',
            f'render_portfolio_required_throughput_fph{{{labels}}} {production["required_throughput_fph"]}',
            f'render_portfolio_delay_minutes{{{labels}}} {production["delay_minutes"]}',
        ])
    return "\n".join([
        "# HELP render_current_throughput_fph Trailer render throughput",
        "# TYPE render_current_throughput_fph gauge",
        f"render_current_throughput_fph{{production_id=\"project-nova\"}} {state['impact']['current_throughput_fph']}",
        f"render_required_throughput_fph{{production_id=\"project-nova\"}} {state['impact']['required_throughput_fph']}",
        f"render_critical_queue_depth{{production_id=\"project-nova\"}} {state['critical_queue_depth']}",
        f"render_scene_failures{{production_id=\"project-nova\",scene_id=\"SC-87\"}} {engine.production.scenes['SC-87'].failed_frames}",
        f"render_storage_utilization{{production_id=\"project-nova\"}} {state['storage_utilization']}",
        f"render_network_latency_ms{{production_id=\"project-nova\"}} {state['network_latency_ms']}",
        f"render_asset_error_rate{{production_id=\"project-nova\"}} {state['asset_error_rate']}",
        *portfolio_lines,
    ]) + "\n"


@app.get("/portfolio")
def portfolio_snapshot():
    return {**portfolio.snapshot(), "agent_run": director.public_run(), "can_approve": director.can_approve()}


@app.post("/portfolio/scenarios/deadline-conflict")
def portfolio_deadline_conflict():
    try:
        with director.lock:
            if engine.production.incident_active:
                raise ValueError("resolve the incident first")
            snapshot = portfolio.start_deadline_conflict()
            emit_evidence_event(snapshot['active_decision']['id'], 'portfolio.deadline_conflict')
            director.start('portfolio', analysis_facts(), [o['id'] for o in snapshot['allocation_options'] if o['requires_approval']])
            return portfolio_snapshot()
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.post("/portfolio/approvals")
def portfolio_approval(option_id: str = Query(...)):
    try:
        if not director.can_approve() and option_id != 'restore-initial-allocation':
            raise ValueError("wait for the live review or explicitly select calculated mode")
        approval = portfolio.request_approval(option_id)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return {**asdict(approval), "created_at": approval.created_at.isoformat(),
            "expires_at": approval.expires_at.isoformat()}


@app.post("/portfolio/allocations/{option_id}")
def portfolio_allocation(option_id: str, request: PortfolioAllocationRequest):
    try:
        with director.lock:
            if engine.production.incident_active or (director.public_run() or {}).get('status') == 'running':
                raise ValueError("an incident or live review is in progress")
            result = portfolio.execute(option_id, request.approval_id, request.approved_by)
            director.sync_workers()
            start_verification(result['execution_id'], portfolio_mode=True)
            return result
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.get("/portfolio/verification")
def portfolio_verification():
    return portfolio.verification()


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
    run = director.public_run() or {}
    evidence = {e['tool']:e for e in run.get('evidence',[])}
    steps = []
    for tool, label in [('grafana_query_metrics','Query Grafana metrics'),('grafana_query_logs','Read correlated event'),('grafana_query_traces','Inspect correlated trace')]:
        result = evidence.get(tool)
        steps.append({'id':tool,'label':label,'status':'complete' if result and result['ok'] else 'failed' if result else 'running' if run.get('status')=='running' else 'idle'})
    return {'mode':run.get('source','pending'), 'workflow_state':engine.status()['workflow_state'],
            'steps':steps, 'evidence':{key:value.get('query','') for key,value in evidence.items()}}


def sse_message(text: str) -> StreamingResponse:
    event = json.dumps({"content": {"parts": [{"text": text}]}})
    return StreamingResponse(iter([f"data: {event}\n\n"]), media_type="text/event-stream")


@app.post("/agent-fallback/apps/{app_name}/users/{user_id}/sessions/{session_id}")
def mock_agent_session(app_name: str, user_id: str, session_id: str):
    raise HTTPException(503, "The live ADK agent is unavailable. Retry the connection.")


@app.post("/agent-fallback/run_sse")
def mock_agent_run(payload: dict):
    raise HTTPException(503, "The live ADK agent is unavailable. Select calculated mode explicitly in the dashboard.")


def recovery_options(agent_recommendation: str | None = None,
                     excluded_actions: set[str] | None = None) -> list[dict]:
    delay = engine.status()["impact"]["projected_delay_minutes"]
    rationale = {"add-workers": "Adds elastic capacity without changing creative priorities.",
                 "prioritize-scenes": "Moves full-film-only work behind the trailer-critical queue.",
                 "restart-workers": "Restores failed capacity, but the original fault could recur.",
                 "reduce-preview-quality": "Trades preview fidelity for fewer frames to render.",
                 "rebalance-queue": "Spreads urgent trailer work evenly across available render capacity.",
                 "release-storage": "Clears replaceable temporary files while preserving production masters.",
                 "reroute-transfers": "Moves Scene 84 through a healthy transfer route without changing the edit.",
                 "restore-asset": "Replaces the damaged Scene 94 artwork with its last verified production copy."}
    candidates = []
    for action, spec in RECOVERY_SPECS.items():
        if action in (excluded_actions or set()):
            continue
        if engine.production.incident_type not in spec.get("incident_types", set()):
            continue
        projection = calculate_recovery_option(engine.production, action)
        candidates.append({"plan_id": action, "title": spec["title"], "risk": spec["risk"],
                           "requires_approval": True, "rationale": rationale[action], **projection})
    on_time = [option for option in candidates if option["projected_delay_minutes"] == 0]
    risk_rank = {"low": 0, "medium": 1, "high": 2}
    creative_penalty = {"restart-workers": 0, "add-workers": 0, "prioritize-scenes": 1,
                        "reduce-preview-quality": 2}
    calculated_id = min(
        on_time or candidates,
        key=lambda option: (risk_rank[option["risk"]], creative_penalty.get(option["plan_id"], 0),
                            option["estimated_added_cost_usd"]),
    )["plan_id"] if candidates else None
    candidate_ids = {option["plan_id"] for option in candidates}
    recommended_id = agent_recommendation if agent_recommendation in candidate_ids else calculated_id
    options = [{**option, "recommended": option["plan_id"] == recommended_id,
                "recommendation_source": "ai-production-director" if agent_recommendation == recommended_id
                else "deterministic-calculator" if option["plan_id"] == recommended_id else None}
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
    scenario = next(item for item in INCIDENT_SCENARIOS.values() if item['issue_type'] == state['scenario'])
    scene = scenario['scene_id'].replace('SC-', 'Scene ')
    cause = scenario['condition'].rstrip('.')
    return {"status": "decision_required", "headline": f"{scene} threatens the trailer delivery window.",
            "summary": f"{cause.capitalize()}. Throughput is {impact['current_throughput_fph']} frames/hour against {impact['required_throughput_fph']} required; without intervention the trailer is projected {impact['projected_delay_minutes']} minutes late.",
            "evidence": [f"GPU memory: {state['gpu_memory_utilization']}%", f"Healthy workers: {state['gpu_workers_active']}/{state['gpu_workers_total']}", f"Trailer-critical queue: {state['critical_queue_depth']} frames"],
            "next_step": "Ask for a recovery recommendation or choose a plan; every execution still needs one human approval."}


def fallback_conversation_answer(message: str, state: dict, briefing: dict, plans: list[dict]) -> tuple[str, str | None]:
    question = message.lower()
    recommendation = briefing.get("recommendation")
    suggested = recommendation["action"] if recommendation and any(
        word in question for word in ("recommend", "fix", "plan", "option", "do")
    ) else None
    if any(word in question for word in ("past", "before", "similar", "previous")):
        case = briefing.get("similar_case")
        answer = (f"We saw a similar issue on the {case['deliverable_title']}. {case['outcome']} "
                  "I have still recalculated the plan for Project Nova's current schedule."
                  if case else "I don't have a verified past case close enough to use for this issue.")
    elif "cost" in question and recommendation:
        answer = (f"The recommended plan adds ${recommendation['added_cost_usd']:.0f}. "
                  f"Its current delivery result is {recommendation['deadline_result'].lower()}. "
                  "I can also compare the alternatives before you approve anything.")
    elif any(word in question for word in ("risk", "trade", "creative")) and recommendation:
        answer = (f"I rate this as {recommendation['risk']} risk. {recommendation['reason']} "
                  "The plan changes production order or capacity; it does not change approved creative work unless you choose a quality-reduction option.")
    elif any(word in question for word in ("why", "happen", "condition", "status", "scene", "schedule", "trailer")):
        answer = f"{briefing['condition']} {briefing['impact']}"
    elif recommendation:
        answer = (f"I recommend {recommendation['title']}. {recommendation['reason']} "
                  f"The current forecast is {recommendation['deadline_result'].lower()} with ${recommendation['added_cost_usd']:.0f} added cost."
                  if suggested else f"{briefing['status_line']} Ask me about the schedule, scenes, cost, risks, alternatives, or the earlier similar case.")
    else:
        answer = briefing["status_line"]
    return answer, suggested


def assistant_snapshot(production_id: str) -> dict:
    if production_id != engine.production.id:
        raise HTTPException(404, "Production not found")
    state = engine.status()
    incident = memory.incident(director.incident_id) if director.incident_id else None
    live = director.public_run()
    selected = live.get('recommended_action') if live and live.get('ok') else None
    plans = recovery_options(selected, {state['last_failed_action']} if state.get('last_failed_action') else None) if state['incident_active'] else []
    briefing = friendly_briefing(state, plans) if state['incident_active'] else None
    if briefing and live:
        for key in ('condition','impact','next_step'):
            if live.get('ok') and live.get('fields',{}).get(key):
                briefing[key] = live['fields'][key]
        if live.get('ok') and live.get('fields',{}).get('recommendation_reason'):
            for plan in plans:
                if plan['recommended']:
                    plan['rationale'] = live['fields']['recommendation_reason']
        if live['status'] == 'running':
            briefing['status_line'] = 'I’m reviewing current production evidence.'
            briefing['next_step'] = 'Checking Grafana and comparing delivery options before recommending a decision.'
        elif live['status'] == 'unavailable':
            briefing['status_line'] = 'The live review needs attention.'
            briefing['next_step'] = live.get('error') or 'Retry the live review.'
    run = {**live, 'briefing': briefing, 'incident_id': director.incident_id} if live else None
    return {"production_id": production_id, "incident": incident, "run": run, "briefing": briefing,
            "messages": memory.messages(production_id, director.incident_id or director.scope_id), "plans": plans,
            "can_approve": director.can_approve(), "calculated_mode": director.calculated_mode}


@app.get("/productions/{production_id}/assistant")
def production_assistant(production_id: str):
    return assistant_snapshot(production_id)


@app.get("/productions/{production_id}/incidents/{incident_id}")
def production_incident(production_id: str, incident_id: str):
    incident = memory.incident(incident_id)
    if not incident or incident["production_id"] != production_id:
        raise HTTPException(404, "Incident not found")
    scenario = next((item for item in INCIDENT_SCENARIOS.values()
                     if item["issue_type"] == incident["incident_type"]), None)
    area = scenario["affected_area"] if scenario else "production pipeline"
    run = memory.run_for_incident(incident_id)
    if run:
        run["source"] = run.get("source", "unavailable")
    return {"incident": incident, "run": run,
            "similar_case": memory.similar_case(incident["incident_type"], area, incident["condition_summary"])}


@app.get("/productions/{production_id}/cases/similar")
def production_similar_case(production_id: str, incident_id: str = Query(...)):
    incident = memory.incident(incident_id)
    if not incident or incident["production_id"] != production_id:
        raise HTTPException(404, "Incident not found")
    scenario = next((item for item in INCIDENT_SCENARIOS.values()
                     if item["issue_type"] == incident["incident_type"]), None)
    area = scenario["affected_area"] if scenario else "production pipeline"
    return {"case": memory.similar_case(incident["incident_type"], area, incident["condition_summary"])}


@app.post("/productions/{production_id}/assistant/messages")
def production_assistant_message(production_id: str, request: CopilotRequest):
    if production_id != engine.production.id:
        raise HTTPException(404, "Production not found")
    clean = request.message.strip()
    if not clean:
        raise HTTPException(400, "Message is required")
    incident_id = director.incident_id
    scope_id = director.scope_id
    if request.incident_id and request.incident_id != incident_id:
        raise HTTPException(409, "The production context changed; refresh and ask again")
    if (director.public_run() or {}).get('status') == 'running':
        raise HTTPException(409, "The live review is still running. Please wait for its result.")
    try:
        answer = director.chat(clean, analysis_facts())
    except Exception as error:
        raise HTTPException(503, "The live answer is unavailable. Your message has been kept; please retry.") from error
    with director.lock:
        if scope_id != director.scope_id:
            raise HTTPException(409, "The production context changed; please ask again")
        memory.add_message(production_id, incident_id or scope_id, 'operator', clean)
        message = memory.add_message(production_id, incident_id or scope_id, 'assistant', answer)
    return {'message': message, 'answer': answer, 'suggested_action': None,
            'briefing': assistant_snapshot(production_id)['briefing'], 'plans': [], 'source': 'live-agent'}


@app.get('/readiness')
def readiness():
    return director.readiness()


@app.get('/evidence-context')
def evidence_context():
    return dict(director.event)


@app.post('/agent/calculated-mode')
def calculated_mode():
    if (director.public_run() or {}).get('status') == 'running':
        raise HTTPException(409, 'Wait for the current live review')
    director.calculated_mode = True
    return {'source': 'deterministic-calculator', 'enabled': True}


@app.post('/agent/retry')
def retry_analysis():
    run = director.public_run()
    if run and run['status'] == 'running':
        raise HTTPException(409, 'A live review is already running')
    if not run:
        raise HTTPException(409, 'Start a scenario first')
    if run['phase'] == 'verification':
        execution_id = run.get('execution_id') or run['id'].split(':verification:', 1)[-1].split(':retry:', 1)[0]
        start_verification(execution_id, portfolio_mode=not engine.production.verification_complete, retry=True)
    elif engine.production.incident_active:
        start_incident_review('reassessment' if engine.production.last_failed_action else 'investigation')
    else:
        director.start('portfolio', analysis_facts(), [o['id'] for o in portfolio.calculate_options() if o['requires_approval']])
    return {'status': 'running'}


@app.get("/copilot/briefing")
def copilot_live_briefing():
    return {**copilot_briefing(), "source": "live-project-context"}


@app.post("/copilot/chat")
def copilot_chat(request: CopilotRequest):
    """Compatibility wrapper for older dashboard bundles."""
    result = production_assistant_message("project-nova", request)
    legacy_briefing = copilot_briefing()
    return {"answer": result["answer"], "source": result["source"], "briefing": legacy_briefing,
            "suggested_action": result["suggested_action"], "plans": result["plans"]}


@app.get("/recovery-plans")
def plans():
    state = engine.status()
    incident = memory.active_incident(state["production_id"])
    run = memory.run_for_incident(incident["id"]) if incident else None
    excluded = {state["last_failed_action"]} if state.get("last_failed_action") else None
    return {"production_id": "project-nova",
            "plans": recovery_options(run.get("recommended_action") if run else None, excluded)
            if engine.production.incident_active else []}


@app.post("/approvals")
def request_approval(action: str = Query(...)):
    try:
        if not director.can_approve():
            raise ValueError("wait for the live review or explicitly choose calculated mode")
        approval = engine.request_approval(action)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    incident = memory.active_incident(engine.production.id)
    memory.record_decision(engine.production.id, incident["id"] if incident else None, action,
                           "approval-created", approval.id)
    return {**asdict(approval), "created_at": approval.created_at.isoformat(), "expires_at": approval.expires_at.isoformat()}


def run_recovery(action: str, request: RecoveryRequest):
    global last_execution
    try:
        with director.lock:
            if not director.can_approve():
                raise ValueError("the live decision is not ready")
            result = engine.execute(action, request.approval_id, request.approved_by)
            director.register_temporary_workers()
            last_execution = {**result, 'action': action}
            director.calculated_mode = False
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    incident = memory.active_incident(engine.production.id)
    memory.record_decision(engine.production.id, incident["id"] if incident else None, action,
                           "executing", request.approval_id, request.approved_by)
    memory.add_message(engine.production.id, incident["id"] if incident else None, "assistant",
                       f"The team approved {RECOVERY_SPECS[action]['title'].lower()}. I'm monitoring the recovery now.")
    return result


@app.post("/recovery/add-workers")
def add_workers(request: RecoveryRequest): return run_recovery("add-workers", request)


@app.post("/recovery/prioritize-scenes")
def prioritize_scenes(request: RecoveryRequest): return run_recovery("prioritize-scenes", request)


@app.post("/recovery/restart-workers")
def restart_workers(request: RecoveryRequest): return run_recovery("restart-workers", request)


@app.post("/recovery/reduce-preview-quality")
def reduce_quality(request: RecoveryRequest): return run_recovery("reduce-preview-quality", request)


@app.post("/recovery/{action}")
def scenario_recovery(action: str, request: RecoveryRequest):
    """Approval-gated route for incident-specific actions exposed to the ADK agent."""
    return run_recovery(action, request)


@app.post("/recovery-plans/{plan_id}/approve")
def compatibility_approve(plan_id: str, approved_by: str = "operator-dashboard"):
    approval = request_approval(plan_id)
    return run_recovery(plan_id, RecoveryRequest(approval_id=approval['id'], approved_by=approved_by))


@app.get("/diagnosis")
def diagnosis():
    state = engine.status()
    incident = state["incident_active"]
    delay = state["impact"]["projected_delay_minutes"]
    scenario = next((item for item in INCIDENT_SCENARIOS.values()
                     if item["issue_type"] == state["scenario"]), None)
    active_incident = memory.active_incident(state["production_id"])
    run = memory.run_for_incident(active_incident["id"]) if active_incident else None
    return {"production_id": "project-nova", "generated_at": datetime.now(timezone.utc).isoformat(),
            "scenario": state["scenario"], "severity": "critical" if incident else "normal",
            "affected_component": scenario["affected_area"] if scenario else "pipeline",
            "root_cause": scenario["condition"] if scenario else "Production is operating normally.",
            "confidence": .94 if incident else .99,
            "delivery_impact": {"predicted_delay_minutes": delay, "deadline_at_risk": delay > 0, "minutes_late": delay},
            "evidence": {"queue_depth": state["queue_depth"], "active_gpu_workers": state["gpu_workers_active"],
                         "gpu_memory_utilization": state["gpu_memory_utilization"],
                         "storage_utilization": state["storage_utilization"],
                         "network_latency_ms": state["network_latency_ms"],
                         "asset_error_rate": state["asset_error_rate"]},
            "recommended_plan_id": run.get("recommended_action") if run else None,
            "source": "Deterministic simulator"}


@app.get("/telemetry-history")
def telemetry_history(limit: int = 72):
    return {"production_id": "project-nova", "points": engine.history[-max(2, min(limit, 360)):]}


@app.get("/audit-log")
def audit_log(limit: int = 50):
    capped = max(1, min(limit, 300))
    events = sorted([*engine.audit, *portfolio.audit], key=lambda event: event["timestamp"], reverse=True)
    return {"production_id": "studio-portfolio", "events": events[:capped]}


@app.post("/scenario/{scenario}")
def compatibility_scenario(scenario: str):
    scenario_id = scenario.replace("_", "-")
    if scenario_id in INCIDENT_SCENARIOS: return raise_scenario(scenario_id)
    if scenario in {"healthy", "recovered"}: return reset()
    raise HTTPException(400, "Unknown production scenario")


@app.get("/scenarios")
def scenarios():
    return {"healthy": {}, **{item["issue_type"]: {"scene_id": item["scene_id"],
                                                    "threshold": item["threshold"]}
                              for item in INCIDENT_SCENARIOS.values()}, "recovered": {}}
