# ReelWarden — Protect every delivery

ReelWarden helps film producers answer: **Will we make our deadline, and should we act?** It combines shared production capacity, Google ADK with Gemini on Vertex AI, and live evidence from the official Grafana MCP server. A producer can compare delivery forecasts and costs, approve a plan, and inspect the evidence behind recovery.

**Hosted demo:** [Open ReelWarden](http://136.64.140.65/) · [Inspect Grafana evidence](http://136.64.140.65:3000/d/ai-production-director/reelwarden-c2b7-production-observability). This is a shared demo; resets and approvals affect all visitors.

The render farm and film workloads are simulated; Gemini inference and Grafana MCP calls run live. The studio portfolio can first resolve a delivery conflict between two productions, then investigate a production incident:

> Scene 87 is failing with GPU memory exhaustion. The trailer will miss delivery unless an operator approves recovery.

The app monitors a local render-farm simulator and turns incidents into a continuous, production-friendly conversation. During an active issue, the AI Production Director explains what is happening, assesses the trailer and schedule impact, recommends one recovery, and stays with the team through approval and verification. Technical evidence continues to be collected in the background. The agent checks fresh Grafana evidence, while calculated production data keeps the same friendly experience available with an explicit calculated mode if live AI is temporarily unavailable.

## What is included

- **Two-production portfolio**: Project Nova and Silverline share one conserved pool of 32 virtual GPU workers.
- **Deterministic allocation planner**: compares current allocation, a four-worker transfer, two temporary workers, and trailer prioritization with calculator-owned time, cost, risk, and throughput.
- **Project Nova incident simulator**: trailer and full-film deliverables, trailer-critical scenes, render queues, costs, retries, and deterministic ETA calculations.
- **Production incident catalogue**: render-capacity pressure, worker loss, queue surge, storage pressure, transfer latency, and corrupted assets, each tied to an explicit telemetry threshold and affected trailer scene.
- **Additional demo paths**: recovery verification failure with an AI-generated revised plan, and a non-mutating what-if calculator.
- **Local observability**: OpenTelemetry, Grafana, Prometheus, Loki, and Tempo through `grafana/otel-lgtm`.
- **AI-first incident workspace**: one production-scoped conversation spanning investigation, recommendation, approval, recovery, and verification.
- **Durable production memory**: SQLite stores incidents, agent runs, messages, decisions, and verified outcomes, including a seeded Silverline trailer case for relevant comparisons.
- **Approval protection**: every recovery action needs a valid, short-lived, single-use approval ID.
- **Portfolio approval protection**: the recommended four-worker transfer is approval-gated, auditable, single-use, and reversible only through a new approved decision.
- **Google ADK agent**: Gemini queries local Grafana MCP, selects one currently valid recovery action, and remains in the same incident-scoped session for follow-ups and reassessment.

## Architecture

```text
Nova + Silverline portfolio → deterministic allocation planner
              ↓                         ↓
        Human approval           shared-worker verification

Render simulator → OpenTelemetry → Local Grafana LGTM
                                      ↓
Operator dashboard ← deterministic impact calculator ← Grafana MCP ← Gemini ADK
        ↓                                                          ↓
Human approval → recovery API → simulator → fresh Grafana verification
```

## Quick start: fully local demo

This mode needs only Docker Desktop. It can run without Google Cloud, Gemini, or API keys; the dashboard starts without the optional agent. Live reviews report their connection status; an operator can explicitly choose calculated plans after a failed review. Calculated plans are never presented as live AI verification.

```bash
git clone https://github.com/trimax420/AI-Cult.git
cd AI-Cult
docker compose up --build
```

Open:

| Service | URL | Credentials |
|---|---|---|
| Product dashboard | http://localhost:4173 | None |
| Grafana | http://localhost:3000 | `admin` / `admin` |
| Simulator API docs | http://localhost:8080/docs | None |

If port `8080` is unavailable:

```bash
SIMULATOR_PORT=18080 docker compose up --build
```

The dashboard continues to use the Compose network automatically; only the simulator API moves to `http://localhost:18080/docs`.

Stop the stack with:

```bash
docker compose down
```

To remove local Grafana data as well:

```bash
docker compose down -v
```

## Run the three-minute demo

1. Open http://localhost:4173 and show the healthy **Production Portfolio**.
2. Select **Run deadline conflict**. Nova’s trailer workload increases without creating an incident.
3. Compare all four deterministic allocation options. The four-worker transfer makes Nova on time while Silverline remains on time.
4. Select **Review and approve**, inspect the effect on both productions, then approve the short-lived decision.
5. Confirm all 32 workers are conserved and both delivery forecasts verify.
6. Select **Continue demo** to raise Nova’s render-memory incident and enter the existing incident workspace.
7. Review the Grafana-grounded recovery recommendation, approve it, and watch the AI confirm the trailer is protected.

Useful alternate paths:

- **Six threshold-driven cases** cover render memory, worker availability, queue demand, storage, transfer latency, and asset integrity.
- **Simulate failed recovery** appears at decision time and makes the next approved action return to a visible failed-verification decision state.
- After a failed recovery, the ADK agent excludes the failed action and generates a revised recommendation in the same conversation.
- **Production what-if lab** compares worker count, deadline, preview quality, and scene prioritization without changing the live simulator.

## Real Gemini + local Grafana MCP

This keeps the application and observability stack local. Gemini is the only external dependency when enabled; nothing is deployed to Cloud Run, Agent Engine, Artifact Registry, Secret Manager, or Grafana Cloud.

### 1. Authenticate locally with Google Cloud

Use a Google Cloud project with Vertex AI enabled:

```bash
gcloud auth application-default login
gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID
```

Create `.env` from the example and set your project values:

```bash
cp .env.example .env
```

```dotenv
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=global
GEMINI_MODEL=gemini-3.8-flash
```

### 2. Start the agent profile

```bash
docker compose --profile agent up --build
```

Additional local endpoints:

| Service | URL |
|---|---|
| ADK playground | http://localhost:8090 |
| Grafana MCP | http://localhost:8000/mcp |

When an incident is raised, the simulator creates one durable investigation for that incident and starts the ADK agent in the background—even when no dashboard is open. The agent queries Grafana MCP for:

1. Prometheus throughput, queue, worker, memory, storage, transfer-latency, and asset-error evidence.
2. The matching affected-scene event from Loki.
3. The matching incident trace from Tempo.

The simulator recalculates current cost, schedule, and risk. The ADK agent authors the visible condition, trailer impact, recommendation rationale, next step, conversation update, and selected action as a guarded structured briefing. Cost, risk, and delivery timing remain calculator-owned and are validated separately. The agent does not execute anything: only a human can create and consume an approval through the recovery API. If a live review fails, the UI shows a retry action. Calculated mode must be explicitly selected, and observed verification is never fabricated.

To control Gemini spend, the full portfolio demo uses four focused runs: portfolio investigation, allocation verification, incident investigation, and recovery verification. Follow-up questions and failed-recovery reassessment add runs. There is no background LLM polling.

### Google AI Studio alternative

If you prefer an API key instead of Vertex AI, set the following in `.env`:

```dotenv
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GEMINI_API_KEY=your_key_here
```


### Current runtime and verification

The verified model target is `gemini-3.8-flash`, using Google ADK 2.8.0 and google-genai 2.22.0. `GOOGLE_CLOUD_LOCATION=global` controls model routing independently of the Cloud Run deployment region. No other model is silently substituted.

On macOS/Linux, Compose reads ADC from `$HOME/.config/gcloud/application_default_credentials.json`. Set `GOOGLE_ADC_PATH` to an absolute file path on Windows or for a custom location. The file must already exist; Compose will not create a directory in its place.

The studio owns 32 base worker identities: Nova starts with 18 and Silverline with 14. Allocation changes synchronize Nova's incident engine. Approved temporary workers have distinct `TEMP-` identities and are reported separately. Portfolio delivery forecasts cover 12/24-hour planning windows; the incident workspace covers the immediate trailer window.

Grafana queries validate each required series and correlate Loki/Tempo with an event trace. Evidence reads retry ingestion delays for up to 30 seconds. Recovery first passes simulator condition and delivery checks; a separate ADK run then verifies fresh observations. The SQLite `live_runs` table preserves phase, raw diagnostics, tool outcomes, and model usage. Reset invalidates unfinished callbacks while retaining history.

Readiness and explicit recovery controls:

```bash
curl http://localhost:8080/readiness
curl http://localhost:8080/evidence-context
curl -X POST http://localhost:8080/agent/retry
curl -X POST http://localhost:8080/agent/calculated-mode
```

`/readiness` checks ADK connectivity and reports the latest live evidence result without calling Gemini. Set `GRAFANA_PUBLIC_URL` to a judge-accessible Grafana dashboard URL for hosted use.

Before recording, wait for the portfolio recommendation, approve the transfer, wait for live allocation verification, then continue into the incident. The same conversation remains available after recovery. Use **Simulate failed recovery** before approving an incident action to exercise reassessment.

For deployment preparation, `./deploy/deploy-cloud-run.sh --dry-run` renders the manifest after checking required environment variables; it does not deploy. The hosted demo remains a single-instance simulation with ephemeral state and no authentication or tenant isolation.

## Host on a Google Compute Engine VM

The VM deployment runs the same Docker Compose services together. Use Debian 12, an `e2-medium` (4 GB RAM), a 30 GB balanced boot disk, and the 2 GB swap configured by `deploy/setup-vm.sh`. No GPU is required: the worker pool is simulated and model inference runs on Vertex AI.

Attach a dedicated service account with `roles/aiplatform.user`, enable the Compute Engine and Vertex AI APIs, and use the `cloud-platform` access scope. The VM override removes the local credential-file mount so Application Default Credentials use the attached VM identity.

Use an ephemeral external IP. Permit TCP 80 for the dashboard and TCP 3000 for read-only Grafana on this VM's network tag. The deployment does not create backup schedules, snapshots, an Ops Agent, Cloud Logging export, a load balancer, or Grafana Cloud resources. Grafana's local telemetry is required by the application. VM, disk, external IPv4, network usage, and Vertex AI calls still have their normal usage charges.

Run `deploy/setup-vm.sh` once as root on the fresh VM. Place the repository source in `/opt/reelwarden`, then run:

```bash
sudo bash /opt/reelwarden/deploy/start-vm-app.sh
```

This generates a root-readable `.env` on the VM, obtains project/IP information from metadata, creates random Grafana and MCP credentials, and builds the agent profile. It uses `docker-compose.yml` plus `docker-compose.vm.yml`. Public Grafana access has the Viewer role; the ADK playground and MCP endpoint remain private. No service-account key needs to be downloaded.

Check the deployment:

```bash
curl http://localhost:8080/readiness
curl http://localhost:3000/api/health
sudo docker compose -f /opt/reelwarden/docker-compose.yml \
  -f /opt/reelwarden/docker-compose.vm.yml --profile agent ps -a
```

The dashboard is `http://VM_IP/` and Grafana is `http://VM_IP:3000/`. These are HTTP demo endpoints; enabling a firewall port alone does not configure HTTPS. An ephemeral address may change after a VM stop/start; update `GRAFANA_PUBLIC_URL` and the shared project URL if that happens. Docker volumes preserve local state on the VM's disk. There are no automatic backups.

## API guide

The interactive API reference is available at `/docs` on the simulator port.

### Simulation controls

```bash
curl -X POST http://localhost:8080/simulation/start
curl -X POST http://localhost:8080/simulation/reset
curl http://localhost:8080/simulation/incidents/catalog
curl http://localhost:8080/simulation/thresholds
curl -X POST http://localhost:8080/simulation/incidents/gpu-oom
curl -X POST http://localhost:8080/simulation/incidents/storage-pressure
curl http://localhost:8080/simulation/status
curl http://localhost:8080/simulation/workers
```

### Portfolio orchestration

```bash
curl http://localhost:8080/portfolio
curl -X POST http://localhost:8080/portfolio/scenarios/deadline-conflict
curl -X POST 'http://localhost:8080/portfolio/approvals?option_id=transfer-four-workers'
curl -X POST http://localhost:8080/portfolio/allocations/transfer-four-workers \
  -H 'Content-Type: application/json' \
  -d '{"approval_id":"APPROVAL_ID","approved_by":"demo-operator"}'
curl http://localhost:8080/portfolio/verification
```

Set `ENABLE_PORTFOLIO_DEMO=false` before the Docker build to return the hosted dashboard to the proven single-production landing view.

### Evidence and planning

```bash
curl http://localhost:8080/impact
curl http://localhost:8080/recovery-plans
curl http://localhost:8080/audit-log
curl http://localhost:8080/verification/comparison
```

### AI Production Director and production memory

```bash
curl http://localhost:8080/productions/project-nova/assistant
curl http://localhost:8080/productions/project-nova/incidents/INCIDENT_ID
curl 'http://localhost:8080/productions/project-nova/cases/similar?incident_id=INCIDENT_ID'
curl -X POST http://localhost:8080/productions/project-nova/assistant/messages \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is the safest way to protect the trailer delivery?","incident_id":"INCIDENT_ID"}'
```

The existing `/copilot/chat` route remains available as a compatibility wrapper.

During an active incident, the dashboard requests only messages linked to that incident. Every follow-up
is sent to the same production-and-incident-scoped Google ADK session, so an earlier incident's discussion
cannot appear in the current workspace. The backend supplies the current calculated schedule, cost, risk,
available actions, and verified prior case as authoritative context. The backend parses final ADK responses before storing display text. Raw JSON, tool payloads, and internal IDs are excluded from conversation. Costs and quantities are checked against calculator facts and observed tool results; invalid responses receive one formatting repair attempt, then a visible retry state.

Example what-if calculation:

```bash
curl -X POST http://localhost:8080/impact/what-if \
  -H 'Content-Type: application/json' \
  -d '{"workers_added":2,"deadline_minutes":90,"quality_percent":82,"prioritize_critical":true}'
```

### Human-approved recovery

First request a single-use approval ID:

```bash
curl -X POST 'http://localhost:8080/approvals?action=prioritize-scenes'
```

Then execute only the matching allowlisted recovery action:

```bash
curl -X POST http://localhost:8080/recovery/prioritize-scenes \
  -H 'Content-Type: application/json' \
  -d '{"approval_id":"APPROVAL_ID","approved_by":"demo-operator"}'
```

Available actions are:

- `add-workers`
- `prioritize-scenes`
- `restart-workers`
- `reduce-preview-quality`
- `rebalance-queue`
- `release-storage`
- `reroute-transfers`
- `restore-asset`

`take-no-action` is only a comparison option and is never executable.

## Tests and quality checks

```bash
PYTHONPYCACHEPREFIX=/tmp/ai-cult-pycache \
  python3 -m unittest discover -s simulator -p 'test_*.py' -v

cd operator-dashboard
npm ci
npm run build
npm run lint
```

The Python tests cover Project Nova scheduling, all six threshold-driven incident scenarios, incident-scoped conversation isolation, ADK session reuse and action parsing, presentation safety, approval expiry/replay protection, what-if isolation, failed-action exclusion, recovery reassessment, and verification.

Run the ADK boundary and evidence-retry tests inside the pinned agent image:

```bash
docker compose --profile agent exec production-director-agent python -m unittest production_director_agent.test_runtime -v
```

With the live local stack running, `python3 scripts/verify-live-demo.py` resets the simulation and exercises portfolio allocation, all six incidents, fresh Grafana verification, and failed recovery with a new approval. It uses the configured Gemini project. Each phase must report `live-agent`; there is no calculated substitute in this acceptance run.

## Cloud Run packaging

The deployment template at `deploy/cloudrun-service.yaml.template` describes one multi-container Cloud Run service: Nginx dashboard ingress on 8080, simulator on 8081, ADK agent on 8090, and the official Grafana MCP server on 8000. Containers communicate over localhost. Vertex AI uses the Cloud Run service account; Grafana and MCP credentials are Secret Manager references. The SQLite ledger is mounted on a 64 MiB in-memory volume, so demo state intentionally resets when the instance is replaced.

The template enables instance-based CPU allocation so simulation ticks, telemetry export, and explicitly started ADK reviews continue after an HTTP response returns. This bills CPU for the instance lifetime; see [Cloud Run billing settings](https://docs.cloud.google.com/run/docs/configuring/billing-settings). The template limits the service to one instance.

Build separate deployment images locally with `sh deploy/build-cloud-run-images.sh`. It produces `ai-cult-simulator:cloudrun`, `ai-cult-agent:cloudrun`, and `ai-cult-dashboard:cloudrun` using `linux/amd64`, as required by the [Cloud Run container contract](https://docs.cloud.google.com/run/docs/container-contract). This does not push images or deploy the service, and preserves the native local Compose images. Tagging and publishing these images to your Artifact Registry repository is a separate release step.

Build and push the three repository images (`dashboard`, `simulator`, and `agent`), create the referenced secrets, export the variables validated by `deploy/deploy-cloud-run.sh`, then run:

```bash
./deploy/deploy-cloud-run.sh
```

Grafana datasource UIDs are configured with `GRAFANA_PROMETHEUS_DATASOURCE_UID`, `GRAFANA_LOKI_DATASOURCE_UID`, and `GRAFANA_TEMPO_DATASOURCE_UID` so local and Grafana Cloud stacks can differ without code changes. The Cloud Run simulator uses OTLP HTTP/protobuf: set `GRAFANA_CLOUD_OTLP_ENDPOINT` to the Grafana Cloud base endpoint ending in `/otlp` (the exporter adds `/v1/traces`, `/v1/metrics`, and `/v1/logs`). The `grafana-otlp-headers` secret contains the complete OpenTelemetry exporter header value required by the chosen Grafana Cloud OTLP endpoint.

## Important boundaries

- The default local mode remains usable without a Google account, but the full agent demonstration requires the ADK profile.
- Google Cloud provides Gemini/Vertex AI in agent mode and Compute Engine for the optional VM deployment.
- This is a hackathon simulator: no real compute workers, tenant isolation, user authentication, or production infrastructure mutations are performed.
- Do not commit `.env`, API keys, or Google credentials.

## Submission readiness

Intended track: **Grafana Labs**. The runtime uses Google ADK + Gemini on Vertex AI and the official `grafana/mcp-grafana` server. The simulator generates synthetic film-production telemetry; it does not operate a real render farm. Simulator verification and Grafana observations are separate evidence sources.

For judging, run the **agent profile with Vertex AI enabled**. The account-free continuity path does not demonstrate Gemini/Google Cloud runtime use. Google AI Studio alone does not establish the required Google Cloud use.

Before submission:

- Publish a judge-accessible project URL, with working backend, Vertex AI, and MCP connectivity.
- Make the repository public and push the root MIT `LICENSE` with all source and setup instructions. Confirm GitHub detects it.
- Record the functioning app in English (or with English subtitles), at most three minutes, and publish on YouTube or Vimeo.
- Select Grafana Labs and complete Devpost, including features, technologies, data sources, and learnings.
- Confirm eligibility, team membership (maximum four), original work during the contest, and rights to included assets.
- Ask the organizers whether their AI-tooling restriction includes development-time coding assistants. Do not assume runtime-only scope.

An English 2:56 demo video has been prepared separately. Video assets are excluded from this repository. The public video URL and completed Devpost form must be supplied by the entrant; verify repository visibility in a signed-out browser before submission.

Deadline: September 9, 2026, 2:00 PM PDT (September 10, 2:30 AM IST).

Sources: [Official rules](https://agentic-cinema.devpost.com/rules), [Grafana track requirements](https://agentic-cinema.devpost.com/details/grafana-resources).

## License

MIT; see [LICENSE](LICENSE). Third-party dependencies retain their respective licenses.
