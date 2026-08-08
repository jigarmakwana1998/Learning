# Learning Coach

An Expo (React Native + TypeScript) app for web, iOS, and Android, a Next.js web client, and a FastAPI service that turns a learner's goal into a researched curriculum, study schedule, quizzes, and assignments.

## Structure

- `mobile/` — Universal Expo Router client (web, iOS, Android)
- `backend/` — FastAPI API and provider-agnostic agent harness

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

Browser-backed Gemini research requires Node.js 24 or newer. Install the pinned
Gemini CLI, agent-browser, and Chrome for Testing from the repository root:

```powershell
.\scripts\setup-browser-tools.ps1
```

On Linux or macOS:

```bash
sh ./scripts/setup-browser-tools.sh
```

The scripts use `npm ci`, so the CLI versions come from the committed lockfile.
They install Chrome for Testing and run agent-browser's offline diagnostics. The
Docker image performs the same setup automatically. Authenticate Gemini by
setting `GEMINI_API_KEY` in `backend/.env`; browser installation itself does not
make a paid model request.

The committed `.gemini/settings.json` registers the local `learning-browser`
MCP server. Gemini may discover only `browser_search` and `browser_read`; no
global Gemini configuration is required. Start the API or Gemini CLI from either
the repository root or `backend/`. The Docker image copies the same project
configuration into `/app/.gemini`.

```bash
cd backend
uv sync --group dev
uv run uvicorn app.main:app --reload
```

The backend is managed with `uv`. Its first hexagonal vertical slice is
`GET /health`: the FastAPI adapter resolves an application service through
Dishka, and that service calls a replaceable outbound health port.

For local PostgreSQL, run `docker compose -f docker-compose.yml up -d` from `backend/` and set `DATABASE_URL=postgresql+asyncpg://learning_coach:learning_coach@127.0.0.1:5432/learning_coach` in `backend/.env`. Run `alembic upgrade head` to create or update the schema. For deployment, use the Supabase Session Pooler connection string in `DATABASE_URL`, then run that same migration command in the deployment environment. Supabase Auth owns email/password credentials; the backend verifies each Supabase access token and creates a matching application profile on first use.

The API docs are available at `http://127.0.0.1:8000/docs`. Course generation always uses a live agent harness and public browser research. Gemini CLI is the default:

```bash
AGENT_HARNESS=gemini-cli  # gemini-cli, codex, or antigravity-cli
```

For local-only development, set `DATABASE_URL=sqlite+aiosqlite:///./learning_local.db` and `LOCAL_AUTH=true`. This explicitly disables Supabase token verification for that process; never enable it in a deployed environment.

Copy `backend/.env.example` to `backend/.env`, set the Supabase values, and replace the encryption key before deployment. Each harness is executed through its installed CLI. Install the pinned project tools with `npm install`, run `npm run browser:install`, and verify them with `npm run browser:doctor`. Antigravity CLI 1.1.8+ is required for headless `stream-json` tracing. The application injects a session-scoped LiteLLM key and stable `agent-model` alias into every harness process; executable overrides cannot remove the enforced gateway/model flags.

Set the first administrator's Supabase Auth `app_metadata.role` to `admin` in the Supabase dashboard or with a server-side administrative tool. The mobile admin screen controls the default agent harness, never the LLM provider; the setting is stored in PostgreSQL and applies to new runs immediately without restarting the API.

## Start the mobile app

Install Node.js 20+ first, then:

```bash
cd mobile
npm install
npx expo start
```

Press `w` for the web app, `i` for iOS simulator, or `a` for Android emulator. Expo Go can be used for a physical device.

Copy `mobile/.env.example` to `mobile/.env`. Set the Supabase Project URL and publishable key; for an iOS/Android device, set `EXPO_PUBLIC_API_URL` to your computer's LAN address, for example `http://192.168.1.10:8000`.

## Agent harness

`POST /learning-runs` runs a real, evidence-gated pipeline:

1. **Research query planner** derives semantic coverage requirements, focused discovery queries, and optional canonical seeds.
2. **Adaptive browser research** reads the strongest candidate first, then searches only for remaining evidence gaps while retaining a complete visit ledger.
3. **Coverage evaluation and synthesis** stop as soon as the requested depth is supported, whether that takes one authoritative source or several complementary sources.
4. **Planner** creates the complete course, paragraph-level citations, quizzes, answer explanations, assignment, rubric, and project. Invalid or unverified output fails instead of falling back to generic content.

The adapters support Codex, Gemini CLI, and Antigravity CLI as independent harnesses. LiteLLM is not a harness: it is the mandatory model gateway beneath all three. The application requests the stable `agent-model` alias; changing that alias in `infra/litellm/config.yaml` swaps the underlying LLM without changing harness selection. Gemini CLI is retained as requested; Google's current tooling is transitioning it to Antigravity CLI, so Antigravity remains a separate harness. [Google's Antigravity documentation](https://www.antigravity.google/docs/cli-overview) describes the current CLI; [the Gemini CLI transition notice](https://github.com/google-gemini/gemini-cli/discussions/27274) explains the migration.

### Agent observability

Each live session receives a short-lived LiteLLM virtual key, joining proxy model records to the exact harness session. The append-only trace ledger combines model requests and responses, actual model/model group, tokens, latency, and cost with harness lifecycle and browser/tool events. The authenticated `/observability` run explorer presents the merged trace as a timeline, expandable structured payloads, and a Learning Coach → harness → LiteLLM → model topology. Prompt and response storage is enabled intentionally for complete tracing; set appropriate access, retention, and redaction policies before production use.

## Backend structure

```
backend/app/
├── agents/       # Researcher, Planner, Examiner prompts and role contracts
├── controllers/  # HTTP route handlers
├── core/         # configuration
├── harness/      # harness runtimes, LiteLLM gateway, and durable sessions
├── mcp/          # safe tool contracts agents can use
├── models/       # domain models (session and transcript entities)
├── schemas/      # API request/response validation
└── services/     # workflow orchestration and application logic
```

`GET /agent-sessions/{id}` returns a decrypted, authorization-checked transcript. `POST /agent-sessions/{id}/resume` appends to an active durable session, and `POST /agent-sessions/{id}/close` terminates it.

## Accounts, analytics, and evaluation

- `POST /auth/register`, `POST /auth/login`, and `GET /auth/me` provide email/password JWT authentication. The configured `ADMIN_EMAIL` / `ADMIN_PASSWORD` account is created with the `admin` role on first startup.
- Agent runs, sessions, tool invocations, and encrypted/redacted transcript entries are persisted. Learners can access only their own data; `/analytics/*` is admin-only.
- The Expo client includes an admin analytics screen with user and session lists, outcome metrics, and full searchable transcript drill-down.
- Run the test suite with `cd backend && pytest -q --benchmark-disable`; run benchmarks with `pytest --benchmark-only`. The tests use controlled executable doubles for external CLIs but exercise the same browser-research and course-validation pipeline. Opt-in authenticated CLI evaluation is `python scripts/live_provider_evaluation.py`.
- Run a complete opt-in live course smoke test with `cd backend && python scripts/live_course_smoke.py`. It consumes Gemini quota, browses public pages, and prints the exact selected source URLs plus course completeness counts.

## Next product milestones

1. Move long-running research into durable background jobs with progress streaming.
2. Add human source-quality review before course publication.
3. Add notifications, calendar scheduling, and deeper learning analytics.
