"""Coordinate deterministic studio state and durable, evidence-backed ADK phases."""
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen

from agent_gateway import presentation_text, production_safe_reply
from domain import Worker
from live_runs import LiveRuns, now


class Director:
    def __init__(self, engine, portfolio, memory, gateway):
        self.engine, self.portfolio, self.memory, self.gateway = engine, portfolio, memory, gateway
        self.lock = engine.lock
        portfolio.lock = self.lock
        self.runs = LiveRuns(memory.path)
        self.runs.lock = self.lock
        self.current_run = None
        self.incident_id = None
        self.scope_id = f'studio-{uuid.uuid4().hex}'
        self.event = {'scope_id': self.scope_id, 'trace_id': '', 'since': now(), 'event_started_at': now()}
        self.calculated_mode = False
        self.worker_registry = {}
        self.sync_workers()

    def sync_workers(self):
        with self.lock:
            self.worker_registry.update(self.engine.production.workers)
            for ids in self.portfolio.worker_assignments.values():
                for worker_id in ids:
                    self.worker_registry.setdefault(worker_id, Worker(worker_id))
            ids = self.portfolio.worker_assignments['project-nova'] + self.portfolio.temporary_worker_ids
            self.engine.production.workers = {i:self.worker_registry[i] for i in ids}

    def register_temporary_workers(self):
        self.portfolio.temporary_worker_ids = [i for i in self.engine.production.workers if i.startswith('TEMP-')]
        self.worker_registry.update(self.engine.production.workers)

    def reset(self):
        with self.lock:
            self.runs.reset()
            self.engine.reset()
            self.portfolio.reset()
            self.worker_registry = {}
            self.sync_workers()
            self.incident_id = None
            self.current_run = None
            self.calculated_mode = False
            self.scope_id = f'studio-{uuid.uuid4().hex}'
            self.event = {'scope_id': self.scope_id, 'trace_id': '', 'since': now(), 'event_started_at': now()}

    def set_event(self, scope_id, trace_id):
        self.scope_id = scope_id
        self.event = {'scope_id': scope_id, 'trace_id': trace_id, 'since': now(),
                      'event_started_at': (datetime.now(timezone.utc)-timedelta(seconds=2)).isoformat()}
        self.calculated_mode = False

    def public_run(self):
        return self.runs.public(self.runs.get(self.current_run))

    def can_approve(self):
        run = self.public_run()
        return self.calculated_mode or bool(run and run['status'] == 'ready' and run.get('ok') and run['phase'] != 'verification')

    @staticmethod
    def parse(raw):
        if not raw:
            return None
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.I)
        text = re.sub(r'^<production_briefing>\s*|\s*</production_briefing>$', '', text, flags=re.I)
        try:
            value = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(value, dict):
            return None
        answer = presentation_text(value.get('answer') or value.get('conversation_message'))
        if not answer or len(answer) < 12 or len(answer) > 3000:
            return None
        return {**value, 'answer': answer}

    @staticmethod
    def grounded_figures(answer, facts):
        """Reject new quantities while permitting rounded figures and unit conversion."""
        words = {'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10}
        encoded = json.dumps(facts).lower()
        allowed = {float(v.replace(',', '')) for v in re.findall(r'(?<![a-z])\d[\d,]*(?:\.\d+)?', encoded)}
        allowed.update(v for k,v in words.items() if re.search(r'\b'+k+r'\b',encoded))
        # Explain transfers and express calculator hours in minutes without inventing a forecast.
        for option in facts.get('portfolio',{}).get('allocation_options',[]):
            for impact in option.get('impacts',[]):
                allowed.add(impact['completion_hours'] * 60)
                current = next((p for p in facts['portfolio']['productions'] if p['id']==impact['production_id']),None)
                if current:allowed.add(abs(impact['allocated_workers']-current['allocated_workers']))
        pattern = r'\b(\d[\d,]*(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)[ -]*(?:minutes?|hours?|workers?|frames?|percent|%)\b'
        for value in re.findall(pattern, answer.lower()):
            number = words[value] if value in words else float(value.replace(',',''))
            if not any(abs(number-v)<=.51 for v in allowed):return False
        return True

    def analyse(self, phase, scope_id, facts, actions, event):
        prompt = (f'{phase.upper()} for scope {scope_id}. Current authoritative facts: {json.dumps(facts)}. '
                  'Query the required Grafana evidence. Use the calculator values for every forecast. '
                  'Return exactly a JSON object with answer (informative prose), recommended_action '
                  '(one executable id supplied below, or null for verification), condition, impact, '
                  'recommendation_reason, next_step. Wording fields must contain plain prose. '
                  f'Executable action ids: {json.dumps(actions)}. Do not execute or approve anything.')
        if phase == 'verification':
            prompt += ' Verification target: ' + ('incident.' if facts['production'].get('verification_complete') else 'portfolio.')
        raw = self.gateway.send('project-nova', scope_id, prompt)
        details = self.gateway.details()
        payload = self.parse(raw)
        if not payload or (phase != 'verification' and payload.get('recommended_action') not in actions):
            raw = self.gateway.send('project-nova', scope_id,
                'FORMAT_REPAIR. Do not call tools or repeat the investigation. Convert the previous final result '
                'to the requested JSON object, with a plain prose answer and a valid recommended_action. '
                f'Use only these facts: {json.dumps(facts)}. Valid actions: {json.dumps(actions)}.')
            payload = self.parse(raw)
        required = {'grafana_query_metrics', 'grafana_query_logs', 'grafana_query_traces'}
        results = {r['name']:r.get('response', {}) for r in details.get('evidence', []) if r['name'] in required}
        evidence = [{'tool':name, 'ok':bool(r.get('ok')) and r.get('scope_id') == event['scope_id'],
                     'source':r.get('source'), 'observed_at':r.get('observed_at'), 'query':r.get('query'),
                     'trace_id':r.get('trace_id'), 'error':r.get('error')} for name,r in results.items()]
        evidence_ok = required == set(results) and all(item['ok'] for item in evidence)
        action = payload.get('recommended_action') if payload else None
        action_ok = phase == 'verification' or action in actions
        verification_ok = True
        if phase == 'verification' and evidence_ok:
            rows = results['grafana_query_metrics'].get('data', {}).get('data', [])
            values = {(r['metric'].get('__name__'), r['metric'].get('production_id')):float(r['value'][1]) for r in rows}
            value = lambda name, production='project-nova': values.get((f'render_{name}', production), float('nan'))
            if facts['production'].get('verification_complete'):
                verification_ok = (value('current_throughput_per_hour') >= value('required_throughput_per_hour')
                    and value('gpu_memory_utilization_percent') < 95 and value('storage_utilization_percent') < 90
                    and value('network_latency_milliseconds') < 150 and value('asset_error_rate_percent') < 10)
            else:
                verification_ok = bool(facts['portfolio'].get('verification', {}).get('verified'))
            for production in facts['portfolio']['productions']:
                verification_ok = verification_ok and value('portfolio_workers_allocated', production['id']) == production['allocated_workers']
                verification_ok = verification_ok and value('portfolio_predicted_delay_minutes', production['id']) == production['delay_minutes']
        answer = payload.get('answer', '') if payload else ''
        grounding = {'snapshot': facts, 'observed_tools': details.get('evidence', [])}
        costs = {float(v) for v in re.findall(r'"(?:estimated_added_cost_usd|cost_usd|total_cost_usd|added_cost_usd|recovery_cost_usd|baseline_cost_usd|savings_usd|estimated_cost_avoided_usd)":\s*([\d.]+)', json.dumps(grounding))}
        safe = production_safe_reply(answer, '', costs or None, allow_technical=True)
        ok = bool(payload and safe and evidence_ok and action_ok and verification_ok and self.grounded_figures(safe,grounding))
        return {'ok': ok, 'source': 'live-agent' if ok else 'unavailable', 'model': next((u['model'] for u in reversed(details.get('usage',[])) if u.get('model')), os.getenv('GEMINI_MODEL','gemini-3.8-flash')),
                'answer': safe if ok else '', 'recommended_action': action if ok else None,
                'execution_id': facts.get('execution_id'),
                'fields': {k:presentation_text(v) for k,v in (payload or {}).items() if k in {'condition','impact','recommendation_reason','next_step'} and isinstance(v,str) and presentation_text(v) and self.grounded_figures(v,grounding)},
                'evidence': evidence, 'error': None if ok else ('Live evidence is incomplete. Retry the review.' if not evidence_ok else 'Observed recovery does not match the forecast. Retry verification.' if not verification_ok else 'The live response could not be validated. Retry the review.'),
                'raw_response': raw, 'tool_results': details.get('evidence',[]), 'usage': details.get('usage',[])}

    def start(self, phase, facts, actions, key=None, on_complete=None):
        with self.lock:
            scope_id, event = self.scope_id, dict(self.event)
            run_id = key or f'{scope_id}:{phase}:{uuid.uuid4().hex}'
            self.current_run = run_id
            incident_id = self.incident_id or self.scope_id
            def complete(result):
                if self.current_run != run_id:
                    return
                if result.get('ok'):
                    self.memory.add_message('project-nova', incident_id, 'assistant', result['answer'])
                    if incident_id and result.get('recommended_action'):
                        self.memory.update_run_recommendation(incident_id, result['recommended_action'])
                if on_complete:
                    on_complete(result)
            self.runs.start(run_id, scope_id, phase,
                lambda:self.analyse(phase,scope_id,facts,actions,event), complete)
            return run_id

    def chat(self, message, facts):
        scope_id = self.scope_id
        event_run = self.public_run()
        raw = self.gateway.send('project-nova', scope_id,
            'FOLLOW_UP. Answer this production question using the supplied current facts and recorded evidence. '
            'Do not call tools. Return exactly {"answer":"plain prose"}. Explain comparisons and tradeoffs when asked. '
            'Do not claim live verification unless the recorded evidence says it passed. '
            f'Question: {json.dumps(message)}. Facts: {json.dumps(facts)}. Evidence: {json.dumps(event_run)}.')
        payload = self.parse(raw)
        if not payload:
            raw = self.gateway.send('project-nova',scope_id,
                'FORMAT_REPAIR. No tools. Rewrite the previous response as {"answer":"plain prose"}; no internal JSON in the answer.')
            payload = self.parse(raw)
        if not payload:
            raise ValueError('The live response could not be displayed. Please retry your question.')
        if scope_id != self.scope_id:
            raise ValueError('The production context changed. Please ask again.')
        costs = {float(v) for v in re.findall(r'"(?:estimated_added_cost_usd|cost_usd|total_cost_usd|added_cost_usd|recovery_cost_usd|baseline_cost_usd|savings_usd|estimated_cost_avoided_usd)":\s*([\d.]+)',json.dumps(facts))}
        answer = production_safe_reply(payload['answer'], '', costs or None, allow_technical=True)
        if not answer or not self.grounded_figures(answer, facts):
            raise ValueError('The live answer did not match the current forecast. Please retry.')
        return answer

    def readiness(self):
        try:
            with urlopen(self.gateway.base_url + '/list-apps', timeout=2) as response:
                agent_ok = response.status == 200
        except Exception:
            agent_ok = False
        run = self.public_run()
        return {'status': 'ready' if agent_ok and run and run.get('ok') else 'needs_review',
                'agent_connected': agent_ok, 'model': os.getenv('GEMINI_MODEL','gemini-3.8-flash'),
                'model_location': os.getenv('GOOGLE_CLOUD_LOCATION','global'), 'latest_run': run,
                'grafana_url':os.getenv('GRAFANA_PUBLIC_URL','http://localhost:3000/d/ai-production-director/ai-production-director')}
