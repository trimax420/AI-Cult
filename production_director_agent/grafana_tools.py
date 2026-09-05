"""Narrow Grafana MCP adapters for the Project Nova demo.

The agent sees three small, read-only tools instead of the complete Grafana MCP
catalog. Each adapter still performs a real MCP call and returns its query so the
UI can cite exactly where the evidence came from.
"""
import asyncio
import json
import os
import time
from urllib.request import urlopen
from datetime import datetime, timezone

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("GRAFANA_MCP_URL", "http://grafana-mcp:8000/mcp")
MCP_TOKEN = os.getenv("GRAFANA_MCP_AUTH_TOKEN", "")


def _incident_start() -> int:
    # Use only the time window from the simulator, never its incident diagnosis.
    try:
        with urlopen(f"{os.getenv('SIMULATOR_URL', 'http://render-simulator:8080')}/simulation/status", timeout=5) as response:
            timestamp = json.load(response).get("incident_started_at")
        return int(datetime.fromisoformat(timestamp).timestamp()) if timestamp else int(time.time()) - 300
    except (OSError, ValueError, TypeError):
        return int(time.time()) - 300


async def _call_mcp(tool_name: str, arguments: dict) -> dict:
    headers = {"Authorization": f"Bearer {MCP_TOKEN}"} if MCP_TOKEN else None
    async with streamablehttp_client(MCP_URL, headers=headers) as (reader, writer, *_):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
    if result.isError:
        message = " ".join(getattr(item, "text", "") for item in result.content)
        return {"ok": False, "error": message or f"{tool_name} failed"}
    text = next((getattr(item, "text", "") for item in result.content if getattr(item, "text", "")), "{}")
    try:
        return {"ok": True, "data": json.loads(text)}
    except json.JSONDecodeError:
        return {"ok": True, "data": text}


async def grafana_query_metrics() -> dict:
    """Query current Project Nova GPU memory, throughput, and critical queue metrics through Grafana MCP."""
    expression = ('{__name__=~"render_(gpu_memory_utilization_percent|current_throughput_per_hour|'
                  'required_throughput_per_hour|queue_critical_depth|asset_error_rate_percent)",production_id="project-nova"}')
    result = await _call_mcp("query_prometheus", {
        "datasourceUid": "prometheus", "expr": expression, "queryType": "instant", "endTime": "now"
    })
    rows = result.get("data", {}).get("data", []) if result.get("ok") else []
    if len(rows) < 5:
        result = {"ok": False, "error": "Required render metrics are missing from Prometheus"}
    return {"source": "Grafana MCP / Prometheus", "query": expression, **result}


async def grafana_query_logs() -> dict:
    """Find recent render errors through Grafana MCP and Loki; use the newest incident log."""
    query = '{service_name="render-farm-simulator"} |~ "CUDA out of memory|checksum mismatch"'
    result = await _call_mcp("query_loki_logs", {
        "datasourceUid": "loki", "logql": query, "limit": 10, "format": "compact",
        "startRfc3339": datetime.fromtimestamp(_incident_start(), timezone.utc).isoformat(), "endRfc3339": "now"
    })
    if result.get("ok") and not result.get("data", {}).get("streams") and not result.get("data", {}).get("data"):
        result = {"ok": False, "error": "No incident logs indexed in Loki yet"}
    return {"source": "Grafana MCP / Loki", "query": query, **result}


async def grafana_query_traces() -> dict:
    """Retrieve the current incident's exact trace through Grafana MCP and Tempo."""
    try:
        with urlopen(f"{os.getenv('SIMULATOR_URL', 'http://render-simulator:8080')}/simulation/status", timeout=5) as response:
            trace_id = json.load(response).get("incident_trace_id", "")
    except (OSError, ValueError):
        trace_id = ""
    if not trace_id or len(trace_id) != 32 or any(c not in "0123456789abcdef" for c in trace_id):
        return {"source": "Grafana MCP / Tempo", "ok": False, "error": "No current incident trace ID"}
    endpoint = f"/api/datasources/proxy/uid/tempo/api/traces/{trace_id}"
    result = {"ok": False, "error": "Current incident trace has not reached Tempo yet"}
    for attempt in range(10):
        candidate = await _call_mcp("grafana_api_request", {"method": "GET", "endpoint": endpoint})
        if candidate.get("ok") and candidate.get("data", {}).get("status") == 200:
            result = candidate
            break
        if attempt < 9:
            await asyncio.sleep(2)
    return {"source": "Grafana MCP / Tempo", "query": f"Tempo trace {trace_id}", "trace_id": trace_id, **result}
