"""Narrow Grafana MCP adapters for the Project Nova demo.

The agent sees three small, read-only tools instead of the complete Grafana MCP
catalog. Each adapter still performs a real MCP call and returns its query so the
UI can cite exactly where the evidence came from.
"""
import json
import os
from urllib.parse import quote

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("GRAFANA_MCP_URL", "http://grafana-mcp:8000/mcp")
MCP_TOKEN = os.getenv("GRAFANA_MCP_AUTH_TOKEN", "")


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
    expression = ('{__name__=~"render_(gpu_memory_utilization_percent|current_throughput_frames_per_hour|'
                  'required_throughput_frames_per_hour|queue_critical_depth_frames)",production_id="project-nova"}')
    result = await _call_mcp("query_prometheus", {
        "datasourceUid": "prometheus", "expr": expression, "queryType": "instant", "endTime": "now"
    })
    return {"source": "Grafana MCP / Prometheus", "query": expression, **result}


async def grafana_query_logs() -> dict:
    """Find the newest Scene 87 CUDA out-of-memory log through Grafana MCP and Loki."""
    query = '{service_name="render-farm-simulator"} |= "CUDA out of memory"'
    result = await _call_mcp("query_loki_logs", {
        "datasourceUid": "loki", "logql": query, "limit": 1, "format": "compact",
        "startRfc3339": "now-30m", "endRfc3339": "now"
    })
    return {"source": "Grafana MCP / Loki", "query": query, **result}


async def grafana_query_traces() -> dict:
    """Find the Scene 87 GPU OOM incident span through Grafana MCP and Tempo."""
    traceql = '{ name = "incident.gpu_oom" }'
    endpoint = f"/api/datasources/proxy/uid/tempo/api/search?q={quote(traceql)}&limit=1"
    result = await _call_mcp("grafana_api_request", {"method": "GET", "endpoint": endpoint})
    return {"source": "Grafana MCP / Tempo", "query": traceql, **result}
