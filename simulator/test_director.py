import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from agent_gateway import presentation_text, production_safe_reply
from director import Director
from domain import ProductionEngine, INCIDENT_SCENARIOS, RECOVERY_SPECS, calculate_recovery_option
from incident_memory import IncidentMemory
from live_runs import LiveRuns
from portfolio import StudioPortfolio


class PresentationTests(unittest.TestCase):
    def test_all_machine_envelopes_only_expose_the_display_field(self):
        body = 'Scene 87 is blocked. Restarting the affected workers restores capacity.'
        payload = json.dumps({'answer':body,'recommended_action':'restart-workers'})
        for raw in [payload, f'```json\n{payload}\n```', f'<production_briefing>{payload}</production_briefing>']:
            self.assertEqual(presentation_text(raw),body)
        for raw in ['{"answer":"unfinished', '{"functionResponse":{"secret":"x"}}', 'Tools said: '+payload, '[{"text":"x"}]', '<production_briefing>broken']:
            self.assertIsNone(presentation_text(raw),raw)

    def test_grounded_figures_allow_explanations_but_reject_invented_quantities(self):
        facts={'workers':22,'delay_minutes':12.4,'cost_usd':17}
        self.assertTrue(Director.grounded_figures('With 22 workers, the forecast is 12 minutes late.',facts))
        self.assertFalse(Director.grounded_figures('The forecast is 99 minutes late.',facts))

    def test_validated_healthy_conversation_keeps_readable_paragraphs(self):
        prose='There is no specific incident currently. Both productions are on track.\n\nNova has 18 workers and Silverline has 14 workers.'
        self.assertEqual(production_safe_reply(prose,'',allow_technical=True),prose)

    def test_historical_machine_messages_are_not_returned_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=IncidentMemory(str(Path(tmp)/'test.db')); m.upsert_production('p','P')
            m.add_message('p',None,'assistant',json.dumps({'answer':'The current production forecast remains on time.'}))
            self.assertEqual(m.messages('p')[0]['body'],'The current production forecast remains on time.')


class DirectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.memory=IncidentMemory(str(Path(self.tmp.name)/'test.db'))
        self.engine=ProductionEngine();self.portfolio=StudioPortfolio()
        self.director=Director(self.engine,self.portfolio,self.memory,Mock())
    def tearDown(self):self.tmp.cleanup()

    def test_worker_transfer_updates_membership_without_losing_health(self):
        self.assertEqual(len(self.engine.production.workers),18)
        self.portfolio.start_deadline_conflict()
        worker=self.director.worker_registry['GPU-32'];worker.healthy=False
        a=self.portfolio.request_approval('transfer-four-workers')
        self.portfolio.execute('transfer-four-workers',a.id,'qa');self.director.sync_workers()
        self.assertEqual(set(self.engine.production.workers),set(self.portfolio.worker_assignments['project-nova']))
        self.assertEqual(len(self.engine.production.workers),22)
        self.assertIs(self.engine.production.workers['GPU-32'],worker)
        self.assertFalse(worker.healthy)
        self.assertEqual(sum(len(x) for x in self.portfolio.worker_assignments.values()),32)

    def test_temporary_workers_are_unique_and_visible_in_both_views(self):
        self.engine.inject_gpu_oom();a=self.engine.request_approval('add-workers');self.engine.execute('add-workers',a.id,'qa')
        self.director.register_temporary_workers()
        pool=self.portfolio.snapshot()['resource_pool']
        self.assertEqual(pool['base_workers'],32);self.assertEqual(pool['temporary_workers'],2)
        self.assertEqual(pool['allocations']['project-nova'],len(self.engine.production.workers))
        self.assertEqual(len(set(sum(pool['assignments'].values(),[]))),34)

    def test_inapplicable_action_cannot_be_approved(self):
        self.engine.inject_corrupted_asset()
        with self.assertRaises(ValueError):self.engine.request_approval('restart-workers')

    def test_alternative_approval_from_before_execution_becomes_stale(self):
        self.engine.inject_gpu_oom()
        first=self.engine.request_approval('restart-workers')
        stale=self.engine.request_approval('add-workers')
        self.engine.production.fail_next_recovery=True
        self.engine.execute('restart-workers',first.id,'qa')
        for _ in range(10):self.engine.tick()
        with self.assertRaises(ValueError):self.engine.execute('add-workers',stale.id,'qa')

    def test_readiness_never_invokes_gemini(self):
        self.director.gateway.base_url='http://agent'
        response=Mock(status=200)
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        with patch('director.urlopen',return_value=response):
            self.assertTrue(self.director.readiness()['agent_connected'])
        self.director.gateway.send.assert_not_called()

    def test_chat_accepts_calculated_cost_difference(self):
        self.portfolio.start_deadline_conflict()
        facts={'portfolio':self.portfolio.snapshot()}
        option=next(o for o in facts['portfolio']['allocation_options'] if o['id']=='add-two-temporary-workers')
        answer=f"Temporary capacity adds ${option['added_cost_usd']:.2f} compared with the current allocation."
        self.director.gateway.send.return_value=json.dumps({'answer':answer})
        self.assertEqual(self.director.chat('Compare costs',facts),answer)

    def test_calculator_matches_each_action_immediately_after_execution(self):
        for scenario, spec in INCIDENT_SCENARIOS.items():
            for action, recovery in RECOVERY_SPECS.items():
                if spec['issue_type'] not in recovery['incident_types']:
                    continue
                engine=ProductionEngine();engine.inject_incident(scenario)
                projected=calculate_recovery_option(engine.production,action)
                approval=engine.request_approval(action);engine.execute(action,approval.id,'qa')
                actual=engine.status()['impact']
                self.assertAlmostEqual(projected['projected_throughput_fph'],actual['current_throughput_fph'],places=1,msg=(scenario,action))
                self.assertAlmostEqual(projected['projected_delay_minutes'],actual['projected_delay_minutes'],delta=.1,msg=(scenario,action))

    def test_progress_does_not_verify_a_late_delivery(self):
        self.engine.inject_gpu_oom();a=self.engine.request_approval('restart-workers')
        self.engine.execute('restart-workers',a.id,'qa')
        for scene in self.engine.production.scenes.values():scene.total_frames+=100000
        for _ in range(10):self.engine.tick()
        self.assertTrue(self.engine.production.recovery_failed)
        self.assertFalse(self.engine.production.verification_complete)

    def test_missing_or_stale_evidence_never_becomes_a_live_recommendation(self):
        g=self.director.gateway
        g.send.return_value=json.dumps({'answer':'Restart the affected workers to restore production capacity.','recommended_action':'restart-workers'})
        g.details.return_value={'evidence':[{'name':'grafana_query_metrics','response':{'ok':True,'scope_id':'old'}}]}
        result=self.director.analyse('investigation','new',{},['restart-workers'],{'scope_id':'new'})
        self.assertFalse(result['ok']);self.assertEqual(result['source'],'unavailable')

    def test_missing_action_gets_one_repair_without_repeating_tools(self):
        g=self.director.gateway
        g.send.side_effect=[json.dumps({'answer':'Restart the affected workers to restore production capacity.'}),
            json.dumps({'answer':'Restart the affected workers to restore production capacity.','recommended_action':'restart-workers'})]
        g.details.return_value={'evidence':[{'name':name,'response':{'ok':True,'scope_id':'new'}} for name in ['grafana_query_metrics','grafana_query_logs','grafana_query_traces']]}
        result=self.director.analyse('investigation','new',{},['restart-workers'],{'scope_id':'new'})
        self.assertTrue(result['ok']);self.assertEqual(g.send.call_count,2)
        self.assertIn('FORMAT_REPAIR',g.send.call_args.args[2])
        self.assertIn('Do not call tools',g.send.call_args.args[2])

    def test_reset_prevents_late_completion_and_duplicate_runs(self):
        started=threading.Event();release=threading.Event();completed=[]
        def work():started.set();release.wait(2);return {'ok':True}
        runs=self.director.runs
        self.assertTrue(runs.start('same','scope','investigation',work,completed.append))
        self.assertFalse(runs.start('same','scope','investigation',work,completed.append))
        started.wait(1);runs.reset();release.set();time.sleep(.05)
        self.assertEqual(runs.get('same')['status'],'superseded');self.assertEqual(completed,[])

if __name__=='__main__':unittest.main()
