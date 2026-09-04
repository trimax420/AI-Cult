import { useMemo, useState } from "react"
import { BoxesIcon, CheckCircle2Icon, Clock3Icon, ExternalLinkIcon, FileWarningIcon, GaugeIcon, MemoryStickIcon, PlayIcon, RefreshCwIcon, RotateCcwIcon, ShieldAlertIcon, SparklesIcon, WifiIcon, XCircleIcon } from "lucide-react"
import { toast } from "sonner"

import { AppSidebar, type DashboardView } from "@/components/app-sidebar"
import { AuditTable } from "@/components/audit-table"
import { DiagnosisPanel } from "@/components/diagnosis-panel"
import { MetricCard } from "@/components/metric-card"
import { OperationsTabs } from "@/components/operations-tabs"
import { RecoveryPanel } from "@/components/recovery-panel"
import { TelemetryChart } from "@/components/telemetry-chart"
import { VerificationPanel } from "@/components/verification-panel"
import { WhatIfPanel } from "@/components/what-if-panel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { Skeleton } from "@/components/ui/skeleton"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useOperations } from "@/hooks/use-operations"

const stateCopy = {
  ON_TRACK: { title: "Production on Track", detail: "Project Nova's trailer render is meeting its delivery target." },
  INVESTIGATING: { title: "Incident Under Investigation", detail: "The agent is correlating Grafana metrics, logs, and traces." },
  DECISION_REQUIRED: { title: "Decision Required", detail: "Scene 87 will delay trailer delivery. Choose a recovery option." },
  PRODUCTION_SAVED: { title: "Production Saved — Trailer delivery protected.", detail: "Grafana telemetry confirms throughput recovery and an on-time ETA." },
}

