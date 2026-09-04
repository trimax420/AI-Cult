import { useMemo, useState } from "react"
import { BoxesIcon, Clock3Icon, ExternalLinkIcon, GaugeIcon, MemoryStickIcon, RefreshCwIcon, WifiIcon } from "lucide-react"
import { toast } from "sonner"

import { AppSidebar, type DashboardView } from "@/components/app-sidebar"
import { AuditTable } from "@/components/audit-table"
import { DiagnosisPanel } from "@/components/diagnosis-panel"
import { IncidentsView } from "@/components/incidents-view"
import { MetricCard } from "@/components/metric-card"
import { RecoveryPanel } from "@/components/recovery-panel"
import { TelemetryChart } from "@/components/telemetry-chart"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { Skeleton } from "@/components/ui/skeleton"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useOperations } from "@/hooks/use-operations"

function App() {
  const operations = useOperations()
  const [view, setView] = useState<DashboardView>("overview")
  const incident = operations.diagnosis?.severity === "critical" || operations.diagnosis?.severity === "warning"
  const activeIncidentCount = operations.incidents.filter((item) => item.status === "firing").length
  const updated = useMemo(() => operations.diagnosis ? new Date(operations.diagnosis.generated_at).toLocaleTimeString() : "Connecting", [operations.diagnosis])

  function navigate(nextView: DashboardView, sectionId?: string) {
    setView(nextView)
    if (sectionId) window.setTimeout(() => document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth", block: "start" }), 0)
  }

  async function approve(id: string) {
    try {
      const result = await operations.approve(id)
      toast.success("Recovery plan approved", { description: `Execution ${result.execution_id.slice(0, 8)} is now running.` })
    } catch (reason) {
      toast.error("Approval failed", { description: reason instanceof Error ? reason.message : "Please try again." })
    }
  }

  async function approveIncident(incidentId: string, planId: string) {
    try {
      const result = await operations.approveIncident(incidentId, planId)
      toast.success("Incident recovery started", { description: `Execution ${result.execution_id.slice(0, 8)} is now linked to this incident.` })
    } catch (reason) {
      toast.error("Recovery could not start", { description: reason instanceof Error ? reason.message : "Please try again." })
    }
  }

  return (
    <TooltipProvider>
      <SidebarProvider defaultOpen>
        <AppSidebar activeView={view} incidentCount={activeIncidentCount} onNavigate={navigate} />
        <SidebarInset>
          <header className="topbar">
            <div className="production-switcher"><SidebarTrigger /><Separator orientation="vertical" /><span>Neon Horizon Trailer</span></div>
            <div className="topbar-actions"><span className="live-status"><WifiIcon />Live connection</span><Separator orientation="vertical" /><span>Last updated: {updated}</span><Button variant="outline" render={<a href="http://localhost:3000/d/ai-production-director/ai-production-director" target="_blank" rel="noreferrer" />}><ExternalLinkIcon data-icon="inline-end" />Open Grafana</Button></div>
          </header>
          <main className="dashboard-shell">
            <section className="page-heading">
              <div><h1>{view === "incidents" ? "Incidents" : "Production operations"}</h1><p>{view === "incidents" ? "Investigate persisted alerts and their lifecycle." : incident ? "An active condition needs operator attention." : "System is operational. Alerts and recovery controls are live."}</p></div>
              {view === "overview" ? <Badge variant={incident ? "destructive" : "secondary"}>{operations.diagnosis?.scenario.replaceAll("_", " ") ?? "Connecting"}</Badge> : null}
              <Button variant="ghost" size="icon" onClick={() => void operations.refresh()} aria-label="Refresh dashboard"><RefreshCwIcon /></Button>
            </section>
            {operations.error ? <div className="connection-error">Unable to load live data: {operations.error}</div> : null}
            {view === "incidents" ? <IncidentsView incidents={operations.incidents} executions={operations.executions} audit={operations.audit} isApproving={operations.isApproving} getPlans={operations.getIncidentPlans} onApprove={approveIncident} onOpenOverview={() => navigate("overview")} /> : !operations.diagnosis || !operations.state ? (
              <div className="loading-grid">{Array.from({ length: 8 }, (_, index) => <Skeleton key={index} />)}</div>
            ) : (
              <div className="operations-grid">
                <section className="primary-column">
                  <div className="metric-grid">
                    <MetricCard title="Deadline impact" value={`${Math.abs(Math.round(operations.diagnosis.delivery_impact.predicted_delay_minutes))} min`} helper={operations.diagnosis.delivery_impact.deadline_at_risk ? "Past delivery forecast" : "Remaining buffer"} icon={Clock3Icon} tone={operations.diagnosis.delivery_impact.deadline_at_risk ? "critical" : "normal"} />
                    <MetricCard title="Active GPU workers" value={`${operations.state.gpu_workers_active} / ${operations.state.gpu_workers_total}`} helper={`${Math.round(operations.state.gpu_workers_active / operations.state.gpu_workers_total * 100)}% capacity`} icon={GaugeIcon} tone={operations.state.gpu_workers_active < 150 ? "critical" : "normal"} />
                    <MetricCard title="GPU memory" value={`${Math.round(operations.state.gpu_memory_utilization)}%`} helper="Pool B utilization" icon={MemoryStickIcon} tone={operations.state.gpu_memory_utilization > 95 ? "critical" : operations.state.gpu_memory_utilization > 85 ? "warning" : "normal"} />
                    <MetricCard title="Queue depth" value={String(operations.state.queue_depth)} helper="Jobs waiting" icon={BoxesIcon} tone={operations.state.queue_depth > 80 ? "critical" : operations.state.queue_depth > 40 ? "warning" : "normal"} />
                  </div>
                  <TelemetryChart data={operations.telemetry} />
                  <DiagnosisPanel diagnosis={operations.diagnosis} />
                </section>
                <div id="recovery" className="recovery-anchor"><RecoveryPanel plans={operations.plans} isApproving={operations.isApproving} onApprove={approve} /></div>
                <div id="audit" className="audit-anchor"><AuditTable events={operations.audit} /></div>
              </div>
            )}
          </main>
        </SidebarInset>
      </SidebarProvider>
      <Toaster />
    </TooltipProvider>
  )
}

export default App
