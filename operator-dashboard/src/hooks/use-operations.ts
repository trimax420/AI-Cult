import {useCallback,useEffect,useRef,useState} from "react"
import type {AuditEvent,Diagnosis,RecoveryPlan,RenderState,TelemetryPoint} from "@/lib/types"
const API_ROOT="/api/simulator"
async function readJson<T>(path:string,init?:RequestInit):Promise<T>{const response=await fetch(`${API_ROOT}${path}`,init);if(!response.ok)throw new Error(await response.text()||`Request failed with ${response.status}`);return response.json() as Promise<T>}
export function useOperations(){
 const [diagnosis,setDiagnosis]=useState<Diagnosis|null>(null),[plans,setPlans]=useState<RecoveryPlan[]>([]),[audit,setAudit]=useState<AuditEvent[]>([]),[state,setState]=useState<RenderState|null>(null),[telemetry,setTelemetry]=useState<TelemetryPoint[]>([]),[error,setError]=useState<string|null>(null),[isApproving,setIsApproving]=useState(false);const inFlight=useRef(false)
 const refresh=useCallback(async()=>{if(inFlight.current)return;inFlight.current=true;try{const [d,p,a,s,h]=await Promise.all([readJson<Diagnosis>("/diagnosis"),readJson<{plans:RecoveryPlan[]}>("/recovery-plans"),readJson<{events:AuditEvent[]}>("/audit-log?limit=25"),readJson<RenderState>("/state"),readJson<{points:Array<{timestamp:string;gpu_memory_utilization:number;queue_depth:number}>}>("/telemetry-history?limit=72")]);setDiagnosis(d);setPlans(p.plans);setAudit(a.events);setState(s);setTelemetry(h.points.map(point=>({time:new Date(point.timestamp).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}),memory:point.gpu_memory_utilization,queue:point.queue_depth})));setError(null)}catch(reason){setError(reason instanceof Error?reason.message:"Unable to reach the simulator")}finally{inFlight.current=false}},[])
 useEffect(()=>{void refresh();const interval=window.setInterval(()=>void refresh(),5000);return()=>window.clearInterval(interval)},[refresh])
 const approve=useCallback(async(planId:string)=>{setIsApproving(true);try{const result=await readJson<{execution_id:string}>(`/recovery-plans/${planId}/approve?approved_by=operator-dashboard`,{method:"POST"});await refresh();return result}finally{setIsApproving(false)}},[refresh])
 return{diagnosis,plans,audit,state,telemetry,error,isApproving,refresh,approve}
}
