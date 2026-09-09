from __future__ import annotations

import math
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Deliverable:
    id: str
    title: str
    deadline: datetime
    scene_ids: list[str]


@dataclass
class Scene:
    id: str
    title: str
    total_frames: int
    completed_frames: int
    trailer_critical: bool
    priority: int
    retries: int = 0
    failed_frames: int = 0

    @property
    def remaining_frames(self) -> int:
        return max(0, self.total_frames - self.completed_frames)


@dataclass
class Worker:
    id: str
    healthy: bool = True
    gpu_utilization: float = 72.0
    gpu_memory_utilization: float = 68.0
    frames_per_hour: float = 42.0
    hourly_rate_usd: float = 3.5
    current_scene_id: str | None = None
    retries: int = 0


@dataclass
class Approval:
    id: str
    action: str
    created_at: datetime
    expires_at: datetime
    used: bool = False
    approved_by: str | None = None
    incident_started_at: datetime | None = None


@dataclass
class Production:
    id: str
    title: str
    workflow_state: str
    running: bool
    incident_active: bool
    incident_started_at: datetime | None
    recovery_action: str | None
    recovery_progress: float
    verification_complete: bool
    incident_type: str | None
    recovery_failed: bool
    fail_next_recovery: bool
    trailer: Deliverable
    full_film: Deliverable
    scenes: dict[str, Scene]
    workers: dict[str, Worker]
    storage_utilization: float = 61.0
    network_latency_ms: float = 12.0
    asset_error_rate: float = 0.0
    last_failed_action: str | None = None
    approvals: dict[str, Approval] = field(default_factory=dict)
    added_cost_usd: float = 0.0
    tick_count: int = 0
    recovery_baseline: dict | None = None
    verification_snapshot: dict | None = None
    incident_trace_id: str | None = None


RECOVERY_SPECS = {
    "add-workers": {"title": "Add two GPU workers", "cost": 84.0, "risk": "low",
                    "incident_types": {"gpu_oom", "worker_loss", "queue_surge"}},
    "prioritize-scenes": {"title": "Prioritize trailer scenes", "cost": 17.0, "risk": "medium",
                          "incident_types": {"gpu_oom", "worker_loss", "queue_surge", "storage_pressure", "network_latency"}},
    "restart-workers": {"title": "Restart affected workers", "cost": 12.0, "risk": "low",
                        "incident_types": {"gpu_oom", "worker_loss"}},
    "reduce-preview-quality": {"title": "Reduce preview quality", "cost": 4.0, "risk": "medium",
                               "incident_types": {"gpu_oom", "queue_surge"}},
    "rebalance-queue": {"title": "Rebalance the trailer render queue", "cost": 10.0, "risk": "low",
                        "incident_types": {"queue_surge"}},
    "release-storage": {"title": "Release temporary render storage", "cost": 9.0, "risk": "low",
                        "incident_types": {"storage_pressure"}},
    "reroute-transfers": {"title": "Reroute scene transfers", "cost": 18.0, "risk": "low",
                          "incident_types": {"network_latency"}},
    "restore-asset": {"title": "Restore the verified artwork", "cost": 6.0, "risk": "low",
                      "incident_types": {"corrupted_asset"}},
}

