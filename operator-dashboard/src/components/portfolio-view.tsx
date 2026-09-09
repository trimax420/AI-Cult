import { useState } from "react"
import { ArrowRightIcon, CheckCircle2Icon, CpuIcon, FilmIcon, PlayIcon, SparklesIcon, TimerResetIcon } from "lucide-react"

import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { AllocationOption, PortfolioSnapshot, ProductionSummary, ProjectImpact } from "@/lib/types"

type PortfolioViewProps = {
  portfolio: PortfolioSnapshot
  busy: boolean
  onStartConflict: () => Promise<void>
  onApprove: (optionId: string) => Promise<void>
  onContinue: () => Promise<void>
}

const dateTime = new Intl.DateTimeFormat([], { weekday: "short", hour: "numeric", minute: "2-digit" })
const money = new Intl.NumberFormat([], { style: "currency", currency: "USD", maximumFractionDigits: 0 })

function impact(option: AllocationOption, productionId: string): ProjectImpact {
  return option.impacts.find(item => item.production_id === productionId) as ProjectImpact
}

function forecastLabel(item: ProjectImpact | ProductionSummary): string {
  if (!item.on_time) return `${Math.round(item.delay_minutes)}m late`
  return `${item.completion_hours.toFixed(1)}h · on time`
}

function ProductionPanel({ production }: { production: ProductionSummary }) {
  return <Card className="portfolio-production" data-production={production.id} data-risk={production.on_time ? "normal" : "warning"}>
    <CardHeader>
      <div className="portfolio-production-title"><span className="portfolio-production-icon"><FilmIcon /></span><div><CardTitle>{production.title}</CardTitle><CardDescription>{production.deliverable}</CardDescription></div></div>
      <CardAction><Badge className="production-status" data-tone={production.on_time ? "healthy" : "warning"} variant="secondary">{production.on_time ? "On track" : "At risk"}</Badge></CardAction>
    </CardHeader>
    <CardContent><dl className="production-metrics">
      <div><dt>Deadline</dt><dd>{dateTime.format(new Date(production.deadline_at))}</dd></div>
      <div><dt>Allocation</dt><dd>{production.allocated_workers} workers</dd></div>
      <div><dt>Throughput</dt><dd>{production.throughput_fph.toLocaleString()} f/h</dd></div>
      <div><dt>Forecast cost</dt><dd>{money.format(production.cost_usd)}</dd></div>
      <div><dt>Delivery risk</dt><dd data-status={production.on_time ? "healthy" : "risk"}>{forecastLabel(production)}</dd></div>
    </dl></CardContent>
  </Card>
}

function AllocationRail({ portfolio }: { portfolio: PortfolioSnapshot }) {
  const nova = portfolio.resource_pool.allocations["project-nova"] ?? 0
  const silverline = portfolio.resource_pool.allocations.silverline ?? 0
  return <Card className="capacity-card">
    <CardHeader><div><CardTitle>Shared GPU capacity</CardTitle><CardDescription>Worker allocation across both productions</CardDescription></div><CardAction><strong>{portfolio.resource_pool.allocated_workers} <small>/ {portfolio.resource_pool.total_workers}</small></strong><span>workers allocated</span></CardAction></CardHeader>
    <CardContent>
      <div className="capacity-rail" role="img" aria-label={`${nova} workers assigned to Project Nova and ${silverline} assigned to Silverline`}>
        {Array.from({ length: portfolio.resource_pool.total_workers }, (_, index) => <i key={index} aria-hidden="true" className={index < nova ? "nova-allocation" : index < nova + silverline ? "silverline-allocation" : "unallocated-worker"} />)}
      </div>
      <div className="capacity-legend"><span><i className="nova-dot" />Project Nova <strong>{nova}</strong></span><span><i className="silverline-dot" />Silverline <strong>{silverline}</strong></span><span className="pool-total"><CpuIcon />{portfolio.resource_pool.total_workers} total</span></div>
      {portfolio.resource_pool.temporary_workers > 0 ? <p>{portfolio.resource_pool.base_workers} base workers + {portfolio.resource_pool.temporary_workers} temporary workers</p> : null}
    </CardContent>
  </Card>
}

