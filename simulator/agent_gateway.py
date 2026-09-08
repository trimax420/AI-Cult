from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request


class AgentGateway:
    """Serialized access to production-scoped Google ADK sessions."""

    def __init__(self, base_url: str, connect_timeout: float = 8, response_timeout: float = 95) -> None:
        self.base_url = base_url.rstrip("/")
        self.connect_timeout = connect_timeout
        self.response_timeout = response_timeout
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    @staticmethod
    def session_id(production_id: str, incident_id: str) -> str:
        return f"{production_id}-{incident_id}"

    def _session_lock(self, session_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(session_id, threading.Lock())

    def send(self, production_id: str, incident_id: str, prompt: str) -> str | None:
        session_id = self.session_id(production_id, incident_id)
        with self._session_lock(session_id):
            session_url = (
                f"{self.base_url}/apps/production_director_agent/users/"
                f"{production_id}/sessions/{session_id}"
            )
            try:
                request = urllib.request.Request(
                    session_url,
                    data=b"{}",
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=self.connect_timeout):
                    pass
            except urllib.error.HTTPError as error:
                if error.code not in {409, 422}:
                    raise

            payload = json.dumps(
                {
                    "appName": "production_director_agent",
                    "userId": production_id,
                    "sessionId": session_id,
                    "newMessage": {"role": "user", "parts": [{"text": prompt}]},
                }
            ).encode()
            request = urllib.request.Request(
                f"{self.base_url}/run_sse",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            final_text = ""
            with urllib.request.urlopen(request, timeout=self.response_timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:])
                    for part in event.get("content", {}).get("parts", []):
                        if part.get("text"):
                            final_text = part["text"].strip()
            return final_text or None


_INTERNAL_LANGUAGE = re.compile(
    r"\b(grafana|mcp|prometheus|loki|tempo|telemetry|traces?(?:\s+id)?|logs?|metric query|"
    r"metrics?|confidence score|stack trace|exception|endpoint)\b",
    re.IGNORECASE,
)

_UNVERIFIED_FIGURE = re.compile(
    r"\$|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+(?:\.\d+)?)\s*"
    r"(?:minutes?|hours?|days?|percent|%)\b",
    re.IGNORECASE,
)

ALLOWED_ACTIONS = {
    "add-workers", "prioritize-scenes", "restart-workers", "reduce-preview-quality",
    "rebalance-queue", "release-storage", "reroute-transfers", "restore-asset",
}

BRIEFING_FIELDS = (
    "status_line", "condition", "impact", "recommendation_reason", "next_step",
    "conversation_message",
)


def recommendation_action(raw_reply: str | None) -> str | None:
    if not raw_reply:
        return None
    match = re.search(
        r'["\']?recommendation_action["\']?\s*(?:=|:)\s*["\']?([a-z-]+)',
        raw_reply,
        re.IGNORECASE,
    )
    action = match.group(1).lower() if match else None
    return action if action in ALLOWED_ACTIONS else None


def structured_briefing(raw_reply: str | None) -> dict | None:
    """Parse the agent-authored presentation fields from a bounded JSON envelope."""
    if not raw_reply:
        return None
    match = re.search(
        r"<production_briefing>\s*(\{[\s\S]*?\})\s*</production_briefing>",
        raw_reply,
        re.IGNORECASE,
    )
    payload = None
    if match:
        try:
            payload = json.loads(match.group(1))
        except (TypeError, ValueError):
            payload = None
    if payload is None:
        decoder = json.JSONDecoder()
        for candidate in re.finditer(r"\{", raw_reply):
            try:
                decoded, _ = decoder.raw_decode(raw_reply[candidate.start():])
            except ValueError:
                continue
            if isinstance(decoded, dict) and all(field in decoded for field in BRIEFING_FIELDS):
                payload = decoded
                break
    if not isinstance(payload, dict):
        return None
    action = str(payload.get("recommendation_action", "")).strip().lower()
    if action not in ALLOWED_ACTIONS:
        return None
    result = {"recommendation_action": action}
    for field in BRIEFING_FIELDS:
        value = re.sub(r"\s+", " ", str(payload.get(field, ""))).strip()
        if len(value) > 280 or _UNVERIFIED_FIGURE.search(value):
            return None
        safe_value = production_safe_reply(value, "")
        if len(safe_value) < 12:
            return None
        result[field] = safe_value
    return result


def production_safe_reply(raw_reply: str | None, fallback: str,
                          allowed_costs: set[float] | None = None) -> str:
    """Keep ADK reasoning live while enforcing production-facing presentation."""
    if not raw_reply:
        return fallback
    if re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", raw_reply):
        return fallback
    if re.search(r"\b(no immediate fix|pre-approved action|manually investigate|automated systems?|"
                 r"no (?:specific )?incident|no current delay|no delay to)\b",
                 raw_reply, re.IGNORECASE):
        return fallback
    if allowed_costs is not None:
        stated_costs = {
            float(value.replace(",", ""))
            for value in re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", raw_reply)
        }
        if any(all(abs(value - allowed) > .01 for allowed in allowed_costs) for value in stated_costs):
            return fallback
    cleaned = re.sub(r"<playbooks>[\s\S]*?</playbooks>", "", raw_reply, flags=re.IGNORECASE)
    cleaned = re.sub(r"<production_briefing>[\s\S]*?</production_briefing>", "", cleaned,
                     flags=re.IGNORECASE)
    cleaned = re.sub(r"recommendation_action\s*=.*$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r"\bCUDA\s+OOM\b", "render-capacity interruption", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bGPU memory(?: exhaustion| pressure| issue(?:s)?)?\b", "render capacity", cleaned,
                     flags=re.IGNORECASE)
    sentences = re.split(r"(?<=[.!?])\s+|\n+", cleaned)
    visible = " ".join(sentence.strip(" -*#\t") for sentence in sentences
                       if sentence.strip() and not _INTERNAL_LANGUAGE.search(sentence))
    visible = re.sub(r"\s+", " ", visible).strip()
    if len(visible) < 24:
        return fallback
    if len(visible) > 800:
        visible = visible[:800].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return visible
