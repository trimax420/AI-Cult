import copy
import unittest
from datetime import timedelta

from portfolio import StudioPortfolio, utcnow


class StudioPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.portfolio = StudioPortfolio()
        self.portfolio.start_deadline_conflict()

    def option(self, option_id: str) -> dict:
        return next(item for item in self.portfolio.calculate_options() if item["id"] == option_id)

    def execute_transfer(self):
        approval = self.portfolio.request_approval("transfer-four-workers")
        return self.portfolio.execute("transfer-four-workers", approval.id, "director")

    def test_allocation_preview_is_pure(self):
        before = copy.deepcopy(self.portfolio.snapshot()["resource_pool"]["allocations"])
        first = self.portfolio.calculate_options()
        second = self.portfolio.calculate_options()
        self.assertEqual(first, second)
        self.assertEqual(self.portfolio.snapshot()["resource_pool"]["allocations"], before)

    def test_every_option_conserves_workers(self):
        for option in self.portfolio.calculate_options():
            allocated = sum(impact["allocated_workers"] for impact in option["impacts"])
            self.assertEqual(allocated, StudioPortfolio.TOTAL_WORKERS + option["temporary_workers"])

    def test_transfer_preserves_source_project_safety(self):
        transfer = self.option("transfer-four-workers")
        silverline = next(item for item in transfer["impacts"] if item["production_id"] == "silverline")
        self.assertEqual(silverline["allocated_workers"], 10)
        self.assertTrue(silverline["on_time"])

    def test_recommendation_is_deterministic_and_guarded(self):
        options = self.portfolio.calculate_options()
        recommended = [item["id"] for item in options if item["recommended"]]
        self.assertEqual(recommended, ["transfer-four-workers"])
        transfer = self.option("transfer-four-workers")
        self.assertTrue(all(impact["on_time"] for impact in transfer["impacts"]))

    def test_approval_expiry_is_enforced(self):
        approval = self.portfolio.request_approval("transfer-four-workers")
        approval.expires_at = utcnow() - timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError, "expired"):
            self.portfolio.execute("transfer-four-workers", approval.id, "director")

    def test_wrong_option_is_rejected(self):
        approval = self.portfolio.request_approval("transfer-four-workers")
        with self.assertRaisesRegex(ValueError, "invalid"):
            self.portfolio.execute("prioritize-nova-trailer", approval.id, "director")

    def test_approval_cannot_be_replayed(self):
        approval = self.portfolio.request_approval("transfer-four-workers")
        self.portfolio.execute("transfer-four-workers", approval.id, "director")
        with self.assertRaisesRegex(ValueError, "already been used"):
            self.portfolio.execute("transfer-four-workers", approval.id, "director")

    def test_execution_verifies_conservation_and_both_forecasts(self):
        result = self.execute_transfer()
        verification = result["verification"]
        self.assertTrue(verification["verified"])
        self.assertTrue(verification["worker_conservation"])
        self.assertTrue(all(item["on_time"] for item in verification["after"]))
        self.assertEqual(self.portfolio.snapshot()["resource_pool"]["allocations"],
                         {"project-nova": 22, "silverline": 10})
        assignments = self.portfolio.snapshot()["resource_pool"]["assignments"]
        self.assertFalse(set(assignments["project-nova"]) & set(assignments["silverline"]))
        self.assertEqual(len(set(assignments["project-nova"] + assignments["silverline"])), 32)

    def test_reversal_requires_a_new_matching_approval(self):
        self.execute_transfer()
        with self.assertRaisesRegex(ValueError, "invalid"):
            self.portfolio.execute("restore-initial-allocation", "not-approved", "director")
        approval = self.portfolio.request_approval("restore-initial-allocation")
        self.portfolio.execute("restore-initial-allocation", approval.id, "director")
        self.assertEqual(self.portfolio.snapshot()["resource_pool"]["allocations"],
                         {"project-nova": 18, "silverline": 14})


if __name__ == "__main__":
    unittest.main()
