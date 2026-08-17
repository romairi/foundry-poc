# Gemini external agent (Foundry traces + optional APIM)

## What each file does

| File | Role |
|------|------|
| `agent.py` | Core: Gemini call + OpenTelemetry (`invoke_agent` span) |
| `app.py` | HTTP API for deploy: `GET /health`, `POST /v1/chat` |
| `run_local.py` | Local CLI: 4 test prompts in a row |
| `register_external_agent.py` | One-time Foundry registration (not the runtime) |
| `.env` | Secrets (not in git) |
| `Dockerfile` / `docker-compose.yml` | Container for deploy |

Flow:

```text
Client or APIM
    → POST /v1/chat  (app.py)
    → run_external_agent()  (agent.py)
    → Gemini
    → traces → Application Insights → Foundry Traces
```

## Local (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# CLI test prompts
python run_local.py

# HTTP API
uvicorn app:app --host 0.0.0.0 --port 8080
curl http://127.0.0.1:8080/health
curl -X POST http://127.0.0.1:8080/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Say hello in one short sentence."}'
```

## Docker

```bash
docker compose up --build
```

Then the same `curl` commands on port 8080.

`.env` is passed into the container via `env_file`. Do not bake secrets into the image.

## Deploy (next)

1. Build/push the image (ACR) and run it (Container Apps / App Service).
2. Put the public HTTPS URL into APIM **Web service URL**.
3. APIM suffix: `gemini-governance-agent`.
4. Client: `https://tamir-ai-gateway.azure-api.net/gemini-governance-agent/v1/chat` + `api-key`.

Until the container has a public URL, APIM cannot call this agent. Local `python run_local.py` is enough for Foundry Traces.
