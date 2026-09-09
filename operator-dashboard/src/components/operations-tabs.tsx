import { ClipboardListIcon, ShieldAlertIcon, WrenchIcon } from "lucide-react"

import { AuditTable } from "@/components/audit-table"
import { DiagnosisPanel } from "@/components/diagnosis-panel"
import { RecoveryPanel } from "@/components/recovery-panel"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import type { AuditEvent, Diagnosis, RecoveryPlan, RenderState } from "@/lib/types"

type OperationsTabProps = {
  view: "incidents" | "recovery" | "audit"
  state: RenderState
  diagnosis: Diagnosis
  audit: AuditEvent[]
  plans: RecoveryPlan[]
  isApproving: boolean
  onApprove: (planId: string) => Promise<void>
}

function incidentLabel(state: RenderState) {
  if (state.scenario === "corrupted_asset") return "Scene 94 asset validation failure"
  if (state.incident_active) return ({gpu_oom:"Scene 87 render memory pressure",worker_loss:"Scene 91 render worker loss",queue_surge:"Scene 82 trailer queue surge",storage_pressure:"Scene 97 storage pressure",network_latency:"Scene 84 transfer slowdown"} as Record<string,string>)[state.scenario] ?? "Production incident"
  return "No active render incident"
}

export function OperationsTabs({ view, state, diagnosis, audit, plans, isApproving, onApprove }: OperationsTabProps) {
  if (view === "recovery") {
    return <section className="tab-view recovery-workspace">
      <header className="tab-heading"><div><span>Recovery command center</span><h1>Human-approved recovery</h1><p>Every action is allowlisted, priced deterministically, and written to the audit timeline.</p></div><WrenchIcon /></header>
      <RecoveryPanel plans={plans} isApproving={isApproving} onApprove={onApprove} />
    </section>
  }

  if (view === "audit") {
    return <section className="tab-view audit-workspace">
      <header className="tab-heading"><div><span>Decision evidence</span><h1>Production audit trail</h1><p>Trace the chain from detection through approval, execution, and verification.</p></div><ClipboardListIcon /></header>
      <div className="audit-summary"><Card><CardHeader><CardTitle>{audit.length}</CardTitle><CardDescription>Recent recorded events</CardDescription></CardHeader></Card><Card><CardHeader><CardTitle>{audit.filter(event => event.approved_by).length}</CardTitle><CardDescription>Human approvals</CardDescription></CardHeader></Card><Card><CardHeader><CardTitle>{audit.filter(event => event.event_type.includes("verified")).length}</CardTitle><CardDescription>Verified outcomes</CardDescription></CardHeader></Card></div>
      <AuditTable events={audit} />
    </section>
  }

  return <section className="tab-view incidents-workspace">
    <header className="tab-heading"><div><span>Live incident record</span><h1>Incident investigation</h1><p>Operational evidence is translated into the trailer delivery decision.</p></div><ShieldAlertIcon /></header>
    <div className="incident-detail-grid"><Card className="incident-primary"><CardHeader><div className="incident-title-row"><Badge variant={state.incident_active ? "destructive" : "secondary"}>{state.incident_active ? "Firing" : "Resolved"}</Badge><span>{state.workflow_state.replaceAll("_", " ")}</span></div><CardTitle>{incidentLabel(state)}</CardTitle><CardDescription>{diagnosis.root_cause}</CardDescription></CardHeader><CardContent><dl className="incident-facts"><div><dt>Trailer ETA</dt><dd>{state.impact.deadline_at_risk ? `${Math.round(state.impact.projected_delay_minutes)} min late` : "On time"}</dd></div><div><dt>Healthy workers</dt><dd>{state.gpu_workers_active} / {state.gpu_workers_total}</dd></div><div><dt>Critical queue</dt><dd>{state.critical_queue_depth} frames</dd></div><div><dt>Evidence source</dt><dd>{diagnosis.source}</dd></div></dl></CardContent></Card><DiagnosisPanel diagnosis={diagnosis} /></div>
    <Card className="incident-events"><CardHeader><CardTitle>Incident timeline</CardTitle><CardDescription>Most recent events tied to the active production workflow.</CardDescription></CardHeader><CardContent><ol>{audit.slice(0, 6).map(event => <li key={event.id}><time>{new Date(event.timestamp).toLocaleTimeString()}</time><strong>{event.event_type.replaceAll("_", " ")}</strong><span>{event.action ?? event.scene_id ?? event.scenario ?? "production event"}</span></li>)}</ol></CardContent></Card>
  </section>
}
