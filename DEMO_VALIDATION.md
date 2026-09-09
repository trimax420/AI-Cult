# Local demo validation — 9 September 2026

The demo uses Gemini 3.8 Flash through Google ADK and Vertex AI's global endpoint. The configured Google Cloud credentials completed text, tool-calling, multi-turn, portfolio, incident, reassessment, and verification runs. No alternate model or calculated fallback was used for the live acceptance checks.

## Verified behavior

| Check | Result |
| --- | --- |
| Portfolio planning and four-worker transfer | Live Gemini recommendation; Grafana metrics, logs, and traces verified the 22 / 10 allocation |
| GPU memory incident | Approved recovery and fresh Grafana verification passed |
| Worker loss | Approved recovery and fresh Grafana verification passed |
| Queue surge | Initial attempt remained late; a different plan received a new approval and passed verification |
| Storage pressure | Approved recovery and fresh Grafana verification passed |
| Network latency | Approved recovery and fresh Grafana verification passed |
| Corrupted asset | Approved recovery and fresh Grafana verification passed |
| Forced recovery failure | Separate reassessment selected a different action; new approval and verification passed |
| Base and temporary capacity | 32 base identities remain conserved; Nova starts with 18, transfers to 22, and temporary identities are tracked separately |
| Presentation boundary | Bare, fenced, tagged, malformed, truncated, mixed tool/text, and historical envelopes are parsed or rejected without displaying raw JSON |
| Retry boundaries | Successful evidence is reused for the same event; failed reads retry for up to 30 seconds; the model cannot repeatedly poll completed tools |
| State protection | Reset invalidates late completions; duplicate executions and stale approval tokens are rejected |
| Optional agent | Dashboard starts without agent/backend DNS; outage is visible, draft text survives, and no fallback answer is returned |
| Deployment preparation | Native local images and separate AMD64 release images built; four-container Cloud Run YAML and HTTP/protobuf telemetry endpoints validated offline |

52 simulator/gateway tests and 5 pinned-runtime ADK/evidence tests passed. Dashboard build and lint pass with three existing Fast Refresh warnings and a bundle-size advisory. Chromium browser checks at 1440 × 1000 and 390 × 844 covered pre-incident chat, portfolio cost comparisons, approval, fresh verification, incident chat, alternative-plan expansion, recovery, post-recovery evidence explanations, what-if calculations, audit, and reset. The tested mobile layout had no horizontal page overflow and no browser runtime errors. Additional mobile tests confirmed that selecting an alternative opens an approval dialog without executing, cancellation preserves state, failed progress never displays a successful outcome, and a second approved recovery verifies successfully.

## Reproduce

```sh
docker compose --profile agent up -d --build
python3 -m unittest discover -s simulator -p 'test_*.py' -v
docker compose --profile agent exec production-director-agent python -m unittest production_director_agent.test_runtime -v
python3 scripts/verify-live-demo.py
```

The live script resets the local simulation and invokes the configured Gemini project. Each review and verification must return live evidence; a missing service cannot become a successful fallback.

## Scope and remaining release work

Rendering and production capacity are simulated. Grafana receives actual telemetry from that simulator, and Gemini reads it through the official Grafana MCP server. Portfolio forecasts use 12-hour / 24-hour planning windows; immediate incident forecasts use the trailer deadline. Calculator verification and observed Grafana verification remain distinct.

Cloud Run preparation was a local dry run, not a deployment or a check of production IAM, secrets, or Grafana Cloud access. The template uses ephemeral simulation state and a single instance. Public hosting, repository visibility, video, and Devpost submission remain separate release tasks. This report establishes local technical behavior, not hackathon eligibility or a judging outcome.
