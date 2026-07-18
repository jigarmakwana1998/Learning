# Learning Coach

An Expo (React Native + TypeScript) app for web, iOS, and Android, plus a FastAPI service that turns a learner's goal into a researched curriculum, study schedule, quizzes, and assignments.

## Structure

- `mobile/` — Universal Expo Router client (web, iOS, Android)
- `backend/` — FastAPI API and provider-agnostic agent harness

## Start the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

For local PostgreSQL, run `docker compose -f docker-compose.yml up -d` from `backend/` and set `DATABASE_URL=postgresql+asyncpg://learning_coach:learning_coach@127.0.0.1:5432/learning_coach` in `backend/.env`. For deployment, use the Supabase Session Pooler connection string in `DATABASE_URL` and set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`. Supabase Auth owns email/password credentials; the backend verifies each Supabase access token and creates a matching application profile on first use.

The API docs are available at `http://127.0.0.1:8000/docs`. The default `mock` provider makes the app usable locally without an LLM. Configure a real provider in `backend/.env`:

```bash
AGENT_PROVIDER=codex       # codex, gemini-cli, antigravity-cli, or mock
```

Copy `backend/.env.example` to `backend/.env`, set the Supabase values, and replace the encryption key and admin password before deployment. Each real provider is executed through its installed CLI; ensure it is authenticated on the server. CLI invocation flags can change, so the example supports `CODEX_COMMAND`, `GEMINI_CLI_COMMAND`, and `ANTIGRAVITY_CLI_COMMAND` overrides that emit one JSON object to stdout. The harness keeps commands behind one adapter, so moving to an API/SDK-based provider later does not affect the three-agent workflow.

## Start the mobile app

Install Node.js 20+ first, then:

```bash
cd mobile
npm install
npx expo start
```

Press `w` for the web app, `i` for iOS simulator, or `a` for Android emulator. Expo Go can be used for a physical device.

Copy `mobile/.env.example` to `mobile/.env`. Set the Supabase Project URL and publishable key; for an iOS/Android device, set `EXPO_PUBLIC_API_URL` to your computer's LAN address, for example `http://192.168.1.10:8000`.

## Next product milestones

## Agent harness

`POST /learning-runs` coordinates three explicitly scoped agents:

1. **Researcher** discovers and ranks sources (papers, official docs, open-source repositories, lectures, books, articles) and must retain URLs and rationale.
2. **Planner** selects the relevant research and creates a curriculum that respects the learner's level, timeline, and weekly availability.
3. **Examiner** creates quizzes, assignments, and a project. Its later evaluation endpoint uses results to recommend adding, removing, or reviewing content.

The adapters support Codex, Gemini CLI, and Antigravity CLI. Gemini CLI is retained as requested; Google's current tooling is transitioning it to Antigravity CLI, so Antigravity is available as a separate provider. [Google's Antigravity documentation](https://www.antigravity.google/docs/cli-overview) describes the current CLI; [the Gemini CLI transition notice](https://github.com/google-gemini/gemini-cli/discussions/27274) explains the migration.

## Backend structure

```
backend/app/
├── agents/       # Researcher, Planner, Examiner prompts and role contracts
├── controllers/  # HTTP route handlers
├── core/         # configuration
├── harness/      # provider runtimes plus start/resume/close/transcript sessions
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
- Run the deterministic suite with `cd backend && pytest -q --benchmark-disable`; run benchmarks with `pytest --benchmark-only`. Opt-in authenticated CLI evaluation is `python scripts/live_provider_evaluation.py` with `AGENT_PROVIDER` set to `codex`, `gemini-cli`, or `antigravity-cli`.

## Next product milestones

1. Replace the deterministic research fallback with search APIs and source fetching in a sandbox.
2. Add authentication, database persistence, and background job queues for long-running research.
3. Add citations, source-quality review, and human approval before plan publication.
4. Add notifications, calendar scheduling, and learning analytics.
