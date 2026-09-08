import tempfile
import threading
import time
import unittest
from pathlib import Path

from incident_memory import IncidentMemory


class IncidentMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.memory = IncidentMemory(str(Path(self.temp.name) / "incidents.db"))
        self.briefing = {"assistant_message": "I found an issue and I am checking the trailer."}

    def tearDown(self):
        self.temp.cleanup()

    def test_incident_and_chat_survive_a_new_store_instance(self):
        incident = self.memory.raise_incident(
            "project-nova", "Project Nova", "gpu_oom", "Scene 87", "Render capacity is unavailable.", self.briefing
        )
        self.memory.add_message("project-nova", incident["id"], "operator", "What does this mean for delivery?")
        reopened = IncidentMemory(self.memory.path)
        self.assertEqual(reopened.active_incident("project-nova")["id"], incident["id"])
        self.assertEqual(len(reopened.messages("project-nova", incident["id"])), 2)
        self.assertEqual(reopened.messages("project-nova"), [])

    def test_duplicate_raise_and_run_are_deduplicated(self):
        incident = self.memory.raise_incident(
            "project-nova", "Project Nova", "gpu_oom", "Scene 87", "Render capacity is unavailable.", self.briefing
        )
        duplicate = self.memory.raise_incident(
            "project-nova", "Project Nova", "gpu_oom", "Scene 87", "Render capacity is unavailable.", self.briefing
        )
        finished = threading.Event()
        self.assertEqual(incident["id"], duplicate["id"])
        self.assertTrue(self.memory.start_run(incident["id"], lambda: finished.set() or None))
        self.assertFalse(self.memory.start_run(incident["id"], lambda: "should not run"))
        self.assertTrue(finished.wait(2))
        for _ in range(50):
            if self.memory.run_for_incident(incident["id"])["status"] == "ready":
                break
            time.sleep(.01)
        self.assertEqual(self.memory.run_for_incident(incident["id"])["status"], "ready")

    def test_agent_action_is_stored_without_exposing_fallback_in_chat(self):
        incident = self.memory.raise_incident(
            "project-nova", "Project Nova", "gpu_oom", "Scene 87", "Render capacity is unavailable.", self.briefing
        )
        self.memory.start_run(
            incident["id"],
            lambda: {"answer": "I recommend prioritising the trailer.",
                     "recommended_action": "prioritize-scenes",
                     "briefing_fields": {"condition": "The agent-authored condition."}},
        )
        for _ in range(50):
            run = self.memory.run_for_incident(incident["id"])
            if run["status"] == "ready":
                break
            time.sleep(.01)
        self.assertEqual(run["source"], "live-agent")
        self.assertEqual(run["recommended_action"], "prioritize-scenes")
        self.assertEqual(run["briefing"]["agent_fields"]["condition"], "The agent-authored condition.")
        self.assertNotIn("fallback", " ".join(message["body"] for message in
                                                self.memory.messages("project-nova", incident["id"])).lower())

    def test_conversations_are_isolated_by_incident(self):
        first = self.memory.raise_incident(
            "project-nova", "Project Nova", "gpu_oom", "Scene 87", "First issue.", self.briefing
        )
        self.memory.add_message("project-nova", first["id"], "operator", "Question for first incident")
        self.memory.resolve_active("project-nova", None, "Reset")
        second = self.memory.raise_incident(
            "project-nova", "Project Nova", "worker_loss", "Scene 91", "Second issue.", self.briefing
        )
        second_messages = self.memory.messages("project-nova", second["id"])
        self.assertEqual(len(second_messages), 1)
        self.assertNotIn("first incident", second_messages[0]["body"].lower())

    def test_only_matching_verified_case_is_returned(self):
        matched = self.memory.similar_case(
            "gpu_oom", "render capacity", "render workers unavailable during the trailer pass"
        )
        self.assertEqual(matched["production_title"], "Silverline")
        self.assertIsNone(self.memory.similar_case("corrupted_asset"))
        self.assertIsNone(self.memory.similar_case("gpu_oom", "sound mix", "dialogue sync drift"))

    def test_resolved_incident_becomes_a_verified_case(self):
        incident = self.memory.raise_incident(
            "project-nova", "Project Nova", "corrupted_asset", "Scene 94", "Artwork needs replacement.", self.briefing
        )
        self.memory.resolve_active("project-nova", "prioritize-scenes", "The trailer returned to an on-time forecast.")
        self.assertIsNone(self.memory.active_incident("project-nova"))
        self.assertEqual(self.memory.incident(incident["id"])["status"], "resolved")
        self.assertEqual(self.memory.similar_case("corrupted_asset")["recovery_action"], "prioritize-scenes")


if __name__ == "__main__":
    unittest.main()
