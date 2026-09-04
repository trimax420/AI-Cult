import { useDeferredValue, useEffect, useMemo, useState } from "react"
import { CheckCircle2Icon, ExternalLinkIcon, LoaderCircleIcon, SearchIcon, ShieldCheckIcon, TriangleAlertIcon } from "lucide-react"

import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { AuditEvent, Incident, RecoveryExecution, RecoveryPlan } from "@/lib/types"

type IncidentsViewProps = {
  incidents: Incident[]
  executions: RecoveryExecution[]
  audit: AuditEvent[]
  isApproving: boolean
  getPlans: (incidentId: string) => Promise<{ can_execute: boolean; plans: RecoveryPlan[] }>
  onApprove: (incidentId: string, planId: string) => Promise<void>
  onOpenOverview: () => void
}

function formatDate(value: string | null) {
  if (!value) return "—"
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
}

function StatusBadge({ status }: Pick<Incident, "status">) {
  return <Badge variant={status === "firing" ? "destructive" : "secondary"}>{status}</Badge>
}

export function IncidentsView({ incidents, executions, audit, isApproving, getPlans, onApprove, onOpenOverview }: IncidentsViewProps) {
  const [status, setStatus] = useState("all")
  const [severity, setSeverity] = useState("all")
  const [query, setQuery] = useState("")
  const [selectedId, setSelectedId] = useState<string | null>(incidents[0]?.id ?? null)
  const [incidentPlans, setIncidentPlans] = useState<RecoveryPlan[]>([])
  const [canExecute, setCanExecute] = useState(false)
  const [isLoadingPlans, setIsLoadingPlans] = useState(false)
  const deferredQuery = useDeferredValue(query.trim().toLowerCase())

  const severities = useMemo(() => Array.from(new Set(incidents.map((incident) => incident.severity))).sort(), [incidents])
  const filtered = useMemo(() => incidents.filter((incident) => {
    const matchesStatus = status === "all" || incident.status === status
    const matchesSeverity = severity === "all" || incident.severity === severity
    const haystack = `${incident.title} ${incident.summary} ${incident.component} ${incident.fingerprint}`.toLowerCase()
    return matchesStatus && matchesSeverity && (!deferredQuery || haystack.includes(deferredQuery))
  }), [deferredQuery, incidents, severity, status])
  const selected = incidents.find((incident) => incident.id === selectedId) ?? filtered[0] ?? null
  const activeCount = incidents.filter((incident) => incident.status === "firing").length
  const selectedIncidentId = selected?.id ?? null
  const execution = selected ? executions.find((item) => item.incident_id === selected.id) ?? null : null
  const incidentAudit = useMemo(() => selected ? audit.filter((event) => event.incident_id === selected.id).slice(0, 4) : [], [audit, selected])

  useEffect(() => {
    if (!selectedIncidentId) return
    let active = true
    void getPlans(selectedIncidentId).then((result) => {
      if (!active) return
      setIncidentPlans(result.plans)
      setCanExecute(result.can_execute)
    }).finally(() => { if (active) setIsLoadingPlans(false) })
    return () => { active = false }
  }, [getPlans, selectedIncidentId])

  return (
    <div className="incidents-workspace">
      <section className="incident-summary-grid" aria-label="Incident summary">
        <Card size="sm"><CardHeader><CardDescription>All incidents</CardDescription><CardTitle>{incidents.length}</CardTitle></CardHeader></Card>
        <Card size="sm"><CardHeader><CardDescription>Needs attention</CardDescription><CardTitle>{activeCount}</CardTitle></CardHeader></Card>
        <Card size="sm"><CardHeader><CardDescription>Resolved</CardDescription><CardTitle>{incidents.length - activeCount}</CardTitle></CardHeader></Card>
      </section>

      <Card className="incident-list-card">
        <CardHeader>
          <CardTitle>Incident history</CardTitle>
          <CardDescription>Grafana alert events persisted by the production simulator.</CardDescription>
          <CardAction><Badge variant="outline">{filtered.length} shown</Badge></CardAction>
        </CardHeader>
        <CardContent>
          <div className="incident-filters">
            <label className="incident-search"><SearchIcon /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search incidents" aria-label="Search incidents" /></label>
            <Select value={status} onValueChange={(value) => setStatus(value ?? "all")}>
              <SelectTrigger aria-label="Filter by status"><SelectValue /></SelectTrigger>
              <SelectContent><SelectGroup><SelectItem value="all">All statuses</SelectItem><SelectItem value="firing">Firing</SelectItem><SelectItem value="resolved">Resolved</SelectItem></SelectGroup></SelectContent>
            </Select>
            <Select value={severity} onValueChange={(value) => setSeverity(value ?? "all")}>
              <SelectTrigger aria-label="Filter by severity"><SelectValue /></SelectTrigger>
              <SelectContent><SelectGroup><SelectItem value="all">All severities</SelectItem>{severities.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectGroup></SelectContent>
            </Select>
          </div>
          <div className="incident-table-wrap">
            <Table>
              <TableHeader><TableRow><TableHead>Incident</TableHead><TableHead>Status</TableHead><TableHead>Component</TableHead><TableHead>Started</TableHead></TableRow></TableHeader>
              <TableBody>
                {filtered.length ? filtered.map((incident) => (
                  <TableRow key={incident.id} data-selected={selected?.id === incident.id} onClick={() => setSelectedId(incident.id)} tabIndex={0} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelectedId(incident.id) }}>
                    <TableCell><strong>{incident.title}</strong><span>{incident.summary}</span></TableCell>
                    <TableCell><StatusBadge status={incident.status} /></TableCell>
                    <TableCell className="incident-component">{incident.component}</TableCell>
                    <TableCell>{formatDate(incident.starts_at)}</TableCell>
                  </TableRow>
                )) : <TableRow><TableCell colSpan={4} className="incident-empty">No incidents match these filters.</TableCell></TableRow>}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card className="incident-detail-card">
        {selected ? <>
          <CardHeader>
            <div className="incident-detail-icon" data-status={selected.status}>{selected.status === "firing" ? <TriangleAlertIcon /> : <ShieldCheckIcon />}</div>
            <CardTitle>{selected.title}</CardTitle>
            <CardDescription>{selected.summary}</CardDescription>
            <CardAction><StatusBadge status={selected.status} /></CardAction>
          </CardHeader>
          <CardContent>
            <dl className="incident-detail-list">
              <div><dt>Severity</dt><dd><Badge variant="outline">{selected.severity}</Badge></dd></div>
              <div><dt>Component</dt><dd>{selected.component}</dd></div>
              <div><dt>Started</dt><dd>{formatDate(selected.starts_at)}</dd></div>
              <div><dt>Resolved</dt><dd>{formatDate(selected.ends_at)}</dd></div>
              <div><dt>Last update</dt><dd>{formatDate(selected.updated_at)}</dd></div>
              <div><dt>Fingerprint</dt><dd><code>{selected.fingerprint}</code></dd></div>
            </dl>
            <Separator />
            <section className="incident-recovery-section">
              <div className="incident-section-heading"><div><h3>Recovery</h3><p>{execution ? "Execution progress is persisted and synchronized with live telemetry." : canExecute ? "Plans ranked for this incident's affected component." : "Recovery is unavailable because this incident is resolved."}</p></div>{execution ? <Badge variant={execution.status === "executing" ? "default" : "secondary"}>{execution.status}</Badge> : null}</div>
              {execution ? <div className="incident-execution"><div><strong>{execution.plan_title}</strong><span>{Math.round(execution.progress)}%</span></div><Progress value={execution.progress} /><small>Approved by {execution.approved_by} · started {formatDate(execution.started_at)}</small></div> : null}
              {!execution && canExecute ? <div className="incident-plan-list">{isLoadingPlans ? <div className="incident-plan-loading"><LoaderCircleIcon />Loading recovery plans</div> : incidentPlans.map((plan) => <Card key={plan.plan_id} size="sm" className="incident-plan"><CardHeader><CardTitle>{plan.title}</CardTitle>{plan.recommended ? <CardAction><Badge>Recommended</Badge></CardAction> : null}<CardDescription>{plan.estimated_recovery_minutes} min · ${plan.estimated_added_cost_usd} · {plan.risk} risk</CardDescription></CardHeader>{plan.recommended ? <CardContent><AlertDialog><AlertDialogTrigger render={<Button disabled={isApproving} />}>{isApproving ? <LoaderCircleIcon className="animate-spin" data-icon="inline-start" /> : <CheckCircle2Icon data-icon="inline-start" />}Approve recovery</AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Start recovery for this incident?</AlertDialogTitle><AlertDialogDescription>{plan.title} will execute immediately, update live telemetry, and be recorded against incident {selected.id.slice(0, 8)}.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={() => void onApprove(selected.id, plan.plan_id)}>Approve and execute</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog></CardContent> : null}</Card>)}</div> : null}
            </section>
            {incidentAudit.length ? <><Separator /><section className="incident-audit-section"><div className="incident-section-heading"><div><h3>Incident activity</h3><p>Latest persisted events for this incident.</p></div></div><ul>{incidentAudit.map((event) => <li key={event.id}><span>{event.event_type.replaceAll("_", " ")}</span><time>{formatDate(event.timestamp)}</time></li>)}</ul></section></> : null}
            <Separator />
            <div className="incident-detail-actions">
              <Button onClick={onOpenOverview}>View live diagnosis</Button>
              <Button variant="outline" render={<a href="http://localhost:3000/alerting/list" target="_blank" rel="noreferrer" />}><ExternalLinkIcon data-icon="inline-end" />Open in Grafana</Button>
            </div>
          </CardContent>
        </> : <CardContent className="incident-empty">Select an incident to inspect its alert evidence.</CardContent>}
      </Card>
    </div>
  )
}
