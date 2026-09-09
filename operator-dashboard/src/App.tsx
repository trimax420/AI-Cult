import { ArchitectureView } from "@/components/architecture-view"
import { useState } from "react"
import { BoxesIcon, CheckCircle2Icon, Clock3Icon, ExternalLinkIcon, GaugeIcon, MemoryStickIcon, PlayIcon, RefreshCwIcon, RotateCcwIcon, ShieldAlertIcon, SparklesIcon, WifiIcon, XCircleIcon } from "lucide-react"
import { toast } from "sonner"

import { DirectorConversation } from "@/components/director-conversation"
import { AiIncidentWorkspace } from "@/components/ai-incident-workspace"
import { AppSidebar, type DashboardView } from "@/components/app-sidebar"
import { AuditTable } from "@/components/audit-table"
import { DiagnosisPanel } from "@/components/diagnosis-panel"
import { MetricCard } from "@/components/metric-card"
import { OperationsTabs } from "@/components/operations-tabs"
import { PortfolioView } from "@/components/portfolio-view"
import { RecoveryPanel } from "@/components/recovery-panel"
import { TelemetryChart } from "@/components/telemetry-chart"
import { VerificationPanel } from "@/components/verification-panel"
import { WhatIfPanel } from "@/components/what-if-panel"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { Skeleton } from "@/components/ui/skeleton"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { PORTFOLIO_ENABLED, useOperations } from "@/hooks/use-operations"

