# AI Production Director — Project Nova

AI Production Director is a hackathon demo for operating a simulated film render farm. It turns observability evidence into a production decision:

> Scene 87 is failing with GPU memory exhaustion. The trailer will miss delivery unless an operator approves recovery.

The app monitors a local render-farm simulator and turns incidents into a continuous, production-friendly conversation. During an active issue, the AI Production Director explains what is happening, assesses the trailer and schedule impact, recommends one recovery, and stays with the team through approval and verification. Technical evidence continues to be collected in the background. The agent checks fresh Grafana evidence, while calculated production data keeps the same friendly experience available if the live AI is temporarily unavailable.

## What is included

- **Project Nova simulator**: 20 virtual GPU workers, trailer and full-film deliverables, trailer-critical scenes, render queues, costs, retries, and deterministic ETA calculations.
- **Production incident catalogue**: render-capacity pressure, worker loss, queue surge, storage pressure, transfer latency, and corrupted assets, each tied to an explicit telemetry threshold and affected trailer scene.
- **Additional demo paths**: recovery verification failure with an AI-generated revised plan, and a non-mutating what-if calculator.
- **Local observability**: OpenTelemetry, Grafana, Prometheus, Loki, and Tempo through `grafana/otel-lgtm`.
- **AI-first incident workspace**: one production-scoped conversation spanning investigation, recommendation, approval, recovery, and verification.
- **Durable production memory**: SQLite stores incidents, agent runs, messages, decisions, and verified outcomes, including a seeded Silverline trailer case for relevant comparisons.
- **Approval protection**: every recovery action needs a valid, short-lived, single-use approval ID.
- **Google ADK agent**: Gemini queries local Grafana MCP, selects one currently valid recovery action, and remains in the same incident-scoped session for follow-ups and reassessment.

## Architecture

```text
Render simulator → OpenTelemetry → Local Grafana LGTM
                                      ↓
Operator dashboard ← deterministic impact calculator ← Grafana MCP ← Gemini ADK
        ↓                                                          ↓
Human approval → recovery API → simulator → fresh Grafana verification
```

## Quick start: fully local demo

This mode needs only Docker Desktop. It can run without Google Cloud, Gemini, or API keys; if the live agent is unavailable, the production team still receives a friendly calculated assessment without infrastructure errors being exposed.

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

1. Open http://localhost:4173 and show **Production on Track**.
2. Choose one of the six production failure scenarios. Each option shows the telemetry threshold that raises it.
3. The simulator changes the matching production telemetry and moves the affected trailer delivery behind schedule.
4. The AI workspace opens automatically with a plain-language assessment, production impact, one recommended recovery, and a relevant earlier case when one exists.
5. Ask follow-up questions about schedule, cost, risk, alternatives, affected scenes, or previous productions. The conversation remains available throughout the incident.
6. Select **Review and approve**, then **Approve and start recovery**. The approval is audited and consumed once.
7. Watch the AI monitor the recovery and confirm when the trailer is protected.

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
GOOGLE_CLOUD_LOCATION=asia-south1
GEMINI_MODEL=gemini-2.5-flash
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

The simulator recalculates current cost, schedule, and risk. The ADK agent authors the visible condition, trailer impact, recommendation rationale, next step, conversation update, and selected action as a guarded structured briefing. Cost, risk, and delivery timing remain calculator-owned and are validated separately. The agent does not execute anything: only a human can create and consume an approval through the recovery API. If the agent is temporarily unavailable, persisted production data keeps the workflow useful without exposing a technical error or fallback label.

To control Gemini spend, one normal demo uses two focused agent runs: investigation and post-recovery verification. There is no background LLM polling.

### Google AI Studio alternative

If you prefer an API key instead of Vertex AI, set the following in `.env`:

```dotenv
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GEMINI_API_KEY=your_key_here
```

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
available actions, and verified prior case as authoritative context. Responses containing internal monitoring
language or figures that conflict with the current calculation are replaced by a production-friendly assessment.

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

## Important boundaries

- The default local mode remains usable without a Google account, but the full agent demonstration requires the ADK profile.
- Google Cloud is used only for Gemini/Vertex AI in the optional agent mode.
- This is a hackathon simulator: no real compute workers, tenant isolation, user authentication, or production infrastructure mutations are performed.
- Do not commit `.env`, API keys, or Google credentials.

## Submission readiness — checked September 5, 2026

Intended track: **Grafana Labs**. The runtime uses Google ADK + Gemini on Vertex AI and the official `grafana/mcp-grafana` server. The simulator generates synthetic film-production telemetry; it does not operate a real render farm. Simulator verification and Grafana observations are separate evidence sources.

For judging, run the **agent profile with Vertex AI enabled**. The account-free continuity path does not demonstrate Gemini/Google Cloud runtime use. Google AI Studio alone does not establish the required Google Cloud use.

Before submission:

- Publish a judge-accessible project URL, with working backend, Vertex AI, and MCP connectivity.
- Make the repository public and push the root MIT `LICENSE` with all source and setup instructions. Confirm GitHub detects it.
- Record the functioning app in English (or with English subtitles), at most three minutes, and publish on YouTube or Vimeo.
- Select Grafana Labs and complete Devpost, including features, technologies, data sources, and learnings.
- Confirm eligibility, team membership (maximum four), original work during the contest, and rights to included assets.
- Ask the organizers whether their AI-tooling restriction includes development-time coding assistants. Do not assume runtime-only scope.

The hosted URL, video, and Devpost form are not yet prepared. The configured GitHub URL returned 404 to an unauthenticated check; public visibility still needs verification. Local commit history begins August 26, 2026, which is within the contest period but does not independently prove originality.

Deadline: September 9, 2026, 2:00 PM PDT (September 10, 2:30 AM IST).

Sources: [Official rules](https://agentic-cinema.devpost.com/rules), [Grafana track requirements](https://agentic-cinema.devpost.com/details/grafana-resources).

## License

MIT; see [LICENSE](LICENSE). Third-party dependencies retain their respective licenses.
