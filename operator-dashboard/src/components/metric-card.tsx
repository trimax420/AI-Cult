import type{LucideIcon}from"lucide-react"
import{Card,CardContent,CardHeader,CardTitle}from"@/components/ui/card"
export function MetricCard({title,value,helper,icon:Icon,tone="normal"}:{title:string;value:string;helper:string;icon:LucideIcon;tone?:"normal"|"warning"|"critical"}){return <Card size="sm" className="metric-card" data-tone={tone}><CardHeader><CardTitle><Icon/>{title}</CardTitle></CardHeader><CardContent><strong>{value}</strong><span>{helper}</span></CardContent></Card>}
