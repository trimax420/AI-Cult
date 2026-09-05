import{useCallback,useEffect,useRef,useState}from"react"
import type{AgentEvent,AuditEvent,CopilotBriefing,CopilotReply,Diagnosis,Investigation,RecoveryPlan,RenderState,TelemetryPoint,VerificationComparison,WhatIfResult}from"@/lib/types"

const API_ROOT=import.meta.env.VITE_SIMULATOR_API_ROOT||"/api/simulator"
const AGENT_ROOT=import.meta.env.VITE_AGENT_API_ROOT||"/api/agent"
const AGENT_APP="production_director_agent",AGENT_USER="operator-dashboard"

async function request<T>(path:string,init?:RequestInit):Promise<T>{const response=await fetch(`${API_ROOT}${path}`,{...init,headers:{"Content-Type":"application/json",...init?.headers}});if(!response.ok)throw new Error(await response.text()||`Request failed with ${response.status}`);return response.json() as Promise<T>}
const initialSteps=(scene="Scene 87")=>[{id:"metrics",label:"Query Grafana metrics",status:"running" as const},{id:"logs",label:`Search ${scene} logs`,status:"idle" as const},{id:"traces",label:"Inspect correlated render trace",status:"idle" as const},{id:"impact",label:"Calculate deterministic delivery impact",status:"idle" as const}]
const toolStep:Record<string,string>={grafana_query_metrics:"metrics",grafana_query_logs:"logs",grafana_query_traces:"traces",calculate_delivery_impact:"impact"}
const recoveryActions=new Set(["add-workers","prioritize-scenes","restart-workers","reduce-preview-quality"])
type AgentPlaybook={action:string;title:string;rationale:string}
function playbooksFrom(text:string):AgentPlaybook[]{const match=text.match(/<playbooks>\s*([\s\S]*?)\s*<\/playbooks>/i);if(!match)return[];try{const value=JSON.parse(match[1]) as {plans?:unknown[]};return(value.plans??[]).flatMap(plan=>{if(!plan||typeof plan!=="object")return[];const item=plan as Partial<AgentPlaybook>;if(typeof item.action!=="string"||!recoveryActions.has(item.action)||typeof item.title!=="string"||typeof item.rationale!=="string")return[];return[{action:item.action,title:item.title.slice(0,72),rationale:item.rationale.slice(0,280)}]})}catch{return[]}}
function visibleAgentText(text:string){return text.replace(/<playbooks>[\s\S]*?<\/playbooks>/i,"").replace(/recommendation_action\s*=.*$/im,"").trim()}

