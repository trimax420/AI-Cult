import { useState } from "react"
import {
  AlertTriangleIcon,
  ArrowRightIcon,
  BotIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  CircleDollarSignIcon,
  Clock3Icon,
  FilmIcon,
  HistoryIcon,
  LoaderCircleIcon,
  MessageCircleMoreIcon,
  SendIcon,
  ShieldCheckIcon,
  SparklesIcon,
} from "lucide-react"

import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import type { AssistantSnapshot, RecoveryPlan, RenderState } from "@/lib/types"

type Props = {
  assistant: AssistantSnapshot
  state: RenderState
  busy: boolean
  onApprove: (action: string) => Promise<void>
  onAsk: (message: string) => Promise<void>
}

const prompts = ["What is the schedule impact?", "Why this plan?", "What are the risks?", "Have we seen this before?"]

function PlanFacts({ plan }: { plan: RecoveryPlan }) {
  return <dl className="ai-plan-facts">
    <div><dt><Clock3Icon />Delivery result</dt><dd>{plan.deadline_result}</dd></div>
    <div><dt><CircleDollarSignIcon />Added cost</dt><dd>${plan.estimated_added_cost_usd}</dd></div>
    <div><dt><ShieldCheckIcon />Risk</dt><dd>{plan.risk}</dd></div>
  </dl>
}

export function AiIncidentWorkspace({ assistant, state, busy, onApprove, onAsk }: Props) {
  const [prompt, setPrompt] = useState("")
  const [sending, setSending] = useState(false)
  const [approvalOpen, setApprovalOpen] = useState(false)
  const briefing = assistant.briefing
  const recommended = assistant.plans.find(plan => plan.recommended) ?? null
  const alternatives = assistant.plans.filter(plan => !plan.recommended)

  async function send(value = prompt) {
    const clean = value.trim()
    if (!clean || sending) return
    setPrompt("")
    setSending(true)
    try { await onAsk(clean) } finally { setSending(false) }
  }

  if (!briefing) return <div className="ai-incident-loading"><LoaderCircleIcon className="animate-spin" /><span>The AI Production Director is preparing the production update.</span></div>

  return <section className="ai-incident-layout">
    <main className="ai-director-stage">
      <header className="ai-director-heading" aria-live="polite">
        <div className="ai-presence"><BotIcon /></div>
        <div><span>AI Production Director</span><h1>{briefing.status_line}</h1><p>{briefing.next_step}</p></div>
        <Badge variant={briefing.phase === "reassessment" ? "destructive" : "secondary"}>{briefing.phase}</Badge>
      </header>

      <div className="ai-assessment-grid">
        <section className="ai-assessment-copy">
          <article><div className="ai-topic-icon warning"><AlertTriangleIcon /></div><div><h2>What’s happening</h2><p>{briefing.condition}</p></div></article>
          <article><div className="ai-topic-icon"><FilmIcon /></div><div><h2>Impact on the trailer</h2><p>{briefing.impact}</p></div></article>
        </section>

        {recommended ? <section className="ai-recommendation">
          <div className="ai-recommendation-label"><SparklesIcon />Recommended action</div>
          <h2>{recommended.title}</h2>
          <p>{recommended.rationale}</p>
          <PlanFacts plan={recommended} />
          <AlertDialog open={approvalOpen} onOpenChange={setApprovalOpen}>
            <AlertDialogTrigger render={<Button className="ai-approve" disabled={busy || state.recovery_progress > 0} />}><CheckCircle2Icon data-icon="inline-start" />Review and approve<ArrowRightIcon data-icon="inline-end" /></AlertDialogTrigger>
            <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Approve {recommended.title}?</AlertDialogTitle><AlertDialogDescription>This action starts immediately after approval. It adds ${recommended.estimated_added_cost_usd} and the current delivery forecast is {recommended.deadline_result.toLowerCase()}.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Keep discussing</AlertDialogCancel><AlertDialogAction disabled={busy} onClick={() => { setApprovalOpen(false); void onApprove(recommended.plan_id) }}>Approve recovery</AlertDialogAction></AlertDialogFooter></AlertDialogContent>
          </AlertDialog>
        </section> : <section className="ai-recommendation pending"><LoaderCircleIcon className="animate-spin" /><h2>I’m preparing the safest recovery options.</h2></section>}
      </div>

      <details className="ai-disclosure"><summary>Alternative plans ({alternatives.length})<ChevronDownIcon /></summary><div className="ai-alternatives">{alternatives.map(plan => <article key={plan.plan_id}><div><h3>{plan.title}</h3><p>{plan.rationale}</p></div><PlanFacts plan={plan} />{plan.requires_approval ? <Button variant="outline" disabled={busy || state.recovery_progress > 0} onClick={() => void onApprove(plan.plan_id)}>Choose this plan</Button> : null}</article>)}</div></details>

      <section className="ai-conversation" aria-label="Conversation with AI Production Director">
        <div className="ai-conversation-title"><MessageCircleMoreIcon /><div><h2>Discuss the production issue</h2><p>Ask naturally, as you would in a production and IT review.</p></div></div>
        <div className="ai-messages" aria-live="polite">{assistant.messages.map(message => <article key={message.id} data-role={message.role}><span>{message.role === "assistant" ? "AI Production Director" : "You"}</span><p>{message.body}</p></article>)}</div>
        {sending ? <div className="ai-thinking" role="status"><LoaderCircleIcon className="animate-spin" />Reviewing the production context…</div> : null}
        <div className="ai-prompt-row">{prompts.map(item => <Button key={item} variant="outline" size="sm" disabled={sending} onClick={() => void send(item)}>{item}</Button>)}</div>
        <form className="ai-compose" onSubmit={event => { event.preventDefault(); void send() }}><input value={prompt} onChange={event => setPrompt(event.target.value)} placeholder="Ask about the schedule, scenes, cost, or options…" aria-label="Ask the AI Production Director" /><Button type="submit" size="icon" disabled={sending || !prompt.trim()} aria-label="Send message"><SendIcon /></Button></form>
      </section>
    </main>

    <aside className="ai-support-rail">
      {briefing.similar_case ? <section className="ai-support-card previous-case"><div className="ai-support-title"><HistoryIcon /><span>Worked before</span></div><h2>{briefing.similar_case.deliverable_title}</h2><p>{briefing.similar_case.summary}</p><strong><CheckCircle2Icon />{briefing.similar_case.outcome}</strong></section> : null}
      <details className="ai-support-card production-details"><summary><FilmIcon /><span>Production details</span><ChevronDownIcon /></summary><ul>{briefing.facts.map(fact => <li key={fact}>{fact}</li>)}</ul></details>
      <section className="ai-support-card progress-card"><div className="ai-support-title"><Clock3Icon /><span>Recovery progress</span></div><strong>{state.recovery_progress > 0 ? `${Math.round(state.recovery_progress)}% complete` : assistant.run?.status === "ready" ? "Recommendation ready" : "Assessing and planning"}</strong><Progress value={state.recovery_progress > 0 ? state.recovery_progress : assistant.run?.status === "ready" ? 38 : 18} /><ol><li data-complete>Issue detected</li><li data-complete={assistant.run?.status === "ready"}>Assessment and plan</li><li data-complete={state.recovery_progress > 0}>Action approval</li><li data-complete={state.recovery_progress >= 100}>Back to normal</li></ol></section>
    </aside>
  </section>
}