INCIDENT_SCENARIOS = {
    "gpu-oom": {"issue_type": "gpu_oom", "label": "Render memory pressure", "scene_id": "SC-87",
                "affected_area": "render capacity", "threshold": "Render memory above 95%",
                "condition": "Scene 87 has stalled because part of the render capacity is unavailable.",
                "impact": "The trailer will miss its delivery window unless capacity is restored or trailer work is prioritised."},
    "worker-loss": {"issue_type": "worker_loss", "label": "Render worker loss", "scene_id": "SC-91",
                    "affected_area": "render capacity", "threshold": "Healthy workers below 75%",
                    "condition": "Scene 91 has slowed because six render workers stopped responding.",
                    "impact": "The reduced capacity puts the remaining trailer scenes behind schedule."},
    "queue-surge": {"issue_type": "queue_surge", "label": "Trailer queue surge", "scene_id": "SC-82",
                   "affected_area": "render queue", "threshold": "Required pace exceeds available throughput",
                   "condition": "A late group of trailer frames has pushed the critical queue beyond the available pace.",
                   "impact": "The trailer delivery is at risk unless critical scenes move ahead of full-film work."},
    "storage-pressure": {"issue_type": "storage_pressure", "label": "Production storage pressure", "scene_id": "SC-97",
                        "affected_area": "production storage", "threshold": "Storage use above 90%",
                        "condition": "Scene 97 is waiting because production storage has reached its safe working limit.",
                        "impact": "New trailer frames cannot move through the pipeline at the required pace."},
    "network-latency": {"issue_type": "network_latency", "label": "Render transfer slowdown", "scene_id": "SC-84",
                       "affected_area": "media transfer", "threshold": "Transfer latency above 150 ms",
                       "condition": "Scene 84 transfers are taking too long to reach the render workers.",
                       "impact": "Trailer frames are arriving late to the queue and could delay final delivery."},
    "corrupted-asset": {"issue_type": "corrupted_asset", "label": "Source artwork failure", "scene_id": "SC-94",
                        "affected_area": "source artwork", "threshold": "Asset error rate above 10%",
                        "condition": "Scene 94 is paused because its city backdrop file needs to be replaced.",
                        "impact": "Other scenes can continue, but this trailer scene cannot finish until the artwork is replaced."},
}

INCIDENT_EFFICIENCY = {
    "gpu_oom": .265, "worker_loss": .33, "queue_surge": .42,
    "storage_pressure": .31, "network_latency": .45, "corrupted_asset": .38,
}


def create_project_nova(now: datetime | None = None) -> Production:
    now = now or utcnow()
    scenes: dict[str, Scene] = {}
    for number in range(81, 101):
        scene_id = f"SC-{number}"
        critical = number in {82, 84, 87, 91, 94, 97}
        total = 720 if critical else 960
        scenes[scene_id] = Scene(scene_id, f"Scene {number}", total, 540 if critical else 610, critical,
                                 100 if critical else 20)
    workers = {f"GPU-{n:02d}": Worker(f"GPU-{n:02d}", hourly_rate_usd=3.5 + (n % 3) * .25)
               for n in range(1, 21)}
    trailer_ids = [scene.id for scene in scenes.values() if scene.trailer_critical]
    return Production("project-nova", "Project Nova", "ON_TRACK", True, False, None, None, 0, False,
                      None, False, False,
                      Deliverable("nova-trailer", "Project Nova Trailer", now + timedelta(minutes=90), trailer_ids),
                      Deliverable("nova-film", "Project Nova Full Film", now + timedelta(days=5), list(scenes)),
                      scenes, workers)


def calculate_delivery_impact(production: Production) -> dict:
    remaining = sum(production.scenes[s].remaining_frames for s in production.trailer.scene_ids)
    healthy = [worker for worker in production.workers.values() if worker.healthy]
    throughput = sum(worker.frames_per_hour for worker in healthy)
    if production.incident_active and not production.recovery_action:
        throughput *= INCIDENT_EFFICIENCY.get(production.incident_type or "", .38)
    elif production.recovery_action in {"prioritize-scenes", "add-workers"}:
        throughput *= .92
    elif production.recovery_action == "restart-workers":
        throughput *= .86
    elif production.recovery_action == "reduce-preview-quality":
        throughput *= .82
    hours_left = max((production.trailer.deadline - utcnow()).total_seconds() / 3600, 1 / 60)
    required = remaining / hours_left
    completion_hours = remaining / max(throughput, .01)
    delay_minutes = max(0.0, (completion_hours - hours_left) * 60)
    hourly_cost = sum(worker.hourly_rate_usd for worker in healthy)
    baseline_cost = completion_hours * hourly_cost
    no_action_cost = remaining / max(sum(w.frames_per_hour for w in healthy) * .265, .01) * hourly_cost
    return {
        "remaining_critical_frames": remaining,
        "required_throughput_fph": round(required, 1),
        "current_throughput_fph": round(throughput, 1),
        "estimated_completion_at": (utcnow() + timedelta(hours=completion_hours)).isoformat(),
        "projected_delay_minutes": round(delay_minutes, 1),
        "baseline_cost_usd": round(baseline_cost, 2),
        "recovery_cost_usd": round(production.added_cost_usd, 2),
        "estimated_cost_avoided_usd": round(max(0, no_action_cost - baseline_cost - production.added_cost_usd), 2),
        "deadline_at_risk": delay_minutes > 0,
    }


