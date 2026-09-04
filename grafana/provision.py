import base64
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

GRAFANA_URL = os.getenv("GRAFANA_URL", "http://lgtm:3000")
token = base64.b64encode(b"admin:admin").decode()
headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def call(path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = Request(f"{GRAFANA_URL}{path}", data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}
    except HTTPError as error:
        if error.code == 404:
            return None
        raise RuntimeError(f"Grafana {method} {path} failed: {error.read().decode()}") from error


dashboard = json.loads(Path("/config/dashboard.json").read_text())
call("/api/dashboards/db", "POST", {"dashboard": dashboard, "folderUid": "", "overwrite": True})

folder_uid = "ai-production-alerts"
if call(f"/api/folders/{folder_uid}") is None:
    call("/api/folders", "POST", {"uid": folder_uid, "title": "AI Production Alerts"})

existing = {rule["title"]: rule for rule in call("/api/v1/provisioning/alert-rules")}
for definition in json.loads(Path("/config/rules.json").read_text()):
    rule = {
        "title": definition["title"], "ruleGroup": "Render Farm Incidents", "folderUID": folder_uid,
        "noDataState": "OK", "execErrState": "Error", "for": definition["for"], "condition": "C",
        "annotations": {"summary": definition["summary"], "description": definition["description"],
                        "dashboard_url": f"{GRAFANA_URL}/d/ai-production-director/ai-production-director"},
        "labels": {"severity": definition["severity"], "component": definition["component"],
                   "service": "render-farm-simulator"},
        "data": [
            {"refId": "A", "queryType": "", "relativeTimeRange": {"from": 300, "to": 0},
             "datasourceUid": "prometheus", "model": {"editorMode": "code", "expr": definition["expression"],
             "instant": True, "intervalMs": 1000, "maxDataPoints": 43200, "range": False, "refId": "A"}},
            {"refId": "B", "queryType": "", "relativeTimeRange": {"from": 0, "to": 0},
             "datasourceUid": "__expr__", "model": {"expression": "A", "reducer": "last",
             "settings": {"mode": "dropNN"}, "type": "reduce", "refId": "B"}},
            {"refId": "C", "queryType": "", "relativeTimeRange": {"from": 0, "to": 0},
             "datasourceUid": "__expr__", "model": {"expression": "B", "type": "threshold", "refId": "C",
             "conditions": [{"evaluator": {"params": [0], "type": "gt"}, "operator": {"type": "and"},
             "query": {"params": ["C"]}, "reducer": {"params": [], "type": "last"}, "type": "query"}]}}
        ],
    }
    current = existing.get(definition["title"])
    call(f"/api/v1/provisioning/alert-rules/{current['uid']}" if current else "/api/v1/provisioning/alert-rules",
         "PUT" if current else "POST", rule)

group_path = f"/api/v1/provisioning/folder/{folder_uid}/rule-groups/{quote('Render Farm Incidents')}"
group = call(group_path)
if group and group.get("interval") != 10:
    group["interval"] = 10
    call(group_path, "PUT", group)

print("Project Nova dashboard and alerts provisioned")
