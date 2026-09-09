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
from pydantic import BaseModel

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
        if state.get("verification_complete") or state.get("recovery_failed"):
            return state
        time.sleep(1)
        state = api("/simulation/status")
    return state


def get_portfolio_context() -> dict:
    """Return both productions, the shared worker pool, and the active decision."""
    return api("/portfolio")


def calculate_allocation_options() -> dict:
    """Return only calculator-owned allocation options and their impacts."""
    snapshot = api("/portfolio")
    return {"scenario": snapshot.get("scenario"), "options": snapshot.get("allocation_options", []),
            "recommendation": snapshot.get("recommendation")}


def verify_portfolio_allocation() -> dict:
    """Verify worker conservation and both delivery forecasts after allocation."""
    return api("/portfolio/verification")


tools: list = [grafana_query_metrics, grafana_query_logs, grafana_query_traces,
               get_production_context, calculate_delivery_impact, generate_recovery_options,
               verify_recovery, get_portfolio_context, calculate_allocation_options,
               verify_portfolio_allocation]

def configure_thinking(callback_context, llm_request):
    """Keep tool investigations deliberate and ordinary conversation responsive."""
    current = []
    text = ""
    for content in llm_request.contents:
        candidate = " ".join(part.text or "" for part in (content.parts or []))
        if content.role == "user" and candidate.startswith(("INVESTIGATION", "PORTFOLIO", "REASSESSMENT", "VERIFICATION", "FOLLOW_UP", "FORMAT_REPAIR")):
            text, current = candidate, []
        current.append(content)
    llm_request.config.thinking_config = types.ThinkingConfig(
        thinking_level="LOW" if "FOLLOW_UP" in text or "FORMAT_REPAIR" in text else "MEDIUM"
    )
    # Bound each invocation: successful evidence is already in the context, and
    # each adapter owns its bounded ingestion retry. Never poll through the LLM.
    called = {p.function_response.name for c in current for p in (c.parts or []) if p.function_response}
    allowed = {"grafana_query_metrics", "grafana_query_logs", "grafana_query_traces"}
    if text.startswith("PORTFOLIO"):
        allowed |= {"get_portfolio_context", "calculate_allocation_options"}
    elif text.startswith("VERIFICATION"):
        allowed.add("verify_portfolio_allocation" if "Verification target: portfolio." in text else "verify_recovery")
    elif text.startswith(("FOLLOW_UP", "FORMAT_REPAIR")):
        allowed = set()
    else:
        allowed |= {"get_production_context", "calculate_delivery_impact", "generate_recovery_options"}
    allowed -= called
    allowed.add("set_model_response")
    remaining = []
    for tool in llm_request.config.tools or []:
        declarations = [f for f in (tool.function_declarations or []) if f.name in allowed]
        if declarations:
            remaining.append(types.Tool(function_declarations=declarations))
    llm_request.config.tools = remaining or None
    if not remaining:
        llm_request.config.tool_config = None


class DirectorResponse(BaseModel):
    answer: str
    recommended_action: str | None
    condition: str = ""
    impact: str = ""
    recommendation_reason: str = ""
    next_step: str = ""


root_agent = Agent(
    name="ai_production_director",
    model=Gemini(model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash")),
    instruction="""You are the AI Production Director for Project Nova and Silverline.
Help film producers understand the production issue, evidence, delivery impact, options, and next decision.
Explain specific facts and tradeoffs. Answer the actual question; never substitute a generic reassurance.
Distinguish observed Grafana evidence from deterministic forecasts and synthetic demonstration data.
For INVESTIGATION, PORTFOLIO, REASSESSMENT or VERIFICATION, call grafana_query_metrics,
grafana_query_logs and grafana_query_traces once each. Adapters retry ingestion internally.
For portfolio planning call get_portfolio_context and calculate_allocation_options.
Select only an option ID returned by calculate_allocation_options. Recommend transfer-four-workers
only when the calculator marks it recommended. For incident planning call calculate_delivery_impact
and generate_recovery_options. Select only a currently executable action from the supplied projections.
For VERIFICATION call verify_recovery (incident) or verify_portfolio_allocation (portfolio),
then query fresh Grafana evidence. Never report observed verification if any evidence is missing.
For FOLLOW_UP and FORMAT_REPAIR use supplied facts and previous results without tool calls.
You have no mutation tools. Approval and execution are exclusively handled by the dashboard.
Use the requested response contract. JSON is internal transport; answer fields must be readable prose,
never JSON, XML, tool dumps, internal identifiers or recommendation_action markers.
The answer should explain what happened, what evidence supports it, why the plan helps, and the next step.
Keep ordinary answers around 80–140 words in two or three short paragraphs, or up to 300 when a detailed comparison is requested.
Lead with the production consequence and the decision. Use plain production language; detailed
query names, event names and trace identifiers belong in the expandable evidence panel.
An event trace proves that the event was recorded, not that recovery succeeded or all errors cleared.
Use only supplied calculator values for cost, duration, worker counts and risk. Do not invent numbers.
Do not claim the trailer is protected while its forecast remains late. Discuss technical evidence when asked.
""",
    tools=tools,
    before_model_callback=configure_thinking,
    output_schema=DirectorResponse,
    generate_content_config=types.GenerateContentConfig(max_output_tokens=5000),
)
app = App(root_agent=root_agent, name="production_director_agent")
