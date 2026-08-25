# AI Production Director

Groundwork for an observability-driven agent that translates render-farm failures into production deadline impact and human-approved recovery options.

## What is included

- Grafana's local LGTM stack: Grafana, Prometheus, Loki, Tempo, Pyroscope, and an OpenTelemetry Collector.
- A FastAPI render-farm simulator emitting correlated OpenTelemetry metrics, logs, and traces.
- A broad incident library spanning GPU, workers, scheduler, storage, network, assets, dependencies, licensing, cost, deadline risk, and recovery.
- Domain telemetry for queue depth, GPU workers, memory pressure, render duration, predicted delay, retries, recovery progress, and added cost.

## Run locally

Requirements: Docker Desktop with Docker Compose.

```powershell
docker compose up --build
```

Open:

- Grafana: http://localhost:3000 (`admin` / `admin`)
- Simulator state: http://localhost:8080/state
- Simulator API docs: http://localhost:8080/docs
- Operator dashboard: http://localhost:4173

## Three-minute demo sequence

Start from the healthy baseline:

```powershell
Invoke-RestMethod -Method Post http://localhost:8080/scenario/healthy
```

Trigger the GPU memory incident:

```powershell
Invoke-RestMethod -Method Post http://localhost:8080/scenario/gpu_oom
```

The expected signals are rising `render.queue.depth`, `render.scene.duration`, `render.gpu.memory.utilization`, retries and logs containing `CUDA out of memory`. The `render.predicted.delay` gauge converts degradation into minutes late.

Approve the recommended recovery plan:

```powershell
Invoke-RestMethod -Method Post http://localhost:8080/scenario/recovering
```

The simulator drains the queue and returns the delivery forecast inside the deadline. Reset the demo at any time:

```powershell
Invoke-RestMethod -Method Post http://localhost:8080/reset
```

## Available conditions

Open `http://localhost:8080/scenarios` for the machine-readable catalog. Trigger any entry with:

```powershell
Invoke-RestMethod -Method Post http://localhost:8080/scenario/<condition>
```

Conditions: `healthy`, `queue_surge`, `gpu_oom`, `gpu_overheating`, `worker_loss`,
`render_stalled`, `storage_slow`, `storage_full`, `network_latency`, `asset_corruption`,
`dependency_down`, `license_failure`, `cost_overrun`, `deadline_risk`, `recovering`, and
`recovered`.

## Grafana alerts

Provision the six baseline incident rules with:

```powershell
.\grafana\alerting\provision-alerts.ps1
```

The rules cover deadline risk, GPU memory exhaustion, worker capacity loss, storage
exhaustion, asset corruption, and critical dependency outages. They are grouped under
**AI Production Alerts / Render Farm Incidents** in Grafana Alerting.

## Diagnosis and human-approved recovery

The simulator exposes a first decision workflow:

- `GET /diagnosis` — root cause, severity, evidence, confidence, and deadline impact.
- `GET /telemetry-history` — recent GPU-memory and queue samples for operator charts.
- `GET /recovery-plans` — ranked scenario-specific options with time, cost, and risk.
- `POST /recovery-plans/{plan_id}/approve?approved_by=<name>` — approve and execute a plan.
- `GET /audit-log` — immutable-in-process record of scenario and approval events.

Example:

```powershell
Invoke-RestMethod -Method Post http://localhost:8080/scenario/gpu_oom
Invoke-RestMethod http://localhost:8080/diagnosis
Invoke-RestMethod http://localhost:8080/recovery-plans
Invoke-RestMethod -Method Post "http://localhost:8080/recovery-plans/restart_gpu_workers/approve?approved_by=govind"
```

## Useful telemetry

| Signal | Meaning |
| --- | --- |
| `render.queue.depth` | Jobs waiting for GPU capacity |
| `render.gpu.workers.active` | Healthy workers in pool B |
| `render.gpu.memory.utilization` | GPU memory pressure percentage |
| `render.scene.duration` | Current average scene render time |
| `render.predicted.delay` | Minutes early (negative) or late (positive) |
| `render.retries` | Scene retries, tagged with failure type |
| `render.recovery.progress` | Execution progress for the approved plan |
| `render.cost.added` | Incremental cost of recovery |
| `render.storage.utilization` | Storage pressure percentage |
| `render.network.latency` | Render-network latency in milliseconds |
| `render.asset.error.rate` | Percentage of assets failing validation |
| `render.cost.estimated` | Current estimated production cost |
| `render.condition` | Active scenario with severity and component labels |

## Next foundation steps

1. Provision a Grafana dashboard and alert rules around the telemetry above.
2. Connect Grafana MCP and implement the diagnosis/recovery agent.
3. Add a recovery-plan API with human approval and an audit log.
4. Instrument agent MCP calls, latency, traces, and token usage.