def calculate_what_if(production: Production, workers_added: int = 0, deadline_minutes: int | None = None,
                      quality_percent: int = 100, prioritize_critical: bool = False) -> dict:
    remaining = sum(production.scenes[s].remaining_frames for s in production.trailer.scene_ids)
    remaining *= max(50, min(100, quality_percent)) / 100
    healthy_throughput = sum(w.frames_per_hour for w in production.workers.values() if w.healthy)
    throughput = healthy_throughput + max(0, min(10, workers_added)) * 46
    if production.incident_active:
        throughput *= .92 if prioritize_critical else INCIDENT_EFFICIENCY.get(production.incident_type or "", .38)
    minutes_left = deadline_minutes if deadline_minutes is not None else max(
        1, int((production.trailer.deadline - utcnow()).total_seconds() / 60))
    completion_minutes = remaining / max(throughput, .01) * 60
    delay = max(0, completion_minutes - minutes_left)
    added_cost = workers_added * 3.75 * completion_minutes / 60
    if quality_percent < 100:
        added_cost += 4
    if prioritize_critical:
        added_cost += 17
    return {"workers_added": workers_added, "deadline_minutes": minutes_left, "quality_percent": quality_percent,
            "prioritize_critical": prioritize_critical, "projected_throughput_fph": round(throughput, 1),
            "projected_completion_minutes": round(completion_minutes, 1), "projected_delay_minutes": round(delay, 1),
            "added_cost_usd": round(added_cost, 2), "deadline_result": "On time" if delay == 0 else f"{delay / 60:.1f}h late"}


def calculate_recovery_option(production: Production, action: str) -> dict:
    """Calculate an allowlisted action from the current schedule without mutating it."""
    if action not in RECOVERY_SPECS:
        raise ValueError("unsupported recovery action")
    remaining = sum(production.scenes[s].remaining_frames for s in production.trailer.scene_ids)
    raw_capacity = sum(worker.frames_per_hour for worker in production.workers.values() if worker.healthy)
    if action == "add-workers":
        raw_capacity += 220
        efficiency = .92
    elif action == "prioritize-scenes":
        raw_capacity = len(production.workers) * 46
        efficiency = .92
    elif action == "restart-workers":
        raw_capacity = sum(worker.frames_per_hour for worker in production.workers.values())
        efficiency = .86
    elif action == "reduce-preview-quality":
        remaining = sum(max(0, math.ceil(production.scenes[s].total_frames * .82) - production.scenes[s].completed_frames)
                        for s in production.trailer.scene_ids)
        efficiency = .82
    else:
        efficiency = 1.0
    throughput = max(.01, raw_capacity * efficiency)
    hours_left = max((production.trailer.deadline - utcnow()).total_seconds() / 3600, 1 / 60)
    completion_hours = remaining / throughput
    delay_minutes = max(0.0, (completion_hours - hours_left) * 60)
    spec = RECOVERY_SPECS[action]
    if delay_minutes == 0:
        deadline_result = "On time"
    elif delay_minutes < 1:
        deadline_result = "Less than 1 minute late"
    else:
        deadline_result = f"{int(delay_minutes // 60)}h {int(delay_minutes % 60)}m late"
    return {"projected_throughput_fph": round(throughput, 1),
            "projected_delay_minutes": round(delay_minutes, 1),
            "deadline_result": deadline_result,
            "estimated_added_cost_usd": spec["cost"]}


