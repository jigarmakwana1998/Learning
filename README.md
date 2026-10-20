# Learning Coach

An Expo (React Native + TypeScript) app for web, iOS, and Android, a Next.js web client, and a FastAPI service that turns a learner's goal into a researched curriculum, study schedule, quizzes, and assignments.

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
Caddy at `http://localhost:8080`; the API is available beneath `/api`. Before a
non-development deployment, apply
`backend/infra/postgres/roles.sql` as the database owner after migration; agent
workers must use the insert-only `agent_writer` role, never the migration owner.

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
OpenRouter and NVIDIA API keys only in the repository-root `.env`; LiteLLM owns those credentials,
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

The API docs are available at `http://127.0.0.1:8000/docs`. Course generation
always uses Deep Agents with public browser research. The stable `agent-model`
LiteLLM alias currently resolves to OpenRouter's free `minimax/minimax-m3.1-flash:free`,
falling back to NVIDIA's `z-ai/glm-5.3-flash` while it is rate-limited.

Local development may use SQLite for application data, but authentication still
requires Supabase. Both frontends call the backend auth endpoints; Supabase keys
and authentication requests remain behind the API.

Copy `backend/.env.example` to `backend/.env`, set the Supabase values, and
replace the encryption key before deployment. Install the pinned browser tool
with `npm install`, run `npm run browser:install`, and verify it with
`npm run browser:doctor`. The application creates a session-scoped LiteLLM key
for every Deep Agent run; provider calls never bypass the gateway.

Set the first administrator's Supabase Auth `app_metadata.role` to `admin` in
the Supabase dashboard or with a server-side administrative tool.

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

`POST /learning-runs` runs a real, evidence-gated pipeline:

1. **Research query planner** derives semantic coverage requirements, focused discovery queries, and optional canonical seeds.
2. **Adaptive browser research** reads the strongest candidate first, discards leftover candidates after their mapped requirement is covered, and searches only for remaining evidence gaps while retaining a complete visit ledger.
3. **Coverage evaluation and synthesis** stop only when every curriculum-scale requirement is supported at the requested depth; incomplete research is never presented as a complete course.
4. **Planner** creates a compact, time-bounded course architecture that maps every verified requirement to modules, lesson blueprints, section plans, assessments, and exact supporting URLs.
5. **Lesson writers** expand each blueprint into a 1,200-1,800 word lesson. Validation proves every research requirement reaches a cited paragraph and rejects missing, unsupported, repetitive, or generic content.

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
├── agents/       # Research, planning, lesson-writing prompts and output contracts
├── controllers/  # HTTP route handlers
├── core/         # configuration
├── harness/      # Deep Agents runtime, LiteLLM gateway, and durable sessions
├── mcp/          # tool and trace audit persistence
├── models/       # domain models (session and transcript entities)
├── schemas/      # API request/response validation
└── services/     # workflow orchestration and application logic
```

`GET /agent-sessions/{id}` returns a decrypted, authorization-checked transcript. `POST /agent-sessions/{id}/resume` appends to an active durable session, and `POST /agent-sessions/{id}/close` terminates it.

## Accounts, analytics, and evaluation

- `POST /auth/register`, `POST /auth/login`, and `GET /auth/me` proxy and validate Supabase Auth. Set `ADMIN_EMAIL` and the server-only `SUPABASE_SECRET_KEY` and that user is promoted to Supabase `app_metadata.role=admin` on first sign-in (or set the role in the Supabase dashboard); the application never stores passwords or issues its own login tokens.
- Agent runs, sessions, tool invocations, and encrypted/redacted transcript entries are persisted. Learners can access only their own data; `/analytics/*` is admin-only.
- The Expo client includes an admin analytics screen with user and session lists, outcome metrics, and full searchable transcript drill-down.
- Run the test suite with `cd backend && pytest -q --benchmark-disable`; `tests/test_supabase_live.py` checks the auth contract against the real Supabase project from `backend/.env` (creating and deleting a throwaway confirmed user) and fails in CI without the `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` and `SUPABASE_SECRET_KEY` repository secrets; run benchmarks with `pytest --benchmark-only`. The tests use controlled model and browser doubles but exercise the same browser-research and course-validation pipeline.
- Run a complete opt-in live course smoke test with `LIVE_SMOKE_EMAIL` and `LIVE_SMOKE_PASSWORD` set for a confirmed Supabase account, then `cd backend && python scripts/live_course_smoke.py`. It consumes NVIDIA API quota, browses public pages, prints the exact selected source URLs and coverage metrics, and fails unless all research requirements map through modules and lessons to full-length cited paragraphs.

## Next product milestones

1. Move long-running research into durable background jobs with progress streaming.
2. Add human source-quality review before course publication.
3. Add notifications, calendar scheduling, and deeper learning analytics.
