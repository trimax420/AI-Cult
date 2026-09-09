"""Read-only, incident-correlated Grafana MCP evidence with bounded ingestion retries."""
import asyncio
import json
import os
import time
from functools import wraps
from datetime import datetime, timezone
from urllib.request import urlopen

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("GRAFANA_MCP_URL", "http://grafana-mcp:8000/mcp")
MCP_TOKEN = os.getenv("GRAFANA_MCP_AUTH_TOKEN", "")
PROMETHEUS_DATASOURCE_UID = os.getenv("GRAFANA_PROMETHEUS_DATASOURCE_UID", "prometheus")
LOKI_DATASOURCE_UID = os.getenv("GRAFANA_LOKI_DATASOURCE_UID", "loki")
TEMPO_DATASOURCE_UID = os.getenv("GRAFANA_TEMPO_DATASOURCE_UID", "tempo")
METRICS = ["gpu_memory_utilization_percent", "current_throughput_per_hour", "required_throughput_per_hour",
           "queue_critical_depth", "asset_error_rate_percent", "storage_utilization_percent",
           "network_latency_milliseconds", "gpu_workers_active", "portfolio_workers_allocated",
           "portfolio_throughput_per_hour", "portfolio_required_throughput_per_hour", "portfolio_predicted_delay_minutes"]

_EVIDENCE_CACHE = {}


def reuse_successful_evidence(function):
    """Retain successful reads for an unchanged event; retries only fetch failures."""
    @wraps(function)
    async def read():
        context = _context()
        key = (function.__name__, context['scope_id'], context.get('trace_id'), context['since'])
        if key in _EVIDENCE_CACHE:
            return _EVIDENCE_CACHE[key]
        result = await function()
        if result.get('ok') and _context() == context:
            if len(_EVIDENCE_CACHE) >= 64:
                _EVIDENCE_CACHE.pop(next(iter(_EVIDENCE_CACHE)))
            _EVIDENCE_CACHE[key] = result
        return result
    return read


def _context() -> dict:
    with urlopen(f"{os.getenv('SIMULATOR_URL', 'http://render-simulator:8080')}/evidence-context", timeout=5) as response:
        return json.load(response)


async def _call_mcp(tool_name: str, arguments: dict) -> dict:
    headers = {"Authorization": f"Bearer {MCP_TOKEN}"} if MCP_TOKEN else None
    try:
        async with asyncio.timeout(12):
            async with streamablehttp_client(MCP_URL, headers=headers) as (reader, writer, *_):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
        text = next((getattr(item, "text", "") for item in result.content if getattr(item, "text", "")), "{}")
        if result.isError:
            return {"ok": False, "error": text[:300]}
        return {"ok": True, "data": json.loads(text)}
    except Exception as error:
        return {"ok": False, "error": f"MCP request failed ({type(error).__name__})"}


async def _retry(operation):
    deadline = time.monotonic() + 30
    result = {"ok": False, "error": "No evidence returned"}
    while time.monotonic() < deadline:
        try:
            result = await asyncio.wait_for(operation(), timeout=max(.1, deadline-time.monotonic()))
        except (TimeoutError, asyncio.TimeoutError):
            break
        if result.get("ok"):
            return {**result, "observed_at": datetime.now(timezone.utc).isoformat()}
        await asyncio.sleep(min(2, max(0, deadline-time.monotonic())))
    return result


@reuse_successful_evidence
async def grafana_query_metrics() -> dict:
    """Observe both productions' capacity and Nova health; wait for fresh, complete samples."""
    context = _context()
    expression = '{__name__=~"render_(' + '|'.join(METRICS) + ')",production_id=~"project-nova|silverline"}'
    expected = {(f"render_{name}", "project-nova") for name in METRICS}
    expected.update((f"render_{name}", "silverline") for name in METRICS if name.startswith("portfolio_"))
    async def query():
        result = await _call_mcp("query_prometheus", {"datasourceUid": PROMETHEUS_DATASOURCE_UID,
                                                    "expr": expression, "queryType": "instant", "endTime": "now"})
        rows = result.get("data", {}).get("data", []) if result.get("ok") else []
        present = {(r["metric"].get("__name__"), r["metric"].get("production_id")) for r in rows}
        missing = sorted(expected-present)
        if missing:
            return {"ok": False, "error": "Required metrics are missing", "missing": missing}
        freshness = await _call_mcp("query_prometheus", {"datasourceUid": PROMETHEUS_DATASOURCE_UID,
            "expr": f'min(timestamp(label_replace({expression}, "metric_name", "$1", "__name__", "(.*)")))', "queryType": "instant", "endTime": "now"})
        samples = freshness.get("data", {}).get("data", []) if freshness.get("ok") else []
        since = datetime.fromisoformat(context["since"]).timestamp()
        if not samples or any(float(row["value"][1]) < since for row in samples):
            return {"ok": False, "error": "Waiting for metrics sampled after the current event"}
        return {**result, "sampled_after": context["since"]}
    return {"source": "Grafana MCP / Prometheus", "query": expression, "scope_id": context["scope_id"], **await _retry(query)}


@reuse_successful_evidence
async def grafana_query_logs() -> dict:
    """Read the exact structured incident or allocation event from Loki."""
    context = _context()
    trace_id = context.get("trace_id")
    if not trace_id:
        return {"source": "Grafana MCP / Loki", "ok": False, "error": "No event to correlate"}
    query = '{service_name="render-farm-simulator"} |= ' + json.dumps(trace_id)
    async def read():
        result = await _call_mcp("query_loki_logs", {"datasourceUid": LOKI_DATASOURCE_UID,
            "logql": query, "limit": 10, "format": "compact", "startRfc3339": datetime.fromisoformat(context["event_started_at"]).isoformat(timespec="seconds"), "endRfc3339": "now"})
        data = result.get("data", {})
        if not result.get("ok") or not (data.get("streams") or data.get("data")):
            return {"ok": False, "error": "Waiting for the correlated event in Loki"}
        return result
    return {"source": "Grafana MCP / Loki", "query": query, "scope_id": context["scope_id"], "trace_id": trace_id, **await _retry(read)}


@reuse_successful_evidence
async def grafana_query_traces() -> dict:
    """Retrieve this event's exact Tempo trace."""
    context = _context()
    trace_id = context.get("trace_id", "")
    if not trace_id or len(trace_id) != 32 or any(c not in "0123456789abcdef" for c in trace_id):
        return {"source": "Grafana MCP / Tempo", "ok": False, "error": "No current event trace ID"}
    async def read():
        result = await _call_mcp("grafana_api_request", {"method": "GET", "endpoint": f"/api/datasources/proxy/uid/{TEMPO_DATASOURCE_UID}/api/traces/{trace_id}"})
        if not result.get("ok") or result.get("data", {}).get("status") != 200:
            return {"ok": False, "error": "Waiting for the correlated event in Tempo"}
        return result
    return {"source": "Grafana MCP / Tempo", "query": f"Tempo trace {trace_id}", "scope_id": context["scope_id"], "trace_id": trace_id, **await _retry(read)}