export function useOperations(){
 const[diagnosis,setDiagnosis]=useState<Diagnosis|null>(null),[agentDiagnosis,setAgentDiagnosis]=useState<Diagnosis|null>(null),[plans,setPlans]=useState<RecoveryPlan[]>([]),[audit,setAudit]=useState<AuditEvent[]>([]),[state,setState]=useState<RenderState|null>(null),[telemetry,setTelemetry]=useState<TelemetryPoint[]>([]),[investigation,setInvestigation]=useState<Investigation|null>(null),[verification,setVerification]=useState<VerificationComparison>({available:false}),[briefing,setBriefing]=useState<CopilotBriefing|null>(null),[error,setError]=useState<string|null>(null),[busy,setBusy]=useState(false),[agentError,setAgentError]=useState<string|null>(null)
 const inFlight=useRef(false),sessionId=useRef<string|null>(null),realAgentActive=useRef(false),diagnosisRef=useRef<Diagnosis|null>(null),agentRecommendation=useRef<string|null>(null),agentRationales=useRef<Record<string,string>>({}),agentTitles=useRef<Record<string,string>>({}),agentController=useRef<AbortController|null>(null)
 const applyAgentRecommendation=useCallback((plans:RecoveryPlan[])=>plans.map(plan=>({...plan,title:agentTitles.current[plan.plan_id]??plan.title,recommended:agentRecommendation.current?plan.plan_id===agentRecommendation.current:plan.recommended,recommendation_source:agentRecommendation.current&&plan.plan_id===agentRecommendation.current?"gemini-adk":plan.recommendation_source,rationale:agentRationales.current[plan.plan_id]??plan.rationale})),[])
 const refresh=useCallback(async()=>{if(inFlight.current)return;inFlight.current=true;try{const[d,p,a,s,h,i,v,b]=await Promise.all([request<Diagnosis>("/diagnosis"),request<{plans:RecoveryPlan[]}>("/recovery-plans"),request<{events:AuditEvent[]}>("/audit-log?limit=25"),request<RenderState>("/simulation/status"),request<{points:Array<{timestamp:string;gpu_memory_utilization:number;queue_depth:number}>}>("/telemetry-history?limit=72"),request<Investigation>("/agent/investigation"),request<VerificationComparison>("/verification/comparison"),request<CopilotBriefing>("/copilot/briefing")]);diagnosisRef.current=d;setDiagnosis(d);setPlans(applyAgentRecommendation(p.plans));setAudit(a.events);setState(s);setVerification(v);setBriefing(realAgentActive.current?{...b,source:"gemini-grafana-mcp"}:b);if(!realAgentActive.current)setInvestigation(i);setTelemetry(h.points.map(point=>({time:new Date(point.timestamp).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}),memory:point.gpu_memory_utilization,queue:point.queue_depth})));setError(null)}catch(reason){setError(reason instanceof Error?reason.message:"Unable to reach the simulator")}finally{inFlight.current=false}},[applyAgentRecommendation])
 useEffect(()=>{const initial=window.setTimeout(()=>void refresh(),0),timer=window.setInterval(()=>void refresh(),2000);return()=>{window.clearTimeout(initial);window.clearInterval(timer)}},[refresh])

 const updateTool=useCallback((tool:string,complete:boolean,response?:unknown)=>{
  const target=toolStep[tool];if(!target)return
  const result=response as {ok?:boolean;error?:string;query?:string;data?:unknown}|undefined
  const failed=complete&&(result?.ok===false||!!result?.error)
  setInvestigation(current=>{
   const steps=(current?.steps??initialSteps()).map(step=>step.id===target?{...step,status:failed?"failed" as const:complete?"complete" as const:"running" as const}:step)
   const evidence={...(current?.evidence??{})}
   if(complete&&target!=="impact")evidence[target]=failed?"Evidence query failed":result?.query??"Tool returned evidence"
   if(complete&&target==="traces"&&!failed){const match=JSON.stringify(result).match(/[a-f0-9]{32}/);if(match)evidence.traces=`Tempo trace ${match[0]}`}
   return{mode:"gemini-grafana-mcp",workflow_state:"INVESTIGATING",steps,evidence}
  })
 },[])

 const runAgent=useCallback(async(prompt:string,phase:"investigate"|"verify"|"chat")=>{
  if(agentController.current)throw new Error("Agent is still working. Try again shortly.")
  setAgentError(null)
  const controller=new AbortController();agentController.current=controller
  const timeout=window.setTimeout(()=>controller.abort(),90000)
  const signal=controller.signal
  try{
   if(!sessionId.current){
    const nextSessionId=globalThis.crypto?.randomUUID?.()??`local-${Date.now()}`
    const created=await fetch(`${AGENT_ROOT}/apps/${AGENT_APP}/users/${AGENT_USER}/sessions/${nextSessionId}`,{method:"POST",headers:{"Content-Type":"application/json"},body:"{}",signal})
    if(!created.ok)throw new Error(`Unable to create the local agent session (${created.status})`)
    const session=await created.json() as {mode?:string}
    if(session.mode==="mock-fallback")throw new Error("Local fallback: Gemini is unavailable")
    sessionId.current=nextSessionId
   }
   realAgentActive.current=true
   if(phase==="investigate")setInvestigation({mode:"gemini-grafana-mcp",workflow_state:"INVESTIGATING",steps:initialSteps(diagnosisRef.current?.scenario==="corrupted_asset"?"Scene 94":"Scene 87"),evidence:{}})
   const response=await fetch(`${AGENT_ROOT}/run_sse`,{method:"POST",headers:{"Content-Type":"application/json"},signal,body:JSON.stringify({appName:AGENT_APP,userId:AGENT_USER,sessionId:sessionId.current,newMessage:{role:"user",parts:[{text:prompt}]}})})
   if(!response.ok||!response.body)throw new Error("Agent request failed")
   const reader=response.body.getReader(),decoder=new TextDecoder();let buffer="",finalText=""
   const completed=new Set<string>()
   function consume(line:string){
    if(!line.startsWith("data:"))return
    const event=JSON.parse(line.slice(5)) as AgentEvent
    if(event.errorMessage)throw new Error(event.errorMessage)
    for(const part of event.content?.parts??[]){
     if(part.functionCall&&phase==="investigate")updateTool(part.functionCall.name,false)
     if(part.functionResponse){
      const {name,response:result}=part.functionResponse
      if(phase==="investigate")updateTool(name,true,result)
      const value=result as {ok?:boolean;error?:unknown}|undefined
      if(value?.ok===false||value?.error)throw new Error(`Evidence tool failed: ${name}`)
      completed.add(name)
     }
     if(part.text)finalText=part.text
    }
   }
   while(true){const{done,value}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const lines=buffer.split("\n");buffer=lines.pop()??"";for(const line of lines)consume(line)}
   buffer+=decoder.decode();if(buffer.trim())consume(buffer)
   if(signal.aborted)throw new DOMException("Agent request cancelled","AbortError")
   if(!finalText.trim()||finalText.includes("mock-fallback"))throw new Error("Agent did not return a complete answer")
   if(phase==="investigate"){
    for(const tool of Object.keys(toolStep))if(!completed.has(tool))throw new Error(`Missing evidence: ${tool}`)
    for(const playbook of playbooksFrom(finalText)){agentTitles.current[playbook.action]=playbook.title;agentRationales.current[playbook.action]=playbook.rationale}
    const recommended=finalText.match(/recommendation_action\s*=\s*(add-workers|prioritize-scenes|restart-workers|reduce-preview-quality)/i)?.[1]?.toLowerCase()
    if(recommended){agentRecommendation.current=recommended;agentRationales.current[recommended]=agentRationales.current[recommended]??visibleAgentText(finalText).slice(0,700);setPlans(current=>applyAgentRecommendation(current))}
    const base=diagnosisRef.current
    if(base)setAgentDiagnosis({...base,root_cause:visibleAgentText(finalText).split("\n").find(line=>line.trim().length>20)?.replaceAll("*","").trim()??base.root_cause,source:"gemini-grafana-mcp"})
    setInvestigation(current=>current?{...current,workflow_state:"DECISION_REQUIRED"}:current)
   }
   return finalText
  }catch(reason){
   if(agentController.current===controller){realAgentActive.current=false;sessionId.current=null;if(!signal.aborted)setAgentError(reason instanceof Error?reason.message:"Agent unavailable")}
   throw reason
  }finally{controller.abort();window.clearTimeout(timeout);if(agentController.current===controller)agentController.current=null}
 },[applyAgentRecommendation,updateTool])

 const act=useCallback(async(path:string)=>{setBusy(true);try{await request(path,{method:"POST"});await refresh()}finally{setBusy(false)}},[refresh])
 const reset=useCallback(async()=>{setAgentError(null);agentController.current?.abort();agentController.current=null;realAgentActive.current=false;sessionId.current=null;agentRecommendation.current=null;agentRationales.current={};agentTitles.current={};setAgentDiagnosis(null);setInvestigation(null);await act("/simulation/reset")},[act])
 const inject=useCallback(async(kind:"gpu-oom"|"corrupted-asset"="gpu-oom")=>{setBusy(true);try{agentController.current?.abort();agentController.current=null;realAgentActive.current=false;sessionId.current=null;setAgentDiagnosis(null);agentRecommendation.current=null;agentRationales.current={};agentTitles.current={};await request(`/simulation/incidents/${kind}`,{method:"POST"});await refresh();void runAgent("Investigate the active Project Nova incident. Query Grafana MCP metrics, logs, and traces once each, calculate deterministic impact, and generate recovery playbooks. Do not request approval or execute recovery. Include exactly one <playbooks>{\"plans\":[{\"action\":\"add-workers\",\"title\":\"context-specific title\",\"rationale\":\"short tradeoff without dollar values or ETA\"}]}</playbooks> block with one plan for each allowlisted action: add-workers, prioritize-scenes, restart-workers, reduce-preview-quality. The title and rationale must be specific to the observed incident. End with exactly recommendation_action=<one allowlisted action id>.","investigate").catch(reason=>{if(reason instanceof DOMException&&reason.name==="AbortError")return;const message=reason instanceof Error?reason.message:"agent unavailable";realAgentActive.current=false;sessionId.current=null;setInvestigation(current=>({...current!,mode:`mock-fallback · ${message}`}))})}finally{setBusy(false)}},[refresh,runAgent])
 const approve=useCallback(async(action:string)=>{setBusy(true);try{agentController.current?.abort();agentController.current=null;sessionId.current=null;const approval=await request<{id:string}>(`/approvals?action=${encodeURIComponent(action)}`,{method:"POST"});const execution=await request<{execution_id:string}>(`/recovery/${action}`,{method:"POST",body:JSON.stringify({approval_id:approval.id,approved_by:"operator-dashboard"})});void runAgent(`The operator already executed approved recovery ${action} with approval ID ${approval.id}. Do not execute any recovery action. Query Grafana metrics, logs, and traces again, then call verify_recovery and report the verification result.`,"verify").catch(()=>undefined);await refresh();return{execution_id:execution.execution_id}}finally{setBusy(false)}},[refresh,runAgent])
 const simulateFailure=useCallback(()=>request<{armed:boolean}>("/simulation/recovery/fail-next",{method:"POST"}).then(()=>undefined),[])
 const askCopilot=useCallback(async(message:string)=>{
  // Keep the deterministic API response as a graceful local fallback, but do
  // not use it when the running ADK service can answer the operator directly.
  const fallback=()=>request<CopilotReply>("/copilot/chat",{method:"POST",body:JSON.stringify({message})})
  try{
   const answer=await runAgent(`Answer this operator question about the current Project Nova production: "${message}". Use live tool evidence whenever it helps. Do not execute or approve a recovery. If you recommend one available recovery action, explain why it is appropriate now and end with recommendation_action=<allowlisted action id>.`,"chat")
   const context=await fallback()
   const suggested=answer.match(/recommendation_action\s*=\s*(add-workers|prioritize-scenes|restart-workers|reduce-preview-quality)/i)?.[1]?.toLowerCase()??null
   if(suggested){agentRecommendation.current=suggested;agentRationales.current[suggested]=answer.replace(/recommendation_action\s*=.*$/im,"").trim().slice(0,700);setPlans(current=>applyAgentRecommendation(current))}
   setBriefing({...context.briefing,source:"gemini-grafana-mcp"})
   return{...context,answer:answer.replace(/recommendation_action\s*=.*$/im,"").trim(),source:"gemini-grafana-mcp",suggested_action:suggested}
  }catch{ return fallback() }
 },[applyAgentRecommendation,runAgent])
 const whatIf=useCallback((input:{workers_added:number;deadline_minutes:number;quality_percent:number;prioritize_critical:boolean})=>request<WhatIfResult>("/impact/what-if",{method:"POST",body:JSON.stringify(input)}),[])
 const demo=useCallback(async()=>{await reset();await new Promise(resolve=>setTimeout(resolve,700));await inject("gpu-oom")},[inject,reset])
 return{agentError,diagnosis:state?.incident_active&&agentDiagnosis&&diagnosis?{...diagnosis,root_cause:agentDiagnosis.root_cause,source:agentDiagnosis.source}:diagnosis,plans,audit,state,telemetry,investigation,verification,briefing,error,busy,refresh,approve,askCopilot,start:()=>act("/simulation/start"),reset,inject,simulateFailure,whatIf,demo}
}
