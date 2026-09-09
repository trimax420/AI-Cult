import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent_gateway import AgentGateway, production_safe_reply, recommendation_action, structured_briefing


class FakeAdkHandler(BaseHTTPRequestHandler):
    sessions: list[str] = []
    messages: list[dict] = []
    extra_events: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if self.path == "/run_sse":
            self.messages.append(json.loads(body))
            payload = {"content": {"parts": [{"text": "The trailer remains on time. recommendation_action=restart-workers"}]}}
            response = "".join(f"data: {json.dumps(event)}\n\n" for event in [*self.extra_events,payload]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return
        self.sessions.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_):
        return


class AgentGatewayTests(unittest.TestCase):
    def setUp(self):
        FakeAdkHandler.extra_events = []
        FakeAdkHandler.sessions = []
        FakeAdkHandler.messages = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAdkHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.gateway = AgentGateway(f"http://127.0.0.1:{self.server.server_port}", 1, 2)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def test_followups_reuse_the_production_incident_session(self):
        first = self.gateway.send("project-nova", "incident-1", "What is the schedule impact?")
        second = self.gateway.send("project-nova", "incident-1", "What is the safest plan?")
        self.assertIn("trailer remains on time", first)
        self.assertIn("trailer remains on time", second)
        self.assertEqual({message["sessionId"] for message in FakeAdkHandler.messages},
                         {"project-nova-incident-1"})
        self.assertEqual(len(FakeAdkHandler.messages), 2)

    def test_tool_thinking_and_partial_events_do_not_become_the_answer(self):
        FakeAdkHandler.extra_events=[
            {'content':{'parts':[{'text':'private reasoning','thought':True}]}},
            {'partial':True,'content':{'parts':[{'text':'{"unfinished":'}]}},
            {'content':{'parts':[{'functionResponse':{'name':'grafana_query_metrics','response':{'ok':True}}},{'text':'tool dump'}]}},
        ]
        answer=self.gateway.send('project-nova','incident-2','Explain the recovery')
        self.assertIn('trailer remains on time',answer)
        self.assertNotIn('private reasoning',answer)
        self.assertEqual(len(self.gateway.details()['evidence']),1)

    def test_presentation_boundary_removes_internal_language_and_action_marker(self):
        raw = ("Grafana MCP confirmed the trace ID. The trailer remains on time after prioritising scenes. "
               "recommendation_action=prioritize-scenes")
        answer = production_safe_reply(raw, "Fallback")
        self.assertEqual(answer, "The trailer remains on time after prioritising scenes.")
        self.assertEqual(production_safe_reply("Grafana trace ID only.", "Friendly fallback"),
                         "Friendly fallback")
        self.assertEqual(
            production_safe_reply("No specific incident was identified from the production logs and traces.",
                                  "Friendly production assessment"),
            "Friendly production assessment",
        )
        self.assertEqual(
            production_safe_reply("Completion is 2026-09-07T19:38:00+00:00 and costs $96.",
                                  "Current calculated answer", {17, 35}),
            "Current calculated answer",
        )
        self.assertEqual(
            production_safe_reply("This costs $17 and keeps the trailer on time.",
                                  "Fallback", {17, 35}),
            "This costs $17 and keeps the trailer on time.",
        )
        self.assertEqual(recommendation_action(raw), "prioritize-scenes")
        self.assertIsNone(recommendation_action("recommendation_action=delete-production"))

    def test_structured_agent_briefing_is_parsed_and_guarded(self):
        fields = {
            "status_line": "Here’s the production decision I recommend.",
            "condition": "Scene 94 cannot continue because its backdrop artwork is damaged.",
            "impact": "The trailer scene is paused while the rest of the edit can continue.",
            "recommendation_reason": "Restoring the verified artwork fixes the blocked scene without changing the edit.",
            "next_step": "Review the artwork restoration with the production lead before approving it.",
            "conversation_message": "I reviewed the affected scene and prepared the safest production recovery.",
            "recommendation_action": "restore-asset",
        }
        raw = f"<production_briefing>{json.dumps(fields)}</production_briefing>"
        self.assertEqual(structured_briefing(raw), fields)
        self.assertEqual(structured_briefing(f"```json\n{json.dumps(fields)}\n```"), fields)
        self.assertEqual(recommendation_action(json.dumps(fields)), "restore-asset")
        fields["condition"] = "Grafana logs show an internal trace."
        unsafe = f"<production_briefing>{json.dumps(fields)}</production_briefing>"
        self.assertIsNone(structured_briefing(unsafe))


if __name__ == "__main__":
    unittest.main()
