# Learning Coach

An Expo (React Native + TypeScript) app for web, iOS, and Android, a Next.js web client, and a FastAPI service that researches a learner's topic: it maps what the topic involves and finds public pages that teach each part.

## Structure

- `mobile/` — Universal Expo Router client (web, iOS, Android)
- `backend/` — FastAPI API, Deep Agents runtime, and LiteLLM gateway integration

## Run the self-hosted stack

For local development, copy `.env.example` to `.env` and
`backend/.env.example` to `backend/.env`, then replace every placeholder before
running:

```bash
docker compose up --build
```

This starts the self-hosted data services, FastAPI, and the web client behind
Caddy at `http://localhost:8080`; the API is available beneath `/api`.

## Start the backend

Browser-backed research requires Node.js 24 or newer. Install the pinned
agent-browser package and Chrome for Testing from the repository root:

```powershell
.\scripts\setup-browser-tools.ps1
```

On Linux or macOS:

```bash
sh ./scripts/setup-browser-tools.sh
```

The scripts use `npm ci`, so the browser version comes from the committed
lockfile. They install Chrome for Testing and run agent-browser's offline
diagnostics. The Docker image performs the same setup automatically. Put the
NVIDIA API key only in the repository-root `.env`; LiteLLM owns that credential,
and the API receives only its LiteLLM master key.

```bash
cd backend
uv sync --group dev
uv run uvicorn app.main:app --reload
```

The backend is managed with `uv`. Its first hexagonal vertical slice is
`GET /health`: the FastAPI adapter resolves an application service through
Dishka, and that service calls a replaceable outbound health port.

For local PostgreSQL, run `docker compose -f docker-compose.yml up -d` from `backend/` and set `DATABASE_URL=postgresql+asyncpg://learning_coach:learning_coach@127.0.0.1:5432/learning_coach` in `backend/.env`. Run `alembic upgrade head` to create or update the schema. For deployment, use the Supabase Session Pooler connection string in `DATABASE_URL`, then run that same migration command in the deployment environment. Supabase Auth owns email/password credentials; the backend verifies each Supabase access token and creates a matching application profile on first use.

The API docs are available at `http://127.0.0.1:8000/docs`. Research
always uses Deep Agents with public browser research. The stable `agent-model`
LiteLLM alias currently resolves to NVIDIA's `z-ai/glm-5.3-flash` endpoint.

Local development may use SQLite for application data, but authentication still
requires Supabase. Both frontends call the backend auth endpoints; Supabase keys
and authentication requests remain behind the API.

Copy `backend/.env.example` to `backend/.env`, set the Supabase values, and
replace the encryption key before deployment. Install the pinned browser tool
with `npm install`, run `npm run browser:install`, and verify it with
`npm run browser:doctor`. The application creates a session-scoped LiteLLM key
for every Deep Agent run; provider calls never bypass the gateway.

## Start the mobile app

Install Node.js 20+ first, then:

```bash
cd mobile
npm install
npx expo start
```

Press `w` for the web app, `i` for iOS simulator, or `a` for Android emulator. Expo Go can be used for a physical device.

Copy `mobile/.env.example` to `mobile/.env`. Set the Supabase Project URL and publishable key; for an iOS/Android device, set `EXPO_PUBLIC_API_URL` to your computer's LAN address, for example `http://192.168.1.10:8000`.

## Agent runtime

`POST /learning-runs` starts research in the background and returns `202 {id}`;
poll `GET /learning-runs/{id}/status`, then read `GET /learning-runs/{id}`.

1. **Research query planner** derives coverage requirements (what the topic involves), focused discovery queries, and optional canonical seeds.
2. **Adaptive browser research** searches through SearXNG and reads the strongest candidate pages in headless Chrome, searching again only for remaining gaps.
3. **Coverage evaluation and synthesis** record which pages cover which requirement. Requirements left partial or missing are reported as warnings.

Deep Agents is the single orchestration runtime. Its LangChain `ToolStrategy`
validates every workflow response against a Pydantic contract, while LiteLLM is
the mandatory model gateway. Changing the `agent-model` mapping in
`infra/litellm/config.yaml` swaps the underlying model without changing agent
code. The default model has a 1,048,576-token input window; automatic context
compaction starts at 838,860 tokens and preserves the most recent 20 messages.
`AGENT_REASONING_EFFORT=medium` is the application-level default and maps to
NVIDIA's middle supported tier, `high`. Deep Agents state stays in its virtual
filesystem, durable checkpoints use PostgreSQL in Compose and SQLite locally,
and optional MCP servers are supplied with `MCP_SERVERS_JSON` and scoped by
`AGENT_MCP_ROLES`.

### Agent observability

Each live session receives a short-lived LiteLLM virtual key, joining proxy model
records to the exact Deep Agents session. The append-only trace ledger combines
model requests and responses, actual model/model group, tokens, latency, cost,
context compaction, and browser/tool events. The authenticated `/observability`
run explorer presents the merged trace as a timeline and expandable structured
payloads. Prompt and response storage is enabled intentionally for complete
tracing; set appropriate access, retention, and redaction policies before
production use.

## Backend structure

```
backend/app/
├── agents/       # Research prompts and output contracts
├── controllers/  # HTTP route handlers
├── core/         # configuration
├── harness/      # Deep Agents runtime, LiteLLM gateway, and durable sessions
├── mcp/          # tool and trace audit persistence
├── models/       # domain models (session and transcript entities)
├── schemas/      # API request/response validation
└── services/     # workflow orchestration and application logic
```

## Accounts and testing

- `POST /auth/register`, `POST /auth/login`, and `GET /auth/me` proxy and validate Supabase Auth. Set `ADMIN_EMAIL` and the server-only `SUPABASE_SECRET_KEY` and that user is promoted to Supabase `app_metadata.role=admin` on first sign-in; the application never stores passwords or issues its own login tokens.
- Agent runs, sessions, tool invocations, and encrypted/redacted transcript entries are persisted. Learners can access only their own runs.
- Run the test suite with `cd backend && pytest -q --benchmark-disable`; `tests/test_supabase_live.py` checks the auth contract against the real Supabase project from `backend/.env` (creating and deleting a throwaway confirmed user) and fails in CI without the `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` and `SUPABASE_SECRET_KEY` repository secrets; run benchmarks with `pytest --benchmark-only`. The tests use controlled model and browser doubles but exercise the real browser-research pipeline.

## Next product milestones

1. **Phase 0 — curated coverage-based search:** one research agent with `search` and `read` tools builds the coverage checklist and its pages, and results appear as they arrive.
2. Course generation on top of the research, once a stronger model is available.
