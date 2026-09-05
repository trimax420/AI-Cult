import { useState } from "react"
import { BotIcon, SendIcon, SparklesIcon } from "lucide-react"

import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { CopilotBriefing, CopilotReply, RecoveryPlan } from "@/lib/types"

type Message = { role: "assistant" | "operator"; text: string; plan?: RecoveryPlan }

export function CopilotPanel({ briefing, ask, onApprove, busy }: { briefing: CopilotBriefing; ask: (message: string) => Promise<CopilotReply>; onApprove: (action: string) => Promise<void>; busy: boolean }) {
  const [messages, setMessages] = useState<Message[]>([])
  const [prompt, setPrompt] = useState("")
  const [sending, setSending] = useState(false)
  const [openApproval, setOpenApproval] = useState<number | null>(null)

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
    <div className="copilot-messages" aria-live="polite">{messages.map((message, index) => <article key={`${message.role}-${index}`} data-role={message.role}><span>{message.role === "assistant" ? "Copilot" : "You"}</span><p>{message.text}</p>{message.plan ? <AlertDialog open={openApproval === index} onOpenChange={open => setOpenApproval(open ? index : null)}><AlertDialogTrigger render={<Button size="sm" disabled={busy || briefing.status !== "decision_required"} />}><SparklesIcon data-icon="inline-start" />Review {message.plan.title}</AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Approve {message.plan.title}?</AlertDialogTitle><AlertDialogDescription>Execute this recovery with a single-use approval. Added cost: ${message.plan.estimated_added_cost_usd}. {message.plan.rationale}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction disabled={busy} onClick={() => { setOpenApproval(null); void onApprove(message.plan!.plan_id) }}>Approve and execute</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog> : null}</article>)}</div>
    {sending ? <p role="status" className="text-sm text-muted-foreground mt-3">Checking production evidence…</p> : null}<div className="copilot-prompts"><Button variant="outline" size="sm" onClick={() => void send("Why is the trailer at risk?")}>Why is it at risk?</Button>{briefing.status === "decision_required" ? <Button variant="outline" size="sm" onClick={() => void send("Recommend the best recovery option")}>Recommend a fix</Button> : <Button variant="outline" size="sm" onClick={() => void send("What is the trailer status?")}>Trailer status</Button>}</div>
    <form className="copilot-compose" onSubmit={event => { event.preventDefault(); void send() }}><input value={prompt} onChange={event => setPrompt(event.target.value)} placeholder="Ask about Scene 87, costs, ETA, or recovery…" aria-label="Ask the production copilot" /><Button type="submit" size="icon" disabled={sending || !prompt.trim()} aria-label="Send message"><SendIcon /></Button></form>
  </CardContent></Card>
}
