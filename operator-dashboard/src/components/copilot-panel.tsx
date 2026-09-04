import { useState } from "react"
import { BotIcon, SendIcon, SparklesIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { CopilotBriefing, CopilotReply, RecoveryPlan } from "@/lib/types"

type Message = { role: "assistant" | "operator"; text: string; plan?: RecoveryPlan }

export function CopilotPanel({ briefing, ask, onApprove, busy }: { briefing: CopilotBriefing; ask: (message: string) => Promise<CopilotReply>; onApprove: (action: string) => Promise<void>; busy: boolean }) {
  const [messages, setMessages] = useState<Message[]>([])
  const [prompt, setPrompt] = useState("")
  const [sending, setSending] = useState(false)

  async function send(message = prompt) {
    const clean = message.trim()
    if (!clean || sending) return
    setPrompt("")
    setSending(true)
    setMessages(current => [...current, { role: "operator", text: clean }])
    try {
      const reply = await ask(clean)
      const plan = reply.suggested_action ? reply.plans.find(candidate => candidate.plan_id === reply.suggested_action) : undefined
      setMessages(current => [...current, { role: "assistant", text: reply.answer, plan }])
    } catch {
      setMessages(current => [...current, { role: "assistant", text: "I could not reach the project context. Refresh telemetry and try again." }])
    } finally { setSending(false) }
  }

  return <Card className="copilot-panel"><CardHeader><div><span className="eyebrow">Production copilot</span><CardTitle><BotIcon /> Ask Project Nova</CardTitle></div><Badge variant="secondary">{briefing.source === "gemini-grafana-mcp" ? "Gemini + Grafana" : "Live context"}</Badge></CardHeader><CardContent>
    <section className="copilot-brief"><strong>{briefing.headline}</strong><p>{briefing.summary}</p><ul>{briefing.evidence.map(item => <li key={item}>{item}</li>)}</ul><small>{briefing.next_step}</small></section>
    <div className="copilot-messages" aria-live="polite">{messages.map((message, index) => <article key={`${message.role}-${index}`} data-role={message.role}><span>{message.role === "assistant" ? "Copilot" : "You"}</span><p>{message.text}</p>{message.plan ? <Button size="sm" disabled={busy} onClick={() => void onApprove(message.plan!.plan_id)}><SparklesIcon data-icon="inline-start" />Prepare {message.plan.title}</Button> : null}</article>)}</div>
    <div className="copilot-prompts"><Button variant="outline" size="sm" onClick={() => void send("Why is the trailer at risk?")}>Why is it at risk?</Button>{briefing.status === "decision_required" ? <Button variant="outline" size="sm" onClick={() => void send("Recommend the best recovery option")}>Recommend a fix</Button> : <Button variant="outline" size="sm" onClick={() => void send("What is the trailer status?")}>Trailer status</Button>}</div>
    <form className="copilot-compose" onSubmit={event => { event.preventDefault(); void send() }}><input value={prompt} onChange={event => setPrompt(event.target.value)} placeholder="Ask about Scene 87, costs, ETA, or recovery…" aria-label="Ask the production copilot" /><Button type="submit" size="icon" disabled={sending || !prompt.trim()} aria-label="Send message"><SendIcon /></Button></form>
  </CardContent></Card>
}
