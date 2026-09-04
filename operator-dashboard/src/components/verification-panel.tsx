import{ArrowRightIcon,CheckCircle2Icon,XCircleIcon}from"lucide-react"
import{Card,CardContent,CardHeader,CardTitle}from"@/components/ui/card"
import type{VerificationComparison}from"@/lib/types"

export function VerificationPanel({comparison}:{comparison:VerificationComparison}){
 if(!comparison.available||!comparison.before||!comparison.after)return null
 const rows=[
  ["Throughput",`${comparison.before.throughput_fph} f/h`,`${comparison.after.throughput_fph} f/h`],
  ["Healthy workers",String(comparison.before.healthy_workers),String(comparison.after.healthy_workers)],
  ["Critical queue",String(comparison.before.critical_queue),String(comparison.after.critical_queue)],
  ["Projected delay",`${Math.round(comparison.before.delay_minutes)} min`,`${Math.round(comparison.after.delay_minutes)} min`],
 ]
 return <Card className="verification-card"><CardHeader><CardTitle>{comparison.passed?<CheckCircle2Icon/>:<XCircleIcon/>}{comparison.passed?"Grafana verified recovery":"Verification failed"}</CardTitle></CardHeader><CardContent>{rows.map(([label,before,after])=><div className="comparison-row" key={label}><span>{label}</span><strong>{before}</strong><ArrowRightIcon/><strong>{after}</strong></div>)}</CardContent></Card>
}