function App() {
  const operations = useOperations()
  const [view, setView] = useState<DashboardView>("overview")
  const state = operations.state
  const incidentActive = Boolean(state?.incident_active)
  const portfolioMode = Boolean(PORTFOLIO_ENABLED && (view === "overview" || view === "recovery") && !incidentActive && state?.workflow_state !== "PRODUCTION_SAVED" && operations.portfolio)

  async function run(action: () => Promise<void>, message: string) {
    try { await action(); toast.success(message) }
    catch { toast.error("I couldn’t complete that request.", { description: "The production remains unchanged. Please try again." }) }
  }

  async function approve(planId: string) {
    try {
      await operations.approve(planId)
      toast.success("Recovery approved", { description: "The ReelWarden is monitoring the production." })
    } catch {
      toast.error("The recovery was not started.", { description: "Nothing changed. Please review the plan and try again." })
    }
  }

  const healthyOverview = !operations.diagnosis || !state ? <div className="loading-grid">{Array.from({ length: 8 }, (_, index) => <Skeleton key={index} />)}</div> : <div className="operations-grid">
    <section className="primary-column">
      <div className="metric-grid">
        <MetricCard title="Trailer completion" value={`${state.trailer.completion_percent}%`} helper="Critical scenes rendered" icon={Clock3Icon} tone="normal" />
        <MetricCard title="Throughput" value={`${state.impact.current_throughput_fph} f/h`} helper={`Required ${state.impact.required_throughput_fph} f/h`} icon={GaugeIcon} tone="normal" />
        <MetricCard title="Render workers" value={`${state.gpu_workers_active} / ${state.gpu_workers_total}`} helper="Healthy capacity" icon={MemoryStickIcon} tone="normal" />
        <MetricCard title="Critical queue" value={String(state.critical_queue_depth)} helper={`${state.non_critical_queue_depth} background frames`} icon={BoxesIcon} tone="normal" />
      </div>
      <VerificationPanel comparison={operations.verification} />
      <WhatIfPanel key={`what-if-${state.incident_started_at ?? "healthy"}`} calculate={operations.whatIf} />
      <TelemetryChart data={operations.telemetry} />
      <DiagnosisPanel diagnosis={operations.diagnosis} />
    </section>
    <RecoveryPanel plans={operations.plans} isApproving={operations.busy} onApprove={approve} />
    <AuditTable events={operations.audit} />
  </div>

  const content = view === "architecture" ? <ArchitectureView readiness={operations.readiness} /> : view === "overview" && incidentActive && state && operations.assistant
    ? <AiIncidentWorkspace key={`incident-${operations.assistant.incident?.id ?? "none"}`} assistant={operations.assistant} state={state} busy={operations.busy} onApprove={approve} />
    : portfolioMode && operations.portfolio
      ? <PortfolioView portfolio={operations.portfolio} busy={operations.busy}
          onStartConflict={() => run(operations.startDeadlineConflict, "Deadline conflict ready")}
          onApprove={(optionId) => run(() => operations.approveAllocation(optionId), "Allocation applied; live verification started")}
          onContinue={() => run(operations.continueDemo, "Nova incident raised")} />
    : view === "overview"
      ? healthyOverview
      : !operations.diagnosis || !state
        ? <div className="loading-grid"><Skeleton /><Skeleton /><Skeleton /></div>
        : <OperationsTabs view={view} state={state} diagnosis={operations.diagnosis} audit={operations.audit} plans={operations.plans} isApproving={operations.busy} onApprove={approve} />

  return <TooltipProvider><SidebarProvider defaultOpen>
    <AppSidebar activeView={view} incidentCount={incidentActive ? 1 : 0} onNavigate={setView} />
    <SidebarInset>
      <header className="topbar"><div className="production-switcher"><SidebarTrigger /><Separator orientation="vertical" /><span>{PORTFOLIO_ENABLED ? "Studio Portfolio" : "Project Nova"}</span></div><div className="topbar-actions"><span className="live-status"><WifiIcon />{operations.error ? "Reconnecting" : operations.readiness?.agent_connected ? "Agent connected" : "Agent unavailable"}</span><Separator orientation="vertical" /><Button variant="outline" render={<a href={operations.readiness?.grafana_url ?? "http://localhost:3000"} target="_blank" rel="noreferrer" />}><ExternalLinkIcon data-icon="inline-end" />Open Grafana</Button></div></header>
      <main className={`dashboard-shell ${portfolioMode ? "portfolio-shell" : ""} ${incidentActive ? "incident-mode" : ""}`}>
        {!portfolioMode && view !== "architecture" ? <section className={`story-state ${state?.workflow_state.toLowerCase() ?? "on_track"}`}><div className="state-icon">{state?.recovery_failed ? <XCircleIcon /> : state?.workflow_state === "PRODUCTION_SAVED" ? <CheckCircle2Icon /> : incidentActive ? <ShieldAlertIcon /> : <PlayIcon />}</div><div><span>ReelWarden</span><h1>{state?.recovery_failed ? "I’m reassessing the recovery." : incidentActive ? "Production issue under review" : state?.workflow_state === "PRODUCTION_SAVED" ? operations.assistant?.run?.phase === "verification" && operations.assistant.run.ok ? "Production saved — verified with Grafana." : "Simulator recovery complete — checking live evidence." : "Production on track"}</h1><p>{state?.recovery_failed ? "The first recovery did not verify. The live agent is reviewing a different plan below." : incidentActive ? "The ReelWarden is assessing the trailer impact and recommended next step." : state?.workflow_state === "PRODUCTION_SAVED" ? "The simulator forecast is on time. Review the agent’s observed verification below." : "Project Nova’s trailer render is meeting its delivery target."}</p></div><Badge>{(state?.workflow_state ?? "CONNECTING").replaceAll("_", " ")}</Badge><div className="demo-controls"><Button variant="outline" disabled={operations.busy} onClick={() => void run(operations.demo, "Demo Mode started")}><SparklesIcon data-icon="inline-start" />Demo Mode</Button><Button variant="outline" disabled={operations.busy} onClick={() => void run(operations.reset, "Simulation reset")}><RotateCcwIcon data-icon="inline-start" />Reset</Button><Button variant="outline" disabled={!incidentActive || operations.busy || state?.recovery_progress !== 0} onClick={() => void run(operations.simulateFailure, "Next recovery will simulate failed verification")}>Simulate failed recovery</Button><Select disabled={operations.busy || incidentActive} onValueChange={(value) => { if (typeof value === "string" && value) void run(() => operations.inject(value), "Production issue raised") }}><SelectTrigger className="scenario-select" aria-label="Raise a failure scenario"><SelectValue>{incidentActive ? operations.scenarios.find(scenario => scenario.issue_type === state?.scenario)?.label : "Raise failure scenario"}</SelectValue></SelectTrigger><SelectContent><SelectGroup>{operations.scenarios.map(scenario => <SelectItem key={scenario.id} value={scenario.id}>{scenario.label} · {scenario.threshold}</SelectItem>)}</SelectGroup></SelectContent></Select></div></section> : null}
        {operations.error ? <p role="status" className="friendly-error">{operations.error}</p> : null}
        {content}
        {view === "overview" && operations.assistant ? <DirectorConversation key={`conversation-${operations.assistant.incident?.id ?? operations.portfolio?.active_decision?.id ?? "studio"}`} assistant={operations.assistant} onAsk={operations.askCopilot} onRetry={operations.retryAgent} onCalculated={operations.calculatedMode} /> : null}
        <Button className="floating-refresh" variant="ghost" size="icon" onClick={() => void operations.refresh()} aria-label="Refresh production status"><RefreshCwIcon /></Button>
      </main>
    </SidebarInset>
    <Toaster />
  </SidebarProvider></TooltipProvider>
}

export default App
