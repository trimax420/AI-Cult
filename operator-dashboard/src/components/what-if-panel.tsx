import{useState}from"react"
import{FlaskConicalIcon}from"lucide-react"
import{Button}from"@/components/ui/button"
import{Card,CardContent,CardHeader,CardTitle}from"@/components/ui/card"
import type{WhatIfResult}from"@/lib/types"

export function WhatIfPanel({calculate}:{calculate:(input:{workers_added:number;deadline_minutes:number;quality_percent:number;prioritize_critical:boolean})=>Promise<WhatIfResult>}){
 const[workers,setWorkers]=useState(0),[deadline,setDeadline]=useState(90),[quality,setQuality]=useState(100),[prioritize,setPrioritize]=useState(false),[result,setResult]=useState<WhatIfResult|null>(null),[loading,setLoading]=useState(false)
 async function run(){setLoading(true);try{setResult(await calculate({workers_added:workers,deadline_minutes:deadline,quality_percent:quality,prioritize_critical:prioritize}))}finally{setLoading(false)}}
 return <Card className="what-if-card"><CardHeader><CardTitle><FlaskConicalIcon/>Production what-if lab</CardTitle></CardHeader><CardContent><div className="what-if-controls"><label>Extra workers<input type="number" min="0" max="10" value={workers} onChange={event=>setWorkers(Number(event.target.value))}/></label><label>Minutes to deadline<input type="number" min="15" value={deadline} onChange={event=>setDeadline(Number(event.target.value))}/></label><label>Preview quality<select value={quality} onChange={event=>setQuality(Number(event.target.value))}><option value="100">100%</option><option value="82">82%</option><option value="65">65%</option></select></label><label className="what-if-check"><input type="checkbox" checked={prioritize} onChange={event=>setPrioritize(event.target.checked)}/>Prioritize trailer</label><Button onClick={()=>void run()} disabled={loading}>{loading?"Calculating…":"Compare scenario"}</Button></div>{result?<div className="what-if-result"><strong>{result.deadline_result}</strong><span>{result.projected_throughput_fph} f/h</span><span>{result.projected_completion_minutes} min</span><span>+${result.added_cost_usd}</span></div>:<p>Change constraints without mutating the live production.</p>}</CardContent></Card>
}
