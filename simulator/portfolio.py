from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PortfolioApproval:
    id: str
    option_id: str
    created_at: datetime
    expires_at: datetime
    used: bool = False
    approved_by: str | None = None


@dataclass
class PortfolioProduction:
    id: str
    title: str
    deliverable: str
    priority: str
    deadline_hours: float
    remaining_frames: float
    frames_per_worker_hour: float
    allocated_workers: int
    hourly_worker_cost_usd: float


OPTION_TITLES = {
    "keep-current-allocation": "Keep current allocation",
    "transfer-four-workers": "Transfer four workers",
    "add-two-temporary-workers": "Add two temporary workers",
    "prioritize-nova-trailer": "Prioritize Nova's trailer queue",
}


class StudioPortfolio:
    """Deterministic two-production resource planner.

    The service owns allocation state. Production engines may consume its
    allocation, but never own or duplicate workers from the shared pool.
    """

    TOTAL_WORKERS = 32
    TRANSFER_COUNT = 4

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "lock", threading.RLock()):
            self.portfolio_started_at = utcnow()
            self.scenario_started_at: datetime | None = None
            self.productions = {
                "project-nova": PortfolioProduction(
                    "project-nova", "Project Nova", "High-priority trailer", "high",
                    12, 6_912, 48, 18, 3.75,
                ),
                "silverline": PortfolioProduction(
                    "silverline", "Silverline", "Episodes 3–6 final renders", "standard",
                    24, 9_856, 44, 14, 3.50,
                ),
            }
            self.temporary_worker_ids = []
            self.initial_allocations = {item.id: item.allocated_workers for item in self.productions.values()}
            worker_ids = [f"GPU-{index:02d}" for index in range(1, self.TOTAL_WORKERS + 1)]
            self.worker_assignments = {
                "project-nova": worker_ids[:18], "silverline": worker_ids[18:],
            }
            self.initial_worker_assignments = copy.deepcopy(self.worker_assignments)
            self.scenario_baseline_allocations: dict[str, int] | None = None
            self.approvals: dict[str, PortfolioApproval] = {}
            self.active_decision: dict | None = None
            self.last_verification: dict | None = None
            self.audit: list[dict] = []
            self._record("portfolio_reset")

    def _record(self, event_type: str, **details) -> dict:
        event = {"id": str(uuid.uuid4()), "timestamp": utcnow().isoformat(),
                 "event_type": event_type, "production_id": "studio-portfolio", **details}
        self.audit.append(event)
        self.audit[:] = self.audit[-200:]
        return event

    def _assert_conservation(self, allocations: dict[str, int], temporary_workers: int = 0) -> None:
        if any(workers < 1 for workers in allocations.values()):
            raise ValueError("each production must retain a safe worker allocation")
        if sum(allocations.values()) != self.TOTAL_WORKERS + temporary_workers:
            raise ValueError("worker conservation check failed")

    def start_deadline_conflict(self) -> dict:
        with self.lock:
            if self.active_decision and self.active_decision.get("status") == "executed":
                raise ValueError("reset the portfolio before starting another deadline conflict")
            if self.active_decision:
                raise ValueError("a portfolio decision already exists; reset first")
            self.approvals.clear()
            self.scenario_started_at = utcnow()
            self.scenario_baseline_allocations = {
                item.id: item.allocated_workers for item in self.productions.values()
            }
            self.productions["project-nova"].remaining_frames = 11_232
            options = self.calculate_options()
            recommendation = next(option for option in options if option["recommended"])
            self.active_decision = {
                "id": str(uuid.uuid4()), "status": "awaiting_approval",
                "created_at": self.scenario_started_at.isoformat(),
                "recommended_option_id": recommendation["id"],
            }
            self._record("deadline_conflict_detected", production_id="project-nova",
                         required_throughput_fph=self._required_throughput(self.productions["project-nova"]))
            return self.snapshot()

    @staticmethod
    def _required_throughput(production: PortfolioProduction) -> float:
        return production.remaining_frames / production.deadline_hours

    def _impact(self, production: PortfolioProduction, workers: int, *, throughput_multiplier: float = 1,
                temporary_workers: int = 0, risk: str = "low") -> dict:
        throughput = workers * production.frames_per_worker_hour * throughput_multiplier
        completion_hours = production.remaining_frames / max(throughput, .01)
        delay_minutes = max(0, (completion_hours - production.deadline_hours) * 60)
        reference = self.scenario_started_at or self.portfolio_started_at
        standard_workers = workers - temporary_workers if production.id == "project-nova" else workers
        cost = completion_hours * standard_workers * production.hourly_worker_cost_usd
        if production.id == "project-nova" and temporary_workers:
            cost += completion_hours * temporary_workers * 6.50
        return {
            "production_id": production.id,
            "production_title": production.title,
            "allocated_workers": workers,
            "throughput_fph": round(throughput, 1),
            "required_throughput_fph": round(self._required_throughput(production), 1),
            "completion_at": (reference + timedelta(hours=completion_hours)).isoformat(),
            "completion_hours": round(completion_hours, 2),
            "delay_minutes": round(delay_minutes, 1),
            "cost_usd": round(cost, 2),
            "risk": "high" if delay_minutes > 0 else risk,
            "on_time": delay_minutes == 0,
        }

    def calculate_options(self) -> list[dict]:
        """Return pure projections. No option calculation mutates live allocation."""
        with self.lock:
            nova = self.productions["project-nova"]
            silverline = self.productions["silverline"]
            current = dict(self.scenario_baseline_allocations or {
                production.id: production.allocated_workers for production in self.productions.values()
            })
            definitions = [
                ("keep-current-allocation", current, 0, 1.0, "low"),
                ("transfer-four-workers", {
                    "project-nova": current["project-nova"] + self.TRANSFER_COUNT,
                    "silverline": current["silverline"] - self.TRANSFER_COUNT,
                }, 0, 1.0, "low"),
                ("add-two-temporary-workers", {
                    "project-nova": current["project-nova"] + 2,
                    "silverline": current["silverline"],
                }, 2, 1.0, "low"),
                ("prioritize-nova-trailer", current, 0, 1.12, "medium"),
            ]
            options = []
            for option_id, allocations, temporary, nova_multiplier, risk in definitions:
                self._assert_conservation(allocations, temporary)
                impacts = [
                    self._impact(nova, allocations["project-nova"], throughput_multiplier=nova_multiplier,
                                 temporary_workers=temporary, risk=risk),
                    self._impact(silverline, allocations["silverline"], risk=risk),
                ]
                options.append({
                    "id": option_id,
                    "title": OPTION_TITLES[option_id],
                    "temporary_workers": temporary,
                    "total_workers": self.TOTAL_WORKERS + temporary,
                    "total_cost_usd": round(sum(item["cost_usd"] for item in impacts), 2),
                    "risk": max((item["risk"] for item in impacts), key={"low": 0, "medium": 1, "high": 2}.get),
                    "impacts": impacts,
                    "recommended": False,
                    "requires_approval": option_id == "transfer-four-workers",
                })
            transfer = next(option for option in options if option["id"] == "transfer-four-workers")
            baseline_cost = options[0]['total_cost_usd']
            for option in options:
                option['added_cost_usd'] = round(max(0, option['total_cost_usd'] - baseline_cost), 2)
                option['savings_usd'] = round(max(0, baseline_cost - option['total_cost_usd']), 2)
                for impact in option['impacts']:
                    production = self.productions[impact['production_id']]
                    impact['deadline_buffer_minutes'] = round(max(0, (production.deadline_hours - impact['completion_hours']) * 60), 2)
            nova_now = options[0]["impacts"][0]
            nova_after, silverline_after = transfer["impacts"]
            transfer["recommended"] = (
                not nova_now["on_time"] and nova_after["on_time"] and silverline_after["on_time"]
            )
            return copy.deepcopy(options)

    def request_approval(self, option_id: str) -> PortfolioApproval:
        with self.lock:
            executed = self.active_decision and self.active_decision.get("status") == "executed"
            valid_ids = {"restore-initial-allocation"} if executed else {
                option["id"] for option in self.calculate_options() if option["requires_approval"]
            }
            if option_id not in valid_ids:
                raise ValueError("option is not currently executable")
            if not self.active_decision:
                raise ValueError("start the deadline conflict scenario before requesting approval")
            approval = PortfolioApproval(str(uuid.uuid4()), option_id, utcnow(), utcnow() + timedelta(minutes=5))
            self.approvals[approval.id] = approval
            self._record("portfolio_approval_requested", option_id=option_id, approval_id=approval.id)
            return approval

    def execute(self, option_id: str, approval_id: str, approved_by: str) -> dict:
        with self.lock:
            approval = self.approvals.get(approval_id)
            if not approval or approval.option_id != option_id:
                raise ValueError("approval ID is invalid for this option")
            if approval.used:
                raise ValueError("approval ID has already been used")
            if utcnow() >= approval.expires_at:
                raise ValueError("approval ID has expired")
            if option_id not in {"transfer-four-workers", "restore-initial-allocation"}:
                raise ValueError("only the approved shared-pool transfer can be executed in this demo")
            before = self._current_impacts()
            if option_id == "transfer-four-workers":
                if not self.active_decision or self.active_decision.get("status") != "awaiting_approval":
                    raise ValueError("the transfer decision is no longer executable")
                nova_workers = self.initial_allocations["project-nova"] + self.TRANSFER_COUNT
                silverline_workers = self.initial_allocations["silverline"] - self.TRANSFER_COUNT
                allocations = {"project-nova": nova_workers, "silverline": silverline_workers}
                moved_workers = self.worker_assignments["silverline"][-self.TRANSFER_COUNT:]
                self.worker_assignments["silverline"] = self.worker_assignments["silverline"][:-self.TRANSFER_COUNT]
                self.worker_assignments["project-nova"].extend(moved_workers)
            else:
                allocations = dict(self.initial_allocations)
                self.worker_assignments = copy.deepcopy(self.initial_worker_assignments)
            self._assert_conservation(allocations)
            approval.used = True
            approval.approved_by = approved_by
            for production_id, workers in allocations.items():
                self.productions[production_id].allocated_workers = workers
            after = self._current_impacts()
            assigned_ids = [worker_id for ids in self.worker_assignments.values() for worker_id in ids]
            conservation = (sum(item.allocated_workers for item in self.productions.values()) == self.TOTAL_WORKERS
                            and len(assigned_ids) == self.TOTAL_WORKERS
                            and len(set(assigned_ids)) == self.TOTAL_WORKERS)
            self.last_verification = {
                "available": True, "verified": conservation and all(item["on_time"] for item in after),
                "option_id": option_id, "approval_id": approval_id, "verified_at": utcnow().isoformat(),
                "worker_conservation": conservation, "before": before, "after": after,
            }
            self.active_decision = {
                **(self.active_decision or {}), "status": "executed", "option_id": option_id,
                "approval_id": approval_id, "approved_by": approved_by,
            }
            self._record("portfolio_allocation_executed", option_id=option_id, approval_id=approval_id,
                         approved_by=approved_by, worker_conservation=conservation)
            return {"execution_id": str(uuid.uuid4()), "option_id": option_id,
                    "status": "verified", "verification": copy.deepcopy(self.last_verification)}

    def _current_impacts(self) -> list[dict]:
        return [self._impact(production, production.allocated_workers) for production in self.productions.values()]

    def snapshot(self) -> dict:
        with self.lock:
            options = self.calculate_options() if self.scenario_started_at else []
            summaries = []
            for production in self.productions.values():
                temporary = len(self.temporary_worker_ids) if production.id == "project-nova" else 0
                impact = self._impact(production, production.allocated_workers + temporary, temporary_workers=temporary)
                summaries.append({
                    **asdict(production), **impact,
                    "deadline_at": ((self.scenario_started_at or self.portfolio_started_at) + timedelta(hours=production.deadline_hours)).isoformat(),
                })
            recommendation = next((option for option in options if option["recommended"]), None)
            return {
                "scenario": "deadline-conflict" if self.scenario_started_at else "on-track",
                "resource_pool": {
                    "id": "studio-gpu-pool", "name": "Shared GPU workers", "base_workers": self.TOTAL_WORKERS, "temporary_workers": len(self.temporary_worker_ids), "total_workers": self.TOTAL_WORKERS + len(self.temporary_worker_ids),
                    "allocated_workers": sum(item.allocated_workers for item in self.productions.values()) + len(self.temporary_worker_ids),
                    "available_workers": self.TOTAL_WORKERS - sum(item.allocated_workers for item in self.productions.values()),
                    "allocations": {item.id: item.allocated_workers + (len(self.temporary_worker_ids) if item.id == "project-nova" else 0) for item in self.productions.values()},
                    "assignments": {key: list(ids) + (self.temporary_worker_ids if key == "project-nova" else []) for key, ids in self.worker_assignments.items()},
                },
                "productions": summaries, "active_decision": copy.deepcopy(self.active_decision),
                "recommendation": copy.deepcopy(recommendation), "allocation_options": options,
                "verification": copy.deepcopy(self.last_verification),
            }

    def verification(self) -> dict:
        return copy.deepcopy(self.last_verification) if self.last_verification else {"available": False}
