# AI Production Director — Project Nova

Hackathon demo in which a GPU out-of-memory failure on trailer-critical Scene 87 is investigated through Grafana telemetry, translated into deterministic deadline and cost impact, recovered after human approval, and verified from fresh observability data.

## Architecture

`Render simulator → OpenTelemetry → Grafana/LGTM → Grafana MCP → Gemini ADK agent → deterministic impact calculator → human approval → recovery → verification`

The repository contains:

- A FastAPI simulation of Project Nova, two deliverables, 20 virtual GPU workers, 20 scenes, frame queues, costs, and trailer-critical scheduling.
- Deterministic Python ETA, throughput, delay, recovery-cost, and cost-avoided calculations.
- Correlated metrics, structured Scene 87 CUDA OOM logs, and traces exported to the local Grafana LGTM stack.
- Four explicit product states: `ON_TRACK`, `INVESTIGATING`, `DECISION_REQUIRED`, and `PRODUCTION_SAVED`.
- Single-use, expiring approval IDs and four distinct recovery actions.
- A Google ADK/Gemini agent with an optional Grafana MCP toolset and a clearly labeled local fallback.

## Run fully locally (no accounts or API keys)

Requirements: Docker Desktop with Docker Compose.

```bash
docker compose up --build
```

Open:

- Product interface: http://localhost:4173
- Grafana: http://localhost:3000 (`admin` / `admin`)
- Simulator API: http://localhost:8080/docs

If port 8080 is already occupied, start with `SIMULATOR_PORT=18080 docker compose up --build` and open the simulator API on port 18080. The dashboard continues to work through the internal Compose network.

The interface contains reset and GPU OOM controls. The complete story runs without cloud credentials using the clearly labeled `mock-fallback` investigation mode. All deadline, ETA, cost, approval, scheduling, telemetry, and verification behavior is real local code; only the natural-language investigation is scripted in this mode.

## Real Gemini + local Grafana MCP

The default agent profile runs every application component locally while authenticating Gemini through Vertex AI with your local Application Default Credentials. It does **not** deploy Cloud Run, Agent Engine, Artifact Registry, or Grafana Cloud resources. Grafana MCP runs as another local container and authenticates to local Grafana with development credentials.

Authenticate once and enable Vertex AI for the project:

```bash
gcloud auth application-default login
gcloud services enable aiplatform.googleapis.com --project=project-f5be723f-d87a-4652-b84
```

Run the ADK service with the optional Compose profile:

```bash
docker compose --profile agent up --build
```

Open the local ADK playground at http://localhost:8090 and select `production_director_agent`. Local Grafana MCP is available at http://localhost:8000/mcp. Its instructions enforce:

`Detect → Investigate → Correlate → Diagnose → Calculate → Recommend → Approve → Execute → Verify`

Grafana MCP must supply metric, Scene 87 log, and correlated trace evidence. The model cannot calculate delivery or cost estimates, invent recovery actions, or execute without a human-provided approval ID.

The product dashboard starts the real agent automatically after incident injection and continues the same ADK session after approval. To control cost, the demo exposes only three narrow, read-only Grafana MCP evidence tools, caps each model response at 900 tokens, and performs no background LLM polling. A normal demo uses two agent runs: investigation and post-approval recovery verification.

To exercise the story in the playground, reset/start the simulation from the product interface, inject the OOM, then ask: `Investigate Project Nova, calculate the delivery impact, and recommend recovery options. Do not execute anything without my approval.` When it requests approval, approve the chosen option in the product interface or provide the single-use approval ID explicitly.

### Local modes at a glance

| Mode | Command | External dependency |
|---|---|---|
| Complete product story with deterministic fallback | `docker compose up --build` | None |
| Gemini agent + local Grafana MCP | `docker compose --profile agent up --build` | Vertex AI API through local ADC |

To use Google AI Studio instead, set `GOOGLE_GENAI_USE_VERTEXAI=FALSE` and provide `GEMINI_API_KEY`.

## Main API

```text
POST /simulation/start
POST /simulation/reset
POST /simulation/incidents/gpu-oom
GET  /simulation/status
GET  /simulation/workers
GET  /production/context
GET  /impact
GET  /metrics

POST /approvals?action=prioritize-scenes
POST /recovery/add-workers
POST /recovery/prioritize-scenes
POST /recovery/restart-workers
POST /recovery/reduce-preview-quality
```

Recovery requests use this body:

```json
{"approval_id":"single-use-id","approved_by":"operator-name"}
```

The previous `/state`, `/reset`, `/scenario/gpu_oom`, `/diagnosis`, `/recovery-plans`, and approval endpoint remain as compatibility adapters for the dashboard.

## Three-minute demo

1. Show Project Nova in **Production on Track**.
2. Select **Inject GPU OOM**. Eight workers fail while rendering Scene 87.
3. Watch the investigation progress through metrics, logs, traces, and deterministic impact calculation.
4. At **Decision Required**, approve **Prioritize trailer scenes** ($17, medium risk).
5. Watch critical frames move ahead of full-film work and recovery progress reach 100%.
6. Finish on **Production Saved — Trailer delivery protected.** and show the Grafana evidence.

## Verification

```bash
python3 -m unittest discover -s simulator -p 'test_*.py' -v
cd operator-dashboard
npm ci
npm run build
npm run lint
```

## Cloud deployment boundary

The local vertical slice is complete. Actual Vertex AI Agent Engine, Cloud Run, Artifact Registry, Secret Manager, and Grafana Cloud deployment require the target Google Cloud and Grafana accounts; no infrastructure is created automatically by this repository.
