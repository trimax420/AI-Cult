"""ADK request boundaries and evidence retries, run with the pinned agent runtime."""
import unittest
from unittest.mock import AsyncMock, patch
from google.genai import types
from google.adk.models.llm_request import LlmRequest
from .agent import configure_thinking
from . import grafana_tools as grafana


class RequestBoundaryTests(unittest.TestCase):
    def request(self, prompt, called):
        return LlmRequest(contents=[types.Content(role='user', parts=[types.Part(text=prompt)]),
            types.Content(role='user', parts=[types.Part(function_response=types.FunctionResponse(name=n,response={'ok':True})) for n in called])],
            config=types.GenerateContentConfig(tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=n,description=n) for n in ['grafana_query_metrics','grafana_query_logs','grafana_query_traces','verify_recovery','verify_portfolio_allocation']])]))

    def test_verified_evidence_cannot_be_polled_again_by_model(self):
        r=self.request('VERIFICATION. Verification target: incident.', ['grafana_query_metrics','grafana_query_logs','grafana_query_traces','verify_recovery'])
        configure_thinking(None,r)
        self.assertIsNone(r.config.tools)
        self.assertEqual(r.config.thinking_config.thinking_level.value,'MEDIUM')

    def test_followup_is_low_thinking_without_tools(self):
        r=self.request('FOLLOW_UP. Explain the forecast.',[])
        configure_thinking(None,r)
        self.assertIsNone(r.config.tools)
        self.assertEqual(r.config.thinking_config.thinking_level.value,'LOW')

    def test_only_outstanding_phase_tools_are_offered(self):
        r=self.request('VERIFICATION. Verification target: portfolio.', ['grafana_query_metrics'])
        configure_thinking(None,r)
        names={f.name for t in r.config.tools for f in t.function_declarations}
        self.assertEqual(names,{'grafana_query_logs','grafana_query_traces','verify_portfolio_allocation'})


class EvidenceRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_delayed_ingestion_retries_until_observed(self):
        operation=AsyncMock(side_effect=[{'ok':False},{'ok':True,'data':'fresh'}])
        with patch.object(grafana.asyncio,'sleep',new=AsyncMock()):
            result=await grafana._retry(operation)
        self.assertTrue(result['ok']);self.assertIn('observed_at',result)
        self.assertEqual(operation.await_count,2)

    async def test_success_reused_but_failure_and_new_event_are_requeried(self):
        grafana._EVIDENCE_CACHE.clear()
        operation=AsyncMock(side_effect=[{'ok':False},{'ok':True},{'ok':True}])
        async def operation_wrapper():return await operation()
        read=grafana.reuse_successful_evidence(operation_wrapper)
        context={'scope_id':'one','trace_id':'a','since':'first'}
        with patch.object(grafana,'_context',side_effect=lambda:dict(context)):
            self.assertFalse((await read())['ok'])
            self.assertTrue((await read())['ok'])
            self.assertTrue((await read())['ok'])
            self.assertEqual(operation.await_count,2)
            context['since']='second'
            self.assertTrue((await read())['ok'])
            self.assertEqual(operation.await_count,3)

if __name__=='__main__':unittest.main()
