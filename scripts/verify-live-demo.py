"""Opt-in live demo acceptance test: resets simulation and uses configured Gemini/Grafana.

Run against a local stack: python3 scripts/verify-live-demo.py
"""
import json,time,urllib.request,urllib.error,os
ROOT=os.getenv('SIMULATOR_URL','http://localhost:8080').rstrip('/')
def api(path,data=None):
 r=urllib.request.Request(ROOT+path,data=json.dumps(data or {}).encode() if data is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(r,timeout=180) as f:return json.load(f)
def wait(phase=None, exclude=None):
 deadline=time.time()+180
 while time.time()<deadline:
  r=api('/productions/project-nova/assistant')['run']
  if r and r['id']!=exclude and r['status']!='running' and (phase is None or r['phase']==phase or (phase=='verification' and r['phase']=='reassessment')):
   print('LIVE',r['phase'],r['status'],r.get('model'),[(e['tool'],e['ok']) for e in r.get('evidence',[])],flush=True)
   if not r.get('ok'):raise RuntimeError(json.dumps(r))
   assert '{' not in r['answer'],r
   return r
  time.sleep(2)
 raise RuntimeError('Timed out waiting for '+str(phase))
def recover(fail=False, attempts=0):
 if attempts>=4:raise RuntimeError('No verified recovery after four approved attempts')
 r=wait();previous=r['id'];a=r['recommended_action'];print('ACTION',a,flush=True)
 if fail:api('/simulation/recovery/fail-next',{})
 approval=api('/approvals?action='+a,{})
 api('/recovery/'+a,{'approval_id':approval['id'],'approved_by':'qa'})
 if fail:
  r=wait('reassessment',exclude=previous);assert r['recommended_action']!=a
  return recover(attempts=attempts+1)
 result=wait('verification',exclude=previous)
 if result['phase']=='reassessment':
  assert result['recommended_action']!=a
  return recover(attempts=attempts+1)
 assert api('/verification/comparison')['passed']
 print('RECOVERED',flush=True)
api('/simulation/reset',{})
api('/portfolio/scenarios/deadline-conflict',{})
wait('portfolio')
a=api('/portfolio/approvals?option_id=transfer-four-workers',{})
api('/portfolio/allocations/transfer-four-workers',{'approval_id':a['id'],'approved_by':'qa'})
wait('verification')
p=api('/portfolio')['resource_pool'];s=api('/simulation/status');assert p['allocations']['project-nova']==s['gpu_workers_total']==22
api('/simulation/incidents/gpu-oom',{})
recover()
print('FULL_PORTFOLIO_PASS',flush=True)
for scenario in ['worker-loss','queue-surge','storage-pressure','network-latency','corrupted-asset']:
 api('/simulation/reset',{});api('/simulation/incidents/'+scenario,{})
 recover();print('SCENARIO_PASS',scenario,flush=True)
api('/simulation/reset',{});api('/simulation/incidents/gpu-oom',{})
recover(True);print('FAILED_RECOVERY_PASS',flush=True)