export function PortfolioView({ portfolio, busy, onStartConflict, onApprove, onContinue }: PortfolioViewProps) {
  const [pendingOption, setPendingOption] = useState<AllocationOption | null>(null)
  const scenarioActive = portfolio.scenario === "deadline-conflict"
  const verified = Boolean(portfolio.verification?.verified)
  const observedVerification = verified && portfolio.agent_run?.phase === "verification" && portfolio.agent_run.ok
  const recommendation = portfolio.recommendation

  return <div className="portfolio-page">
    <header className="portfolio-heading"><div><h1>Production Portfolio</h1><p>Shared GPU resources. Nova: 12-hour planning window. Silverline: 24-hour planning window.</p></div>
      {!scenarioActive ? <Button disabled={busy} onClick={() => void onStartConflict()}><PlayIcon data-icon="inline-start" />Run deadline conflict</Button>
        : verified ? <Button disabled={busy || !observedVerification} onClick={() => void onContinue()}><FilmIcon data-icon="inline-start" />Continue demo</Button>
          : <Badge variant="secondary"><TimerResetIcon data-icon="inline-start" />Deadline conflict active</Badge>}
    </header>

    <AllocationRail portfolio={portfolio} />
    <section className="production-pair">{portfolio.productions.map(production => <ProductionPanel key={production.id} production={production} />)}</section>

    <Card className="portfolio-recommendation" data-state={verified ? "verified" : scenarioActive ? "decision" : "healthy"}>
      <CardHeader><div className="recommendation-title"><span>{observedVerification ? <CheckCircle2Icon /> : <SparklesIcon />}</span><div><CardTitle>{observedVerification ? "Allocation verified with Grafana" : verified ? "Allocation applied — awaiting live verification" : portfolio.agent_run?.ok ? "AI recommendation" : "Calculated allocation preview"}</CardTitle><CardDescription>{verified ? "Calculator forecast: both deliveries are on time and all workers are accounted for." : "Based on current workloads, capacity, and delivery deadlines."}</CardDescription></div></div></CardHeader>
      <CardContent>
        {verified ? <div className="verified-summary"><strong>The calculator projects both productions on time.</strong><p>{observedVerification ? portfolio.agent_run?.answer : "The allocation is complete. The agent must check fresh Grafana evidence before the demo continues."}</p></div>
          : recommendation ? <div className="recommendation-body"><div><strong>Move four workers from Silverline to Project Nova.</strong><p>{portfolio.agent_run?.answer || "The calculator projects both deliveries on time. The live agent is reviewing the evidence before recommending approval."}</p></div><Button disabled={busy || !portfolio.can_approve} onClick={() => setPendingOption(recommendation)}>Review and approve<ArrowRightIcon data-icon="inline-end" /></Button></div>
            : <div className="recommendation-body"><div><strong>Both productions are on track.</strong><p>The current 18 / 14 allocation protects both deliveries. Demo Mode introduces a throughput conflict without raising an incident.</p></div></div>}
      </CardContent>
    </Card>

    {scenarioActive ? <Card className="allocation-table-card">
      <CardHeader><div><CardTitle>Allocation comparison</CardTitle><CardDescription>Compare delivery forecasts and total cost before approving a change.</CardDescription></div></CardHeader>
      <CardContent><Table><TableHeader><TableRow><TableHead>Option</TableHead><TableHead>Nova</TableHead><TableHead>Silverline</TableHead><TableHead>Total cost</TableHead><TableHead>Risk</TableHead><TableHead>Decision</TableHead></TableRow></TableHeader>
        <TableBody>{portfolio.allocation_options.map(option => {
          const nova = impact(option, "project-nova")
          const silverline = impact(option, "silverline")
          return <TableRow key={option.id} data-recommended={option.recommended || undefined}>
            <TableCell><div className="option-name"><strong>{option.title}</strong>{option.recommended ? <span>Recommended</span> : null}</div></TableCell>
            <TableCell><strong>{nova.allocated_workers} workers · {nova.throughput_fph.toLocaleString()} f/h</strong><span data-status={nova.on_time ? "healthy" : "risk"}>{forecastLabel(nova)}</span></TableCell>
            <TableCell><strong>{silverline.allocated_workers} workers · {silverline.throughput_fph.toLocaleString()} f/h</strong><span data-status={silverline.on_time ? "healthy" : "risk"}>{forecastLabel(silverline)}</span></TableCell>
            <TableCell>{money.format(option.total_cost_usd)}</TableCell><TableCell><Badge className="production-status" data-tone={option.risk === "high" ? "critical" : option.risk === "medium" ? "warning" : "healthy"} variant="secondary">{option.risk}</Badge></TableCell>
            <TableCell>{option.recommended && !verified ? <Button variant="outline" size="sm" disabled={busy || !portfolio.can_approve} onClick={() => setPendingOption(option)}>Review</Button> : <span className="not-selected">—</span>}</TableCell>
          </TableRow>
        })}</TableBody>
      </Table></CardContent>
    </Card> : null}

    <AlertDialog open={Boolean(pendingOption)} onOpenChange={open => { if (!open) setPendingOption(null) }}>
      <AlertDialogContent className="allocation-approval">
        <AlertDialogHeader><AlertDialogTitle>Apply this allocation?</AlertDialogTitle><AlertDialogDescription>Transfer four workers from Silverline to Project Nova. This approval expires in five minutes and can be used once.</AlertDialogDescription></AlertDialogHeader>
        {pendingOption ? <div className="approval-impact"><h3>Effect on both productions</h3>{pendingOption.impacts.map(item => <div key={item.production_id}><span>{item.production_title}</span><strong>{item.allocated_workers} workers</strong><small>{item.throughput_fph.toLocaleString()} f/h · {forecastLabel(item)}</small></div>)}<p><CheckCircle2Icon />The shared pool remains at 32 workers.</p></div> : null}
        <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction disabled={busy} onClick={() => { if (pendingOption) void onApprove(pendingOption.id); setPendingOption(null) }}>Approve and apply</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
}
