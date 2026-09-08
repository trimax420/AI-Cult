from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class IncidentMemory:
    """Small durable ledger for production incidents and conversations."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or os.getenv(
            "INCIDENT_DB_PATH", os.path.join(os.path.dirname(__file__), "production-director.db")
        )
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.RLock()
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialise(self) -> None:
        with self._connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS productions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    production_id TEXT NOT NULL,
                    incident_type TEXT NOT NULL,
                    scene_id TEXT,
                    condition_summary TEXT NOT NULL,
                    status TEXT NOT NULL,
                    raised_at TEXT NOT NULL,
                    resolved_at TEXT,
                    recovery_action TEXT,
                    outcome_summary TEXT,
                    FOREIGN KEY(production_id) REFERENCES productions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_incidents_production ON incidents(production_id, raised_at DESC);
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL UNIQUE,
                    production_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    briefing_json TEXT NOT NULL,
                    recommended_action TEXT,
                    error_code TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(incident_id) REFERENCES incidents(id)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    production_id TEXT NOT NULL,
                    incident_id TEXT,
                    role TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(production_id) REFERENCES productions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_production ON messages(production_id, created_at);
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY,
                    production_id TEXT NOT NULL,
                    production_title TEXT NOT NULL,
                    deliverable_title TEXT NOT NULL,
                    incident_type TEXT NOT NULL,
                    affected_area TEXT NOT NULL,
                    condition_summary TEXT NOT NULL,
                    recovery_action TEXT NOT NULL,
                    outcome_summary TEXT NOT NULL,
                    verified INTEGER NOT NULL,
                    resolved_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY,
                    production_id TEXT NOT NULL,
                    incident_id TEXT,
                    approval_id TEXT,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    approved_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            run_columns = {row[1] for row in db.execute("PRAGMA table_info(agent_runs)")}
            if "recommended_action" not in run_columns:
                db.execute("ALTER TABLE agent_runs ADD COLUMN recommended_action TEXT")
            db.execute(
                "INSERT OR IGNORE INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "case-silverline-render-capacity",
                    "silverline",
                    "Silverline",
                    "Silverline Trailer",
                    "gpu_oom",
                    "render capacity",
                    "A group of render workers stopped during the final trailer pass.",
                    "prioritize-scenes",
                    "Trailer scenes were prioritised and the delivery remained on time.",
                    1,
                    "2026-06-18T18:25:00+00:00",
                ),
            )

    def upsert_production(self, production_id: str, title: str) -> None:
        with self._connection() as db:
            db.execute(
                "INSERT INTO productions VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at",
                (production_id, title, utcnow()),
            )

    def active_incident(self, production_id: str) -> dict | None:
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM incidents WHERE production_id=? AND status='active' ORDER BY raised_at DESC LIMIT 1",
                (production_id,),
            ).fetchone()
        return dict(row) if row else None

    def raise_incident(self, production_id: str, production_title: str, incident_type: str,
                       scene_id: str, condition_summary: str, briefing: dict) -> dict:
        self.upsert_production(production_id, production_title)
        with self._lock, self._connection() as db:
            existing = db.execute(
                "SELECT * FROM incidents WHERE production_id=? AND status='active' ORDER BY raised_at DESC LIMIT 1",
                (production_id,),
            ).fetchone()
            if existing:
                return dict(existing)
            incident_id = str(uuid.uuid4())
            run_id = str(uuid.uuid4())
            now = utcnow()
            db.execute(
                "INSERT INTO incidents VALUES (?, ?, ?, ?, ?, 'active', ?, NULL, NULL, NULL)",
                (incident_id, production_id, incident_type, scene_id, condition_summary, now),
            )
            db.execute(
                """INSERT INTO agent_runs
                   (id, incident_id, production_id, status, source, briefing_json, recommended_action,
                    error_code, started_at, completed_at)
                   VALUES (?, ?, ?, 'queued', 'pending', ?, NULL, NULL, ?, NULL)""",
                (run_id, incident_id, production_id, json.dumps(briefing), now),
            )
            db.execute(
                "INSERT INTO messages VALUES (?, ?, ?, 'assistant', ?, ?)",
                (str(uuid.uuid4()), production_id, incident_id, briefing["assistant_message"], now),
            )
        return self.incident(incident_id) or {}

    def start_run(self, incident_id: str, runner: Callable[[], str | dict | None]) -> bool:
        with self._lock, self._connection() as db:
            run = db.execute("SELECT status FROM agent_runs WHERE incident_id=?", (incident_id,)).fetchone()
            if not run or run["status"] != "queued":
                return False
            db.execute("UPDATE agent_runs SET status='investigating' WHERE incident_id=?", (incident_id,))

        def work() -> None:
            source = "deterministic-fallback"
            error_code = None
            recommended_action = None
            agent_fields = None
            try:
                result = runner()
                if isinstance(result, dict):
                    live_answer = result.get("answer")
                    recommended_action = result.get("recommended_action")
                    agent_fields = result.get("briefing_fields")
                else:
                    live_answer = result
                    agent_fields = None
                if live_answer:
                    source = "live-agent"
                    self.add_message(self.incident(incident_id)["production_id"], incident_id, "assistant", live_answer)
            except Exception as error:  # The stored code is diagnostic only and is never rendered.
                error_code = type(error).__name__
            with self._connection() as db:
                if agent_fields:
                    row = db.execute(
                        "SELECT briefing_json FROM agent_runs WHERE incident_id=?", (incident_id,)
                    ).fetchone()
                    briefing = json.loads(row["briefing_json"]) if row else {}
                    briefing["agent_fields"] = agent_fields
                    db.execute(
                        "UPDATE agent_runs SET briefing_json=? WHERE incident_id=?",
                        (json.dumps(briefing), incident_id),
                    )
                db.execute(
                    """UPDATE agent_runs SET status='ready', source=?, recommended_action=?, error_code=?,
                       completed_at=? WHERE incident_id=?""",
                    (source, recommended_action, error_code, utcnow(), incident_id),
                )

        threading.Thread(target=work, daemon=True, name=f"incident-agent-{incident_id[:8]}").start()
        return True

    def incident(self, incident_id: str) -> dict | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        return dict(row) if row else None

    def run_for_incident(self, incident_id: str) -> dict | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM agent_runs WHERE incident_id=?", (incident_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["briefing"] = json.loads(result.pop("briefing_json"))
        result.pop("error_code", None)
        return result

    def similar_case(self, incident_type: str, affected_area: str | None = None,
                     symptoms: str | None = None) -> dict | None:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM cases WHERE verified=1 AND incident_type=? ORDER BY resolved_at DESC",
                (incident_type,),
            ).fetchall()
        if not rows:
            return None
        if not affected_area and not symptoms:
            return dict(rows[0])

        def words(value: str | None) -> set[str]:
            ignored = {"the", "and", "for", "that", "with", "from", "part", "because", "during"}
            return {word for word in re.findall(r"[a-z0-9]+", (value or "").lower())
                    if len(word) > 2 and word not in ignored}

        area_words = words(affected_area)
        symptom_words = words(symptoms)

        def score(row: sqlite3.Row) -> tuple[int, int, str]:
            case_area = words(row["affected_area"])
            case_symptoms = words(row["condition_summary"])
            area_match = len(area_words & case_area)
            symptom_match = len(symptom_words & (case_area | case_symptoms))
            return area_match, symptom_match, row["resolved_at"]

        best = max(rows, key=score)
        area_match, symptom_match, _ = score(best)
        return dict(best) if area_match > 0 or symptom_match > 0 else None

    def messages(self, production_id: str, incident_id: str | None = None, limit: int = 80) -> list[dict]:
        with self._connection() as db:
            if incident_id:
                rows = db.execute(
                    """SELECT id, production_id, incident_id, role, body, created_at FROM messages
                       WHERE production_id=? AND incident_id=? ORDER BY created_at DESC LIMIT ?""",
                    (production_id, incident_id, max(1, min(limit, 200))),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT id, production_id, incident_id, role, body, created_at FROM messages
                       WHERE production_id=? AND incident_id IS NULL ORDER BY created_at DESC LIMIT ?""",
                    (production_id, max(1, min(limit, 200))),
                ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_message(self, production_id: str, incident_id: str | None, role: str, body: str) -> dict:
        message = {"id": str(uuid.uuid4()), "production_id": production_id, "incident_id": incident_id,
                   "role": role, "body": body, "created_at": utcnow()}
        with self._connection() as db:
            db.execute(
                "INSERT INTO messages VALUES (:id, :production_id, :incident_id, :role, :body, :created_at)",
                message,
            )
        return message

    def record_decision(self, production_id: str, incident_id: str | None, action: str, status: str,
                        approval_id: str | None = None, approved_by: str | None = None) -> None:
        now = utcnow()
        with self._connection() as db:
            db.execute(
                "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), production_id, incident_id, approval_id, action, status, approved_by, now, now),
            )

    def update_run_recommendation(self, incident_id: str, action: str, source: str = "live-agent") -> None:
        with self._connection() as db:
            db.execute(
                "UPDATE agent_runs SET recommended_action=?, source=?, completed_at=? WHERE incident_id=?",
                (action, source, utcnow(), incident_id),
            )

    def resolve_active(self, production_id: str, recovery_action: str | None, outcome: str) -> None:
        with self._lock, self._connection() as db:
            row = db.execute(
                "SELECT * FROM incidents WHERE production_id=? AND status='active' ORDER BY raised_at DESC LIMIT 1",
                (production_id,),
            ).fetchone()
            if not row:
                return
            db.execute(
                "UPDATE incidents SET status='resolved', resolved_at=?, recovery_action=?, outcome_summary=? WHERE id=?",
                (utcnow(), recovery_action, outcome, row["id"]),
            )
            if recovery_action:
                db.execute(
                    "INSERT OR REPLACE INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                    (
                        row["id"], production_id, "Project Nova", "Project Nova Trailer",
                        row["incident_type"], "render production", row["condition_summary"],
                        recovery_action, outcome, utcnow(),
                    ),
                )
