import { useCallback, useEffect, useRef, useState } from "react"

import type { AssistantSnapshot, AuditEvent, CopilotBriefing, Diagnosis, IncidentScenario, Investigation, PortfolioSnapshot, RecoveryPlan, Readiness, RenderState, TelemetryPoint, VerificationComparison, WhatIfResult } from "@/lib/types"

const API_ROOT = import.meta.env.VITE_SIMULATOR_API_ROOT || "/api/simulator"
const PRODUCTION_ID = "project-nova"
export const PORTFOLIO_ENABLED = import.meta.env.VITE_ENABLE_PORTFOLIO_DEMO !== "false"

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(typeof detail?.detail === "string" ? detail.detail : `Request failed with ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function useOperations() {
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null)
  const [plans, setPlans] = useState<RecoveryPlan[]>([])
  const [audit, setAudit] = useState<AuditEvent[]>([])
  const [state, setState] = useState<RenderState | null>(null)
  const [telemetry, setTelemetry] = useState<TelemetryPoint[]>([])
  const [investigation, setInvestigation] = useState<Investigation | null>(null)
  const [verification, setVerification] = useState<VerificationComparison>({ available: false })
  const [briefing, setBriefing] = useState<CopilotBriefing | null>(null)
  const [assistant, setAssistant] = useState<AssistantSnapshot | null>(null)
  const [scenarios, setScenarios] = useState<IncidentScenario[]>([])
  const [portfolio, setPortfolio] = useState<PortfolioSnapshot | null>(null)
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const inFlight = useRef(false)

  const refresh = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const [d, p, a, s, h, i, v, b, ai, scenarioCatalog, portfolioSnapshot, readinessSnapshot] = await Promise.all([
        request<Diagnosis>("/diagnosis"),
        request<{ plans: RecoveryPlan[] }>("/recovery-plans"),
        request<{ events: AuditEvent[] }>("/audit-log?limit=25"),
        request<RenderState>("/simulation/status"),
        request<{ points: Array<{ timestamp: string; gpu_memory_utilization: number; queue_depth: number }> }>("/telemetry-history?limit=72"),
        request<Investigation>("/agent/investigation"),
        request<VerificationComparison>("/verification/comparison"),
        request<CopilotBriefing>("/copilot/briefing"),
        request<AssistantSnapshot>(`/productions/${PRODUCTION_ID}/assistant`),
        request<{ scenarios: IncidentScenario[] }>("/simulation/incidents/catalog"),
        PORTFOLIO_ENABLED ? request<PortfolioSnapshot>("/portfolio") : Promise.resolve(null),
        request<Readiness>("/readiness").catch(() => null),
      ])
      setReadiness(readinessSnapshot)
      setDiagnosis(d)
      setPlans(p.plans)
      setAudit(a.events)
      setState(s)
      setInvestigation(i)
      setVerification(v)
      setBriefing(b)
      setAssistant(ai)
      setScenarios(scenarioCatalog.scenarios)
      setPortfolio(portfolioSnapshot)
      setTelemetry(h.points.map(point => ({ time: new Date(point.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), memory: point.gpu_memory_utilization, queue: point.queue_depth })))
      setError(null)
    } catch {
      setError("The production update is temporarily unavailable. I’ll keep trying in the background.")
    } finally { inFlight.current = false }
  }, [])

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0)
    const timer = window.setInterval(() => void refresh(), 2000)
    return () => { window.clearTimeout(initial); window.clearInterval(timer) }
  }, [refresh])

  const act = useCallback(async (path: string) => {
    setBusy(true)
    try { await request(path, { method: "POST" }); await refresh() } finally { setBusy(false) }
  }, [refresh])
  const reset = useCallback(() => act("/simulation/reset"), [act])
  const inject = useCallback(async (kind = "gpu-oom") => {
    setBusy(true)
    try { await request(`/simulation/incidents/${kind}`, { method: "POST" }); await refresh() } finally { setBusy(false) }
  }, [refresh])
  const approve = useCallback(async (action: string) => {
    setBusy(true)
    try {
      const approval = await request<{ id: string }>(`/approvals?action=${encodeURIComponent(action)}`, { method: "POST" })
      const execution = await request<{ execution_id: string }>(`/recovery/${action}`, { method: "POST", body: JSON.stringify({ approval_id: approval.id, approved_by: "operator-dashboard" }) })
      await refresh()
      return { execution_id: execution.execution_id }
    } finally { setBusy(false) }
  }, [refresh])
  const askCopilot = useCallback(async (message: string) => {
    await request(`/productions/${PRODUCTION_ID}/assistant/messages`, { method: "POST", body: JSON.stringify({ message, incident_id: assistant?.incident?.id }) })
    await refresh()
  }, [assistant?.incident?.id, refresh])
  const simulateFailure = useCallback(() => request<{ armed: boolean }>("/simulation/recovery/fail-next", { method: "POST" }).then(() => undefined), [])
  const whatIf = useCallback((input: { workers_added: number; deadline_minutes: number; quality_percent: number; prioritize_critical: boolean }) => request<WhatIfResult>("/impact/what-if", { method: "POST", body: JSON.stringify(input) }), [])
  const demo = useCallback(async () => { await reset(); await new Promise(resolve => setTimeout(resolve, 700)); await inject("gpu-oom") }, [inject, reset])
  const startDeadlineConflict = useCallback(() => act("/portfolio/scenarios/deadline-conflict"), [act])
  const approveAllocation = useCallback(async (optionId: string) => {
    setBusy(true)
    try {
      const approval = await request<{ id: string }>(`/portfolio/approvals?option_id=${encodeURIComponent(optionId)}`, { method: "POST" })
      await request(`/portfolio/allocations/${encodeURIComponent(optionId)}`, { method: "POST", body: JSON.stringify({ approval_id: approval.id, approved_by: "operator-dashboard" }) })
      await refresh()
    } finally { setBusy(false) }
  }, [refresh])
  const continueDemo = useCallback(() => inject("gpu-oom"), [inject])

  return { readiness, retryAgent: () => act("/agent/retry"), calculatedMode: () => act("/agent/calculated-mode"), assistant, scenarios, portfolio, agentError: null, diagnosis, plans, audit, state, telemetry, investigation, verification, briefing, error, busy, refresh, approve, approveAllocation, startDeadlineConflict, continueDemo, askCopilot, start: () => act("/simulation/start"), reset, inject, simulateFailure, whatIf, demo }
}
