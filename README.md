# AI Production Director — Project Nova

AI Production Director is a hackathon demo for operating a simulated film render farm. It turns observability evidence into a production decision:

> Scene 87 is failing with GPU memory exhaustion. The trailer will miss delivery unless an operator approves recovery.

The app monitors a local render-farm simulator, investigates metrics, logs, and traces in Grafana, calculates deadline and cost impact with deterministic Python code, requires human approval for recovery, and verifies the outcome in the simulator. The optional agent separately checks fresh Grafana evidence.

## What is included

- **Project Nova simulator**: 20 virtual GPU workers, trailer and full-film deliverables, trailer-critical scenes, render queues, costs, retries, and deterministic ETA calculations.
- **Primary incident**: GPU OOM on trailer-critical **Scene 87**.
- **Additional demo paths**: corrupted asset on Scene 94, recovery verification failure, and a non-mutating what-if calculator.
- **Local observability**: OpenTelemetry, Grafana, Prometheus, Loki, and Tempo through `grafana/otel-lgtm`.
- **Operator dashboard**: `ON_TRACK → INVESTIGATING → DECISION_REQUIRED → PRODUCTION_SAVED`.
- **Approval protection**: every recovery action needs a valid, short-lived, single-use approval ID.
- **Optional real agent**: Google ADK + Gemini queries local Grafana MCP for Prometheus, Loki, and Tempo evidence.

## Architecture

```text
Render simulator → OpenTelemetry → Local Grafana LGTM
                                      ↓
Operator dashboard ← deterministic impact calculator ← Grafana MCP ← Gemini ADK
        ↓                                                          ↓
Human approval → recovery API → simulator → fresh Grafana verification
```

## Quick start: fully local demo

This mode needs only Docker Desktop. It uses the clearly labelled `mock-fallback` investigation path, so it does not require Google Cloud, Gemini, or API keys.

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
2. Click **Demo Mode** or **GPU OOM**.
3. The simulator makes Scene 87 fail, drops healthy capacity, raises GPU-memory pressure, and moves the trailer ETA behind schedule.
4. Watch the investigation show metric, log, trace, correlation, and deterministic impact steps.
5. At **Decision Required**, review the live recovery projections. Each option's ETA and cost are recalculated from the current queue and worker capacity. With ADK enabled, Gemini ranks the allowlisted options from Grafana evidence and is labelled **Gemini recommended**; otherwise the deterministic calculator provides a clearly labelled fallback.
6. Click **Approve option**, then **Approve and execute**. The approval is audited and consumed once.
7. Watch recovery progress and the before/after verification card.
8. Finish on **Production Saved — Trailer delivery protected.**

Useful alternate paths:

- **Corrupt Asset** injects a checksum failure for `nova_city.exr` on Scene 94.
- **Simulate failed recovery** appears at decision time and makes the next approved action return to a visible failed-verification decision state.
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

When you inject **GPU OOM** in the product dashboard, the dashboard starts the ADK agent. The agent queries Grafana MCP for:

1. Prometheus throughput, queue, and GPU-memory evidence.
2. The matching Scene 87 CUDA OOM or Scene 94 checksum-failure log from Loki.
3. The matching `incident.gpu_oom` or `incident.corrupted_asset` trace from Tempo.

It then ranks the live, deterministic recovery projections and returns one allowlisted recommendation to the dashboard. The agent gets costs and ETAs from deterministic tools. Its registered tools are read-only: only the dashboard can create and consume an operator approval through the recovery API. The dashboard always executes an approved action through the recovery API first, so an unavailable agent cannot block the human-approved recovery; ADK then performs post-recovery verification when available.

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
curl -X POST http://localhost:8080/simulation/incidents/gpu-oom
curl -X POST http://localhost:8080/simulation/incidents/corrupted-asset
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

The Python tests cover Project Nova scheduling, deterministic impact calculations, Scene 87 and Scene 94 telemetry behavior, approval expiry/replay protection, prioritization, what-if isolation, recovery failure, and verification.

## Important boundaries

- The default local mode works without a Google account.
- Google Cloud is used only for Gemini/Vertex AI in the optional agent mode.
- This is a hackathon simulator: no real compute workers, tenant isolation, user authentication, or production infrastructure mutations are performed.
- Do not commit `.env`, API keys, or Google credentials.

## Submission readiness — checked September 5, 2026

Intended track: **Grafana Labs**. The runtime uses Google ADK + Gemini on Vertex AI and the official `grafana/mcp-grafana` server. The simulator generates synthetic film-production telemetry; it does not operate a real render farm. Simulator verification and Grafana observations are separate evidence sources.

For judging, run the **agent profile with Vertex AI enabled**. The account-free `mock-fallback` mode is a development convenience and does not demonstrate Gemini/Google Cloud runtime use. Google AI Studio alone does not establish the required Google Cloud use.

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
