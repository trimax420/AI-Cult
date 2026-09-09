import { useEffect, useRef, useState } from "react"
import { BotIcon, SendIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { AssistantSnapshot } from "@/lib/types"

type Props = { assistant: AssistantSnapshot; onAsk: (message: string) => Promise<void>; onRetry: () => Promise<void>; onCalculated: () => Promise<void> }
export function DirectorConversation({ assistant, onAsk, onRetry, onCalculated }: Props) {
  const [prompt, setPrompt] = useState("")
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const messagesRef = useRef<HTMLDivElement>(null)
  const lastMessageId = assistant.messages.at(-1)?.id
  useEffect(() => {
    const list = messagesRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [lastMessageId])
  const run = assistant.run
  async function send(value = prompt) {
    if (!value.trim() || sending) return
    setSending(true); setError(null)
    try { await onAsk(value.trim()); setPrompt("") }
    catch (e) { setPrompt(value); setError(e instanceof Error ? e.message : "Please retry your question.") }
    finally { setSending(false) }
  }
  async function action(fn: () => Promise<void>) {
    setError(null)
    try { await fn() } catch (e) { setError(e instanceof Error ? e.message : "Please retry.") }
  }
  const waiting = run?.status === "running"
  return <section className="director-conversation ai-support-card" aria-label="Conversation with ReelWarden">
    <div className="ai-conversation-title"><BotIcon /><div><h2>Discuss the production</h2><p>{run?.model ?? "Gemini 3.8 Flash"} · Google ADK · Grafana MCP</p></div></div>
    {waiting ? <p role="status">{run.phase === "verification" ? "Checking the recovery against fresh Grafana evidence…" : "Reviewing live evidence and comparing the production options…"}</p> : null}
    {run?.status === "unavailable" || run?.status === "interrupted" ? <div role="status"><p>{run.error || "The live review was interrupted."}</p><Button onClick={() => void action(onRetry)}>Retry live review</Button> <Button variant="outline" onClick={() => void action(onCalculated)}>Use calculated plans</Button></div> : null}
    {assistant.calculated_mode ? <p role="status">Calculated mode selected. These plans have not been verified by the live agent.</p> : null}
    {run?.evidence?.length ? <details className="director-evidence"><summary>Grafana evidence · {run.evidence.filter(e => e.ok).length}/{run.evidence.length} checks available</summary>{run.evidence.map(e => <article key={e.tool}><strong>{e.source} · {e.ok ? "Observed" : "Unavailable"}</strong><p>{e.error || (e.observed_at ? `Checked ${new Date(e.observed_at).toLocaleTimeString()}` : "Awaiting evidence")}</p><code>{e.query}</code>{e.trace_id ? <small>Correlated trace: {e.trace_id}</small> : null}</article>)}</details> : null}
    <div ref={messagesRef} className="ai-messages" aria-live="polite">{assistant.messages.map(m => <article key={m.id} data-role={m.role}><span>{m.role === "assistant" ? "ReelWarden" : "You"}</span><p>{m.body}</p></article>)}</div>
    {sending ? <p role="status">Preparing your production answer…</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    <div className="ai-prompt-row">{["What is the schedule impact?", "Why this plan?", "Compare the alternatives", "What did Grafana observe?"].map(q => <Button key={q} variant="outline" size="sm" disabled={sending || waiting} onClick={() => void send(q)}>{q}</Button>)}</div>
    <form className="ai-compose" onSubmit={e => { e.preventDefault(); void send() }}><input aria-label="Ask the ReelWarden" value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="Ask about evidence, delivery, costs, or the next decision…" /><Button aria-label="Send message" type="submit" size="icon" disabled={sending || waiting || !prompt.trim()}><SendIcon /></Button></form>
  </section>
}
