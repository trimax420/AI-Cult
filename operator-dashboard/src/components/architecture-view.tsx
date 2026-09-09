import { useState } from "react"
import { ArrowDownIcon, ExternalLinkIcon } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import type { Readiness } from "@/lib/types"

const steps = [
  { name: "Observe the production", system: "Render simulator → OpenTelemetry → Grafana", detail: "The render farm emits metrics, logs, and traces. Prometheus measures throughput and worker health; Loki records scene and recovery events; Tempo connects each event to its trace. The render infrastructure in this prototype is simulated.", files: "simulator/app.py · grafana/dashboards/ai-production-director.json" },
  { name: "Investigate with context", system: "Google ADK + Gemini on Vertex AI ↔ official Grafana MCP", detail: "A decision starts a focused agent run. Gemini requests metrics, matching logs, and the event trace through the official Grafana MCP server. It combines observed evidence with the affected production and scene. Missing evidence produces a retry state, never a fabricated success.", files: "production_director_agent/agent.py · production_director_agent/grafana_tools.py" },
  { name: "Compare delivery options", system: "Deterministic calculators → grounded recommendation", detail: "Calculators own the completion time, throughput, cost, and risk of each available plan. Gemini explains the tradeoff and selects a valid option. The portfolio conserves 32 base worker identities across Nova and Silverline; temporary capacity is tracked separately.", files: "simulator/portfolio.py · simulator/domain.py · simulator/director.py" },
  { name: "Approve and execute", system: "Producer → single-use approval → recovery API", detail: "Only a human approval can execute an allowlisted action. Approval expires and is revalidated against the current scenario. What-if calculations do not modify production. SQLite preserves decisions, messages, execution, and agent runs.", files: "simulator/app.py · simulator/live_runs.py" },
  { name: "Verify the outcome", system: "Simulator checks → fresh Grafana evidence → ADK verification", detail: "Simulator completion is followed by a separate, execution-linked agent verification using fresh observations. A failed recovery requires reassessment, a different valid recommendation, and a new approval. Observed recovery and calculated delivery forecasts stay distinct.", files: "simulator/director.py · production_director_agent/agent.py" },
]

export function ArchitectureView({ readiness }: { readiness: Readiness | null }) {
  const [active, setActive] = useState(0)
  return <section className="architecture-view">
    <header className="tab-heading"><div><span>Inside ReelWarden</span><h1>Protect the delivery. Prove the recovery.</h1><p>For studio producers and render operations: turn a technical incident into an informed production decision.</p></div></header>
    <div className="architecture-layout"><div className="architecture-flow" aria-label="Architecture stages">
      {steps.map((step, index) => <div key={step.name}><Button variant={active === index ? "secondary" : "outline"} className="architecture-node" aria-pressed={active === index} onClick={() => setActive(index)}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{step.name}</strong><small>{step.system}</small></div></Button>{index < steps.length - 1 ? <ArrowDownIcon className="architecture-arrow" aria-hidden="true" /> : null}</div>)}
    </div><Card className="architecture-detail"><CardHeader><CardDescription>How this stage works</CardDescription><CardTitle>{steps[active].name}</CardTitle></CardHeader><CardContent><p>{steps[active].detail}</p><div className="architecture-runtime"><strong>Current connection</strong><p>{readiness?.agent_connected ? "Agent connected" : "Agent unavailable"} · {readiness?.model ?? "Checking model"} · {readiness?.model_location ?? "Checking location"}</p><p>Model inference: Google Cloud Vertex AI. This local demo runs the dashboard, API, and Grafana in Docker.</p></div><details><summary>Runtime source files</summary><code>{steps[active].files}</code></details><Button variant="outline" render={<a href={readiness?.grafana_url ?? "http://localhost:3000"} target="_blank" rel="noreferrer" />}><ExternalLinkIcon data-icon="inline-start" />Inspect Grafana dashboard</Button></CardContent></Card></div>
    <footer className="architecture-benefit"><strong>One workflow, from delivery risk to verified recovery.</strong><p>Compare the effect on both productions, preserve human control, and keep the evidence with every decision. Real render-farm adapters and public hosting are the next steps.</p></footer>
  </section>
}
