"""Google ADK agent for the Project Nova demo.

The Grafana MCP toolset is enabled when GRAFANA_MCP_URL is configured. The local
functions remain explicit tools so all deadline and cost values come from the
simulator's deterministic calculator rather than the model.
"""
import json
import os
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from .grafana_tools import grafana_query_logs, grafana_query_metrics, grafana_query_traces

SIMULATOR_URL = os.getenv("SIMULATOR_URL", "http://localhost:8080")


def api(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(f"{SIMULATOR_URL}{path}", data=body, method=method,
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except URLError as error:
        return {"error": f"simulator unavailable: {error.reason}"}


def get_production_context() -> dict:
    """Get Project Nova deliverables, scenes, workers, and schedule context."""
    context = api("/production/context")
    if isinstance(context.get("status"), dict):
        context["status"].pop("scenario", None)
    return context


def calculate_delivery_impact() -> dict:
    """Calculate delivery ETA, delay, cost, and required throughput deterministically."""
    return api("/impact")


def generate_recovery_options() -> dict:
    """Return only the allowlisted recovery options with deterministic cost and deadline effects."""
    return api("/recovery-plans")


def request_human_approval(action: str) -> dict:
    """Create a short-lived, single-use approval request for an allowlisted action."""
    return api(f"/approvals?action={action}", "POST")


def execute_recovery(action: str, approval_id: str, approved_by: str) -> dict:
    """Execute an allowlisted recovery only after a human supplies its approval ID."""
    return api(f"/recovery/{action}", "POST", {"approval_id": approval_id, "approved_by": approved_by})


def verify_recovery() -> dict:
    """Wait briefly and return deterministic post-action recovery verification."""
    state = api("/simulation/status")
    for _ in range(20):
        if state.get("verification_complete"):
            return state
        time.sleep(1)
        state = api("/simulation/status")
    return state


tools: list = [grafana_query_metrics, grafana_query_logs, grafana_query_traces,
               get_production_context, calculate_delivery_impact, generate_recovery_options,
               request_human_approval, execute_recovery, verify_recovery]

root_agent = Agent(
    name="ai_production_director",
    model=Gemini(model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash")),
    instruction="""You are the AI Production Director for Project Nova.
Follow exactly: Detect, Investigate, Correlate, Diagnose, Calculate, Recommend, Approve, Execute, Verify.
For an investigation, call grafana_query_metrics, grafana_query_logs, and grafana_query_traces exactly
once each before diagnosing. Then call calculate_delivery_impact and generate_recovery_options exactly
once each. Never infer an incident from simulator scenario data. Cite the returned metric query, matching
Scene 87 CUDA OOM log, and correlated Tempo trace ID.
Use calculate_delivery_impact for every ETA or cost; never estimate those values yourself. Recommend
only returned allowlisted actions. Never call execute_recovery without a human-provided approval ID.
After execution, query metrics, logs, and traces once more and call verify_recovery before declaring
production saved. Keep the final response below 350 words and state that evidence came through Grafana MCP.""",
    tools=tools,
    generate_content_config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=900),
)
app = App(root_agent=root_agent, name="production_director_agent")