function App() {
  const operations = useOperations()
  const [view, setView] = useState<DashboardView>("overview")
  const state = operations.state
  const baseCopy = stateCopy[state?.workflow_state ?? "ON_TRACK"]
  const copy = state?.scenario === "corrupted_asset" && state.incident_active
    ? { title: state.workflow_state === "INVESTIGATING" ? "Asset Failure Under Investigation" : "Asset Recovery Decision", detail: "Scene 94 cannot render because nova_city.exr is corrupted." }
    : baseCopy
  const incidentCount = useMemo(() => state?.incident_active ? 1 : 0, [state?.incident_active])

  async function run(action: () => Promise<void>, message: string) {
    try { await action(); toast.success(message) }
    catch (reason) { toast.error("Action failed", { description: reason instanceof Error ? reason.message : "Please try again." }) }
  }

  async function approve(planId: string) {
    try {
      const result = await operations.approve(planId)
      toast.success("Recovery approved", { description: `Execution ${result.execution_id.slice(0, 8)} is running.` })
    } catch (reason) {
      toast.error("Approval failed", { description: reason instanceof Error ? reason.message : "Please try again." })
    }
  }

  const overview = !operations.diagnosis || !state ? <div className="loading-grid">{Array.from({ length: 8 }, (_, index) => <Skeleton key={index} />)}</div> : <div className="operations-grid">
    <section className="primary-column">
      <div className="metric-grid">
        <MetricCard title="Trailer completion" value={`${state.trailer.completion_percent}%`} helper="Critical scenes rendered" icon={Clock3Icon} tone="normal" />
        <MetricCard title="Throughput" value={`${state.impact.current_throughput_fph} f/h`} helper={`Required ${state.impact.required_throughput_fph} f/h`} icon={GaugeIcon} tone={state.impact.deadline_at_risk ? "critical" : "normal"} />
        <MetricCard title="GPU workers" value={`${state.gpu_workers_active} / ${state.gpu_workers_total}`} helper="Healthy capacity" icon={MemoryStickIcon} tone={state.gpu_workers_active < state.gpu_workers_total ? "critical" : "normal"} />
        <MetricCard title="Critical queue" value={String(state.critical_queue_depth)} helper={`${state.non_critical_queue_depth} background frames`} icon={BoxesIcon} tone={state.incident_active ? "warning" : "normal"} />
      </div>
      {operations.investigation && ["INVESTIGATING", "DECISION_REQUIRED"].includes(state.workflow_state) ? <Card className="investigation-card"><CardHeader><CardTitle>Agent investigation</CardTitle><Badge variant="secondary">{operations.investigation.mode}</Badge></CardHeader><CardContent><div className="agent-steps">{operations.investigation.steps.map(step => <div key={step.id} data-status={step.status}><span>{step.status === "complete" ? "✓" : step.status === "running" ? "●" : "○"}</span><strong>{step.label}</strong></div>)}</div>{Object.keys(operations.investigation.evidence).length > 0 ? <div className="evidence-strip">{Object.entries(operations.investigation.evidence).map(([key, value]) => <div key={key}><span>{key}</span><strong>{value}</strong></div>)}</div> : null}</CardContent></Card> : null}
      {state.recovery_progress > 0 && !state.verification_complete && !state.recovery_failed ? <div className="recovery-progress"><span>Executing approved recovery</span><strong>{Math.round(state.recovery_progress)}%</strong><div><i style={{ width: `${state.recovery_progress}%` }} /></div></div> : null}
      <VerificationPanel comparison={operations.verification} />
      <WhatIfPanel calculate={operations.whatIf} />
      <TelemetryChart data={operations.telemetry} />
      <DiagnosisPanel diagnosis={operations.diagnosis} />
    </section>
    <RecoveryPanel plans={operations.plans} isApproving={operations.busy} onApprove={approve} />
    <AuditTable events={operations.audit} />
  </div>

  return <TooltipProvider><SidebarProvider defaultOpen><AppSidebar activeView={view} incidentCount={incidentCount} onNavigate={setView} /><SidebarInset>
    <header className="topbar"><div className="production-switcher"><SidebarTrigger /><Separator orientation="vertical" /><span>Project Nova</span></div><div className="topbar-actions"><span className="live-status"><WifiIcon />Live telemetry</span><Separator orientation="vertical" /><Button variant="outline" render={<a href="http://localhost:3000/d/ai-production-director/ai-production-director" target="_blank" rel="noreferrer" />}><ExternalLinkIcon data-icon="inline-end" />Open Grafana</Button></div></header>
    <main className="dashboard-shell">
      <section className={`story-state ${state?.workflow_state.toLowerCase() ?? "on_track"}`}><div className="state-icon">{state?.recovery_failed ? <XCircleIcon /> : state?.workflow_state === "PRODUCTION_SAVED" ? <CheckCircle2Icon /> : state?.incident_active ? <ShieldAlertIcon /> : <PlayIcon />}</div><div><span>AI Production Director</span><h1>{state?.recovery_failed ? "Recovery Failed Verification" : copy.title}</h1><p>{state?.recovery_failed ? "Grafana still shows insufficient throughput. Choose a revised action." : copy.detail}</p></div><Badge>{(state?.workflow_state ?? "CONNECTING").replaceAll("_", " ")}</Badge><div className="demo-controls"><Button variant="outline" disabled={operations.busy} onClick={() => void run(operations.demo, "Demo Mode started")}><SparklesIcon data-icon="inline-start" />Demo Mode</Button><Button variant="outline" disabled={operations.busy} onClick={() => void run(operations.reset, "Simulation reset")}><RotateCcwIcon data-icon="inline-start" />Reset</Button><Button variant="destructive" disabled={operations.busy || state?.incident_active} onClick={() => void run(() => operations.inject("gpu-oom"), "GPU OOM injected on Scene 87")}><MemoryStickIcon data-icon="inline-start" />GPU OOM</Button><Button variant="outline" disabled={operations.busy || state?.incident_active} onClick={() => void run(() => operations.inject("corrupted-asset"), "Corrupted asset injected on Scene 94")}><FileWarningIcon data-icon="inline-start" />Corrupt Asset</Button></div></section>
      {state?.workflow_state === "DECISION_REQUIRED" ? <div className="decision-tools"><Button variant="outline" onClick={() => void run(operations.simulateFailure, "Next recovery will fail verification")}>Simulate failed recovery</Button></div> : null}
      {operations.error ? <div className="connection-error">Unable to load live data: {operations.error}</div> : null}
      {view === "overview" ? overview : !operations.diagnosis || !state ? <div className="loading-grid"><Skeleton /><Skeleton /><Skeleton /></div> : <OperationsTabs view={view} state={state} diagnosis={operations.diagnosis} audit={operations.audit} plans={operations.plans} isApproving={operations.busy} onApprove={approve} />}
      <Button className="floating-refresh" variant="ghost" size="icon" onClick={() => void operations.refresh()} aria-label="Refresh"><RefreshCwIcon /></Button>
    </main>
  </SidebarInset></SidebarProvider><Toaster /></TooltipProvider>
}

export default App