class ProductionEngine:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.production = create_project_nova()
        self.audit: list[dict] = []
        self.history: list[dict] = []
        self._seed_history()

    def _append_history(self) -> None:
        p = self.production
        impact = calculate_delivery_impact(p)
        self.history.append({"timestamp": utcnow().isoformat(),
                             "gpu_memory_utilization": round(max(w.gpu_memory_utilization for w in p.workers.values()), 1),
                             "queue_depth": sum(s.remaining_frames for s in p.scenes.values()),
                             "critical_queue_depth": impact["remaining_critical_frames"],
                             "throughput_fph": impact["current_throughput_fph"],
                             "storage_utilization": p.storage_utilization,
                             "network_latency_ms": p.network_latency_ms,
                             "asset_error_rate": p.asset_error_rate})
        self.history[:] = self.history[-360:]

    def _seed_history(self) -> None:
        """Provide a believable local telemetry window before the first live tick."""
        p = self.production
        queue_now = sum(scene.remaining_frames for scene in p.scenes.values())
        now = utcnow()
        for index in range(72):
            phase = index / 5
            # Older points have a slightly deeper queue; every value is deterministic.
            self.history.append({"timestamp": (now - timedelta(seconds=(71 - index) * 2)).isoformat(),
                                 "gpu_memory_utilization": round(68 + math.sin(phase) * 5.8 + math.cos(phase / 2) * 1.7, 1),
                                 "queue_depth": queue_now + (71 - index) * 11 + int(math.sin(phase) * 9),
                                 "critical_queue_depth": max(0, sum(p.scenes[s].remaining_frames for s in p.trailer.scene_ids) + (71 - index) * 2),
                                 "throughput_fph": round(840 + math.sin(phase) * 38, 1)})

    def record(self, event_type: str, **details) -> dict:
        event = {"id": str(uuid.uuid4()), "timestamp": utcnow().isoformat(), "event_type": event_type,
                 "production_id": self.production.id, **details}
        self.audit.append(event)
        self.audit[:] = self.audit[-300:]
        return event

    def reset(self) -> None:
        with self.lock:
            self.production = create_project_nova()
            self.history.clear()
            self._seed_history()
            self.record("simulation_reset", workflow_state="ON_TRACK")

    def inject_gpu_oom(self) -> None:
        self.inject_incident("gpu-oom")

    def inject_corrupted_asset(self) -> None:
        self.inject_incident("corrupted-asset")

    def inject_incident(self, scenario_id: str) -> None:
        if scenario_id not in INCIDENT_SCENARIOS:
            raise ValueError("unsupported incident scenario")
        with self.lock:
            scenario = INCIDENT_SCENARIOS[scenario_id]
            scene = self.production.scenes[scenario["scene_id"]]
            scene.retries += 1
            scene.failed_frames += 36 if scenario_id == "corrupted-asset" else 24
            if scenario_id == "gpu-oom":
                for worker in list(self.production.workers.values())[:8]:
                    worker.healthy = False
                    worker.gpu_memory_utilization = 99.2
                    worker.gpu_utilization = 8
                    worker.current_scene_id = scenario["scene_id"]
                    worker.retries += 1
            elif scenario_id == "worker-loss":
                for worker in list(self.production.workers.values())[:6]:
                    worker.healthy = False
                    worker.gpu_utilization = 0
                    worker.current_scene_id = scenario["scene_id"]
            elif scenario_id == "queue-surge":
                for scene_id in self.production.trailer.scene_ids:
                    self.production.scenes[scene_id].total_frames += 180
            elif scenario_id == "storage-pressure":
                self.production.storage_utilization = 96.0
            elif scenario_id == "network-latency":
                self.production.network_latency_ms = 240.0
            elif scenario_id == "corrupted-asset":
                scene.retries += 2
                self.production.asset_error_rate = 18.0
            self.production.approvals.clear()
            self.production.incident_active = True
            self.production.incident_type = scenario["issue_type"]
            self.production.incident_started_at = utcnow()
            self.production.workflow_state = "INVESTIGATING"
            self.production.verification_complete = False
            self.production.recovery_failed = False
            self.production.recovery_progress = 0
            self.production.recovery_baseline = None
            self.production.verification_snapshot = None
            evidence = {"asset": "nova_city.exr"} if scenario_id == "corrupted-asset" else {}
            if scenario_id in {"gpu-oom", "worker-loss"}:
                evidence["failed_workers"] = 8 if scenario_id == "gpu-oom" else 6
            self.record(f"{scenario['issue_type']}_injected", scene_id=scenario["scene_id"],
                        threshold=scenario["threshold"], workflow_state="INVESTIGATING", **evidence)

    def request_approval(self, action: str) -> Approval:
        if action not in RECOVERY_SPECS:
            raise ValueError("unsupported recovery action")
        if action == self.production.last_failed_action:
            raise ValueError("the previous recovery did not verify; choose a revised action")
        with self.lock:
            if not self.production.incident_active or self.production.incident_type not in RECOVERY_SPECS[action]["incident_types"]:
                raise ValueError("action does not apply to the active incident")
            approval = Approval(str(uuid.uuid4()), action, utcnow(), utcnow() + timedelta(minutes=10), incident_started_at=self.production.incident_started_at)
            self.production.approvals[approval.id] = approval
            self.record("approval_requested", approval_id=approval.id, action=action)
            return approval

    def execute(self, action: str, approval_id: str, approved_by: str) -> dict:
        with self.lock:
            approval = self.production.approvals.get(approval_id)
            if not approval or approval.action != action:
                raise ValueError("approval ID is invalid for this action")
            if approval.used:
                raise ValueError("approval ID has already been used")
            if utcnow() >= approval.expires_at:
                raise ValueError("approval ID has expired")
            if self.production.recovery_action:
                raise ValueError("a recovery is already executing")
            if not self.production.incident_active:
                raise ValueError("no active incident to recover")
            if approval.incident_started_at != self.production.incident_started_at:
                raise ValueError("approval belongs to an earlier incident")
            if action not in RECOVERY_SPECS or self.production.incident_type not in RECOVERY_SPECS[action]["incident_types"] or action == self.production.last_failed_action:
                raise ValueError("action is no longer valid for this incident")
            approval.used = True
            approval.approved_by = approved_by
            spec = RECOVERY_SPECS[action]
            self.production.verification_snapshot = None
            self.production.verification_complete = False
            self.production.recovery_baseline = self.status()
            self.production.recovery_action = action
            self.production.last_failed_action = None
            self.production.recovery_progress = 1
            self.production.recovery_failed = False
            self.production.added_cost_usd += spec["cost"]
            if action == "add-workers":
                first_id = len(self.production.workers) + 1
                for n in range(first_id, first_id + 2):
                    worker_id = f"TEMP-{uuid.uuid4().hex[:12]}"
                    self.production.workers[worker_id] = Worker(worker_id, frames_per_hour=110, hourly_rate_usd=6.5)
            elif action == "prioritize-scenes":
                for scene in self.production.scenes.values():
                    scene.priority = 200 if scene.trailer_critical else 1
                for worker in self.production.workers.values():
                    worker.healthy = True
                    worker.frames_per_hour = 46
                    worker.gpu_memory_utilization = 74
            elif action == "restart-workers":
                for worker in self.production.workers.values():
                    worker.healthy = True
                    worker.gpu_memory_utilization = 70
            elif action == "reduce-preview-quality":
                for scene in self.production.scenes.values():
                    if scene.trailer_critical:
                        scene.total_frames = max(scene.completed_frames, math.ceil(scene.total_frames * .82))
            elif action == "restore-asset":
                self.production.scenes["SC-94"].failed_frames = 0
            elif action == "rebalance-queue":
                for scene in self.production.scenes.values():
                    scene.priority = 220 if scene.trailer_critical else 1
            self.production.storage_utilization = 65
            self.production.network_latency_ms = 14
            self.production.asset_error_rate = 0
            execution_id = str(uuid.uuid4())
            self.record("recovery_executed", approval_id=approval_id, execution_id=execution_id, action=action,
                        approved_by=approved_by, added_cost_usd=spec["cost"])
            return {"execution_id": execution_id, "action": action, "status": "running"}

    def tick(self) -> None:
        with self.lock:
            p = self.production
            if not p.running:
                return
            p.tick_count += 1
            for index, worker in enumerate(p.workers.values()):
                if worker.healthy:
                    phase = p.tick_count / 3 + index * .7
                    worker.gpu_utilization = round(69 + math.sin(phase) * 12 + (index % 3) * 2, 1)
                    worker.gpu_memory_utilization = round(67 + math.sin(phase / 1.7) * 7 + (index % 4), 1)
            if p.incident_active and p.workflow_state == "INVESTIGATING" and p.tick_count % 4 == 0:
                p.workflow_state = "DECISION_REQUIRED"
                scene_id = next((item["scene_id"] for item in INCIDENT_SCENARIOS.values()
                                 if item["issue_type"] == p.incident_type), "SC-87")
                self.record("investigation_completed", scene_id=scene_id, workflow_state="DECISION_REQUIRED")
            if p.recovery_action:
                p.recovery_progress = min(100, p.recovery_progress + 12)
                for scene_id in p.trailer.scene_ids:
                    scene = p.scenes[scene_id]
                    scene.completed_frames = min(scene.total_frames, scene.completed_frames + 18)
                if p.recovery_progress >= 100:
                    # A completed attempt changes the decision state. Unused
                    # alternative tokens cannot authorize a reassessment.
                    p.approvals = {key: token for key, token in p.approvals.items() if token.used}
                    health = (p.storage_utilization < 90 and p.network_latency_ms < 150 and p.asset_error_rate < 10)
                    impact = calculate_delivery_impact(p)
                    passed = health and not impact["deadline_at_risk"] and impact["current_throughput_fph"] >= impact["required_throughput_fph"]
                    if p.fail_next_recovery or not passed:
                        p.fail_next_recovery = False
                        p.recovery_failed = True
                        p.verification_complete = False
                        p.workflow_state = "DECISION_REQUIRED"
                        p.last_failed_action = p.recovery_action
                        self.record("recovery_verification_failed", reason="Throughput remains below required rate",
                                    workflow_state="DECISION_REQUIRED")
                    else:
                        p.incident_active = False
                        p.recovery_failed = False
                        p.verification_complete = True
                        p.workflow_state = "PRODUCTION_SAVED"
                    p.recovery_action = None
                    p.verification_snapshot = self.status()
                    if p.verification_complete:
                        scene_id = next((item["scene_id"] for item in INCIDENT_SCENARIOS.values()
                                         if item["issue_type"] == p.incident_type), "SC-87")
                        self.record("recovery_verified", scene_id=scene_id, workflow_state="PRODUCTION_SAVED")
            elif not p.incident_active:
                for scene in p.scenes.values():
                    scene.completed_frames = min(scene.total_frames, scene.completed_frames + (2 if scene.trailer_critical else 1))
            elif p.incident_type in {"gpu_oom", "queue_surge"}:
                affected = "SC-87" if p.incident_type == "gpu_oom" else "SC-82"
                p.scenes[affected].total_frames += 2
            self._append_history()

    def status(self) -> dict:
        with self.lock:
            p = self.production
            impact = calculate_delivery_impact(p)
            critical_total = sum(p.scenes[s].total_frames for s in p.trailer.scene_ids)
            critical_remaining = impact["remaining_critical_frames"]
            return {"production_id": p.id, "production_title": p.title, "workflow_state": p.workflow_state,
                    "scenario": p.incident_type if p.incident_active else ("recovered" if p.verification_complete else "healthy"),
                    "running": p.running, "incident_active": p.incident_active,
                    "incident_started_at": p.incident_started_at.isoformat() if p.incident_started_at else None,
                    "incident_trace_id": p.incident_trace_id,
                    "recovery_progress": round(p.recovery_progress, 1), "verification_complete": p.verification_complete,
                    "recovery_failed": p.recovery_failed,
                    "last_failed_action": p.last_failed_action,
                    "trailer": {**asdict(p.trailer), "deadline": p.trailer.deadline.isoformat(),
                                "completion_percent": round((critical_total - critical_remaining) / critical_total * 100, 1)},
                    "full_film": {**asdict(p.full_film), "deadline": p.full_film.deadline.isoformat()},
                    "impact": impact, "queue_depth": sum(s.remaining_frames for s in p.scenes.values()),
                    "critical_queue_depth": critical_remaining,
                    "non_critical_queue_depth": sum(s.remaining_frames for s in p.scenes.values() if not s.trailer_critical),
                    "gpu_workers_total": len(p.workers),
                    "gpu_workers_active": sum(1 for w in p.workers.values() if w.healthy),
                    "gpu_memory_utilization": round(max(w.gpu_memory_utilization for w in p.workers.values()), 1),
                    "storage_utilization": p.storage_utilization,
                    "network_latency_ms": p.network_latency_ms,
                    "asset_error_rate": p.asset_error_rate,
                    "retries_total": sum(s.retries for s in p.scenes.values())}
