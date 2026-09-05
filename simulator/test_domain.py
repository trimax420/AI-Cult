import unittest
from datetime import timedelta

from domain import ProductionEngine, calculate_delivery_impact, calculate_recovery_option, calculate_what_if, utcnow


class ProjectNovaTests(unittest.TestCase):
    def test_second_execution_is_rejected_without_consuming_approval(self):
        engine = ProductionEngine()
        engine.inject_gpu_oom()
        first = engine.request_approval("prioritize-scenes")
        second = engine.request_approval("add-workers")
        engine.execute("prioritize-scenes", first.id, "director")
        with self.assertRaisesRegex(ValueError, "already executing"):
            engine.execute("add-workers", second.id, "director")
        self.assertFalse(second.used)
        self.assertEqual(engine.production.added_cost_usd, 17)

    def test_recovery_requires_an_active_incident(self):
        engine = ProductionEngine()
        approval = engine.request_approval("restart-workers")
        with self.assertRaisesRegex(ValueError, "no active incident"):
            engine.execute("restart-workers", approval.id, "director")
        self.assertFalse(approval.used)

    def test_retry_clears_old_verification_and_new_incident_clears_recovery(self):
        engine = ProductionEngine()
        engine.inject_gpu_oom()
        engine.production.fail_next_recovery = True
        approval = engine.request_approval("prioritize-scenes")
        engine.execute("prioritize-scenes", approval.id, "director")
        for _ in range(10):
            engine.tick()
        self.assertIsNotNone(engine.production.verification_snapshot)
        retry = engine.request_approval("restart-workers")
        engine.execute("restart-workers", retry.id, "director")
        self.assertIsNone(engine.production.verification_snapshot)
        self.assertFalse(engine.production.recovery_failed)
        for _ in range(10):
            engine.tick()
        engine.inject_corrupted_asset()
        self.assertIsNone(engine.production.recovery_baseline)
        self.assertIsNone(engine.production.verification_snapshot)
        self.assertEqual(engine.production.recovery_progress, 0)
        self.assertFalse(engine.production.verification_complete)

    def test_project_has_twenty_workers_and_scene_87_is_critical(self):
        engine = ProductionEngine()
        self.assertEqual(len(engine.production.workers), 20)
        self.assertTrue(engine.production.scenes["SC-87"].trailer_critical)

    def test_gpu_oom_creates_deterministic_deadline_risk(self):
        engine = ProductionEngine()
        engine.inject_gpu_oom()
        impact = calculate_delivery_impact(engine.production)
        self.assertGreater(impact["projected_delay_minutes"], 300)
        self.assertEqual(engine.production.workflow_state, "INVESTIGATING")
        self.assertEqual(sum(not worker.healthy for worker in engine.production.workers.values()), 8)

    def test_prioritization_requires_single_use_approval_and_changes_queue_policy(self):
        engine = ProductionEngine()
        engine.inject_gpu_oom()
        approval = engine.request_approval("prioritize-scenes")
        engine.execute("prioritize-scenes", approval.id, "director")
        self.assertTrue(all(engine.production.scenes[s].priority == 200 for s in engine.production.trailer.scene_ids))
        self.assertTrue(all(scene.priority == 1 for scene in engine.production.scenes.values() if not scene.trailer_critical))
        with self.assertRaisesRegex(ValueError, "already been used"):
            engine.execute("prioritize-scenes", approval.id, "director")

    def test_expired_or_wrong_approval_cannot_execute(self):
        engine = ProductionEngine()
        approval = engine.request_approval("add-workers")
        approval.expires_at = utcnow() - timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError, "expired"):
            engine.execute("add-workers", approval.id, "director")
        other = engine.request_approval("restart-workers")
        with self.assertRaisesRegex(ValueError, "invalid"):
            engine.execute("add-workers", other.id, "director")

    def test_recovery_is_verified(self):
        engine = ProductionEngine()
        engine.inject_gpu_oom()
        approval = engine.request_approval("prioritize-scenes")
        engine.execute("prioritize-scenes", approval.id, "director")
        for _ in range(10):
            engine.tick()
        self.assertEqual(engine.production.workflow_state, "PRODUCTION_SAVED")
        self.assertTrue(engine.production.verification_complete)

    def test_corrupted_asset_targets_scene_94_with_consistent_audit_evidence(self):
        engine = ProductionEngine()
        engine.inject_corrupted_asset()
        self.assertEqual(engine.production.incident_type, "corrupted_asset")
        self.assertEqual(engine.production.scenes["SC-94"].failed_frames, 36)
        self.assertEqual(engine.audit[-1]["scene_id"], "SC-94")
        self.assertEqual(engine.audit[-1]["asset"], "nova_city.exr")

    def test_what_if_is_deterministic_and_does_not_mutate_live_production(self):
        engine = ProductionEngine()
        engine.inject_gpu_oom()
        worker_count = len(engine.production.workers)
        baseline = calculate_what_if(engine.production, deadline_minutes=90)
        recovery = calculate_what_if(engine.production, workers_added=2, deadline_minutes=90,
                                     quality_percent=82, prioritize_critical=True)
        self.assertGreater(recovery["projected_throughput_fph"], baseline["projected_throughput_fph"])
        self.assertLess(recovery["projected_delay_minutes"], baseline["projected_delay_minutes"])
        self.assertEqual(len(engine.production.workers), worker_count)

    def test_telemetry_history_is_seeded_and_changes_on_live_ticks(self):
        engine = ProductionEngine()
        self.assertEqual(len(engine.history), 72)
        seeded_memory = {point["gpu_memory_utilization"] for point in engine.history}
        self.assertGreater(len(seeded_memory), 10)
        before = engine.history[-1]["queue_depth"]
        engine.tick()
        self.assertLess(engine.history[-1]["queue_depth"], before)

    def test_recovery_projection_is_live_and_does_not_mutate_production(self):
        engine = ProductionEngine()
        engine.inject_gpu_oom()
        worker_count = len(engine.production.workers)
        prioritize = calculate_recovery_option(engine.production, "prioritize-scenes")
        no_action = calculate_delivery_impact(engine.production)
        self.assertEqual(len(engine.production.workers), worker_count)
        self.assertEqual(prioritize["deadline_result"], "On time")
        self.assertLess(prioritize["projected_delay_minutes"], no_action["projected_delay_minutes"])

    def test_failed_recovery_returns_to_decision_and_records_verification_failure(self):
        engine = ProductionEngine()
        engine.inject_gpu_oom()
        approval = engine.request_approval("prioritize-scenes")
        engine.production.fail_next_recovery = True
        engine.execute("prioritize-scenes", approval.id, "director")
        for _ in range(10):
            engine.tick()
        self.assertEqual(engine.production.workflow_state, "DECISION_REQUIRED")
        self.assertTrue(engine.production.recovery_failed)
        self.assertFalse(engine.production.verification_complete)
        self.assertTrue(any(event["event_type"] == "recovery_verification_failed" for event in engine.audit))


if __name__ == "__main__":
    unittest.main()
