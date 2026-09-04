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
    approvals: dict[str, Approval] = field(default_factory=dict)
    added_cost_usd: float = 0.0
    tick_count: int = 0
    recovery_baseline: dict | None = None
    verification_snapshot: dict | None = None


RECOVERY_SPECS = {
    "add-workers": {"title": "Add two GPU workers", "cost": 84.0, "risk": "low"},
    "prioritize-scenes": {"title": "Prioritize trailer scenes", "cost": 17.0, "risk": "medium"},
    "restart-workers": {"title": "Restart affected workers", "cost": 12.0, "risk": "low"},
    "reduce-preview-quality": {"title": "Reduce preview quality", "cost": 4.0, "risk": "medium"},
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
        throughput *= .265 if production.incident_type == "gpu_oom" else .38
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
        throughput *= .92 if prioritize_critical else (.265 if production.incident_type == "gpu_oom" else .38)
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
        raw_capacity = sum(worker.frames_per_hour for worker in production.workers.values()) / 42 * 46
        efficiency = .92
    elif action == "restart-workers":
        raw_capacity = sum(worker.frames_per_hour for worker in production.workers.values())
        efficiency = .86
    else:
        remaining *= .82
        efficiency = .82
    throughput = max(.01, raw_capacity * efficiency)
    hours_left = max((production.trailer.deadline - utcnow()).total_seconds() / 3600, 1 / 60)
    completion_hours = remaining / throughput
    delay_minutes = max(0.0, (completion_hours - hours_left) * 60)
    spec = RECOVERY_SPECS[action]
    return {"projected_throughput_fph": round(throughput, 1),
            "projected_delay_minutes": round(delay_minutes, 1),
            "deadline_result": "On time" if delay_minutes == 0 else f"{int(delay_minutes // 60)}h {int(delay_minutes % 60)}m late",
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
                             "throughput_fph": impact["current_throughput_fph"]})
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
        with self.lock:
            scene = self.production.scenes["SC-87"]
            scene.retries += 1
            scene.failed_frames += 24
            for worker in list(self.production.workers.values())[:8]:
                worker.healthy = False
                worker.gpu_memory_utilization = 99.2
                worker.gpu_utilization = 8
                worker.current_scene_id = "SC-87"
                worker.retries += 1
            self.production.incident_active = True
            self.production.incident_type = "gpu_oom"
            self.production.incident_started_at = utcnow()
            self.production.workflow_state = "INVESTIGATING"
            self.production.verification_complete = False
            self.record("gpu_oom_injected", scene_id="SC-87", failed_workers=8, workflow_state="INVESTIGATING")

    def inject_corrupted_asset(self) -> None:
        with self.lock:
            scene = self.production.scenes["SC-94"]
            scene.retries += 3
            scene.failed_frames += 36
            self.production.incident_active = True
            self.production.incident_type = "corrupted_asset"
            self.production.incident_started_at = utcnow()
            self.production.workflow_state = "INVESTIGATING"
            self.production.verification_complete = False
            self.record("corrupted_asset_injected", scene_id="SC-94", asset="nova_city.exr",
                        workflow_state="INVESTIGATING")

    def request_approval(self, action: str) -> Approval:
        if action not in RECOVERY_SPECS:
            raise ValueError("unsupported recovery action")
        with self.lock:
            approval = Approval(str(uuid.uuid4()), action, utcnow(), utcnow() + timedelta(minutes=10))
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
            approval.used = True
            approval.approved_by = approved_by
            spec = RECOVERY_SPECS[action]
            self.production.recovery_baseline = self.status()
            self.production.recovery_action = action
            self.production.recovery_progress = 1
            self.production.recovery_failed = False
            self.production.added_cost_usd += spec["cost"]
            if action == "add-workers":
                for n in range(21, 23):
                    self.production.workers[f"GPU-{n:02d}"] = Worker(f"GPU-{n:02d}", frames_per_hour=110)
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
                scene_id = "SC-94" if p.incident_type == "corrupted_asset" else "SC-87"
                self.record("investigation_completed", scene_id=scene_id, workflow_state="DECISION_REQUIRED")
            if p.recovery_action:
                p.recovery_progress = min(100, p.recovery_progress + 12)
                for scene_id in p.trailer.scene_ids:
                    scene = p.scenes[scene_id]
                    scene.completed_frames = min(scene.total_frames, scene.completed_frames + 18)
                if p.recovery_progress >= 100:
                    if p.fail_next_recovery:
                        p.fail_next_recovery = False
                        p.recovery_failed = True
                        p.verification_complete = False
                        p.workflow_state = "DECISION_REQUIRED"
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
                        scene_id = "SC-94" if p.incident_type == "corrupted_asset" else "SC-87"
                        self.record("recovery_verified", scene_id=scene_id, workflow_state="PRODUCTION_SAVED")
            elif not p.incident_active:
                for scene in p.scenes.values():
                    scene.completed_frames = min(scene.total_frames, scene.completed_frames + (2 if scene.trailer_critical else 1))
            elif p.incident_type == "gpu_oom":
                # Failed retries add to the queue while Scene 87 remains blocked.
                p.scenes["SC-87"].total_frames += 2
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
                    "recovery_progress": round(p.recovery_progress, 1), "verification_complete": p.verification_complete,
                    "recovery_failed": p.recovery_failed,
                    "trailer": {**asdict(p.trailer), "deadline": p.trailer.deadline.isoformat(),
                                "completion_percent": round((critical_total - critical_remaining) / critical_total * 100, 1)},
                    "full_film": {**asdict(p.full_film), "deadline": p.full_film.deadline.isoformat()},
                    "impact": impact, "queue_depth": sum(s.remaining_frames for s in p.scenes.values()),
                    "critical_queue_depth": critical_remaining,
                    "non_critical_queue_depth": sum(s.remaining_frames for s in p.scenes.values() if not s.trailer_critical),
                    "gpu_workers_total": len(p.workers),
                    "gpu_workers_active": sum(1 for w in p.workers.values() if w.healthy),
                    "gpu_memory_utilization": round(max(w.gpu_memory_utilization for w in p.workers.values()), 1),
                    "retries_total": sum(s.retries for s in p.scenes.values())}
