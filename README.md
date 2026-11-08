# Learning Coach

An Expo (React Native + TypeScript) app for web, iOS, and Android, a Next.js web client, and a FastAPI service that researches a learner's topic: it maps what the topic involves and finds public pages that teach each part.

## Structure

One uv workspace (`pyproject.toml` and `uv.lock` at the root):

- `backend/` — FastAPI API (`app/`): auth, research runs, the Deep Agents harness, and tracing
- `database/` — `learning_db` package: SQLAlchemy models, async session, and Alembic migrations
- `mcp/` — MCP servers; `mcp/browser/` (`browser_mcp`) is the restricted public-web browser (SearXNG search, hardened Chrome reads) with its pinned `agent-browser` toolchain; `mcp/course/` (`course_mcp`) serves a research run's source pages and stores the cited course being written
- `web/` — Next.js client; `mobile/` — Expo Router client (web, iOS, Android)
- `infra/` — Caddy, LiteLLM and SearXNG configuration for `compose.yml`

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

Install the Python workspace from the repository root:

```bash
uv sync
```

Browser-backed research requires Node.js 24 or newer. Install the pinned
agent-browser package and Chrome for Testing for the browser MCP server:

```bash
sh mcp/browser/scripts/setup-browser-tools.sh      # Linux or macOS
.\mcp\browser\scripts\setup-browser-tools.ps1      # Windows
```

The scripts use `npm ci`, so the browser version comes from the committed
lockfile in `mcp/browser/`. The Docker image performs the same setup
automatically. Put the OpenAI API key only in the repository-root `.env`;
LiteLLM owns that credential, and the API receives only its LiteLLM key.

Copy `backend/.env.example` to `backend/.env`, set the Supabase values and a
generated `APP_ENCRYPTION_KEY`, then create the schema and start the API:

```bash
cd database && uv run alembic upgrade head && cd ..
cd backend && uv run uvicorn app.main:app --reload
```

For deployment, use the Supabase Session Pooler connection string in
`DATABASE_URL` and run the same migration command. Supabase Auth owns
email/password credentials; the backend verifies each Supabase access token and
creates a matching application profile on first use. Local development may use
SQLite for application data (`DATABASE_URL=sqlite+aiosqlite:///./learning_coach.db`),
but authentication still requires Supabase.

The API docs are available at `http://127.0.0.1:8000/docs`. The stable
`agent-model` LiteLLM alias is mapped in `infra/litellm/config.yaml`; the
application creates a session-scoped LiteLLM key for every agent run.

## Start the mobile app

Install Node.js 22.13+ (CI uses 22.19.0) first, then:

```bash
cd mobile
npm install
npx expo start
```

The mobile app uses Expo SDK 58, pinned to 58.0.22 (released October 31, 2026;
at least seven days old when selected). Router, React Native, and native modules
are aligned with that SDK. Use an SDK 58-compatible Expo Go or development build.
SDK 58 requires iOS 16.4+ and Android 7+; rebuilding a development client is
required after this native dependency upgrade. Press `w` for web, `i` for the iOS
simulator, or `a` for the Android emulator. Web export remains static.

Copy `mobile/.env.example` to `mobile/.env`. For an iOS/Android device, set `EXPO_PUBLIC_API_URL` to your computer's LAN address, for example `http://192.168.1.10:8000`.

## Agent runtime

`POST /research-runs` starts research in the background and returns `202 {id}`.
Poll `GET /research-runs/{id}`: it returns the status, the current tool activity,
the coverage items and the pages saved so far, so results show as they arrive.

Standalone research uses a **Researcher** Deep Agent with `browser_search`,
`browser_read`, `set_coverage` and `save_page`. Research metadata has no content
minimums. Saving an unread page gives an informational note rather than rejecting
it. Its skills live in `backend/app/skills/research/`.

`POST /research-runs/{id}/courses` builds a new course version from a completed
research run; every version is kept (`GET /research-runs/{id}/courses`). Poll
`GET /courses/{id}` for chapters, sections, sources and current agent activity.

**CourseBuilder** owns the outline and delegates through Deep Agents' native
`task` tool to two named specialists:

- **Researcher** receives focused questions, searches and reads sources, and uses
  `save_page` to add captured source text to the course library.
- **Writer** receives chapter or section briefs and source IDs, reads evidence,
  and saves sections through `write_section`. `read_section` loads saved content
  for revisions. Writer returns missing research questions to CourseBuilder.

CourseBuilder can request more research and then send Writer a revision brief.
The source library is refreshed on every read, so newly saved evidence is
available during the same build. Initial research text is reused; each new
course version gets its own source snapshots under its course run ID in
`source_pages`. Existing courses still read their original research snapshots,
so no database migration is needed.

Agent skills live in `backend/app/skills/course/`, `research/` and `writer/`.
Content length, sentence kind and citations are flexible. Citation quotes are
optional; no automatic quote/number grading or mandatory warning-fixing pass
runs. `check_course` reports progress without rejecting content. Actual execution
errors still mark the run failed and preserve sections already saved.

LiteLLM is the mandatory model gateway: changing the `agent-model` mapping in
`infra/litellm/config.yaml` swaps the model without changing agent code. Durable
checkpoints use PostgreSQL in Compose and SQLite locally.

Browser and course tools use the official MCP 2.x client and `MCPServer`. The LangChain MCP
adapter was removed because its published releases still require MCP 1.x.

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
├── agents/       # Researcher and CourseBuilder prompts, tools and MCP clients
├── controllers/  # HTTP route handlers (auth, health, research runs, courses, observability)
├── core/         # configuration, auth dependencies, Supabase, encryption
├── harness/      # Deep Agents runtime, LiteLLM gateway, and durable sessions
├── schemas/      # API request/response validation
├── services/     # research runs, course builds and their live progress
├── skills/       # research/ and course/ skills (SKILL.md) for each agent
└── tracing.py    # trace-event and tool-invocation persistence
```

## Accounts and testing

- `POST /auth/register`, `POST /auth/login`, and `GET /auth/me` proxy and validate Supabase Auth. Set `ADMIN_EMAIL` and the server-only `SUPABASE_SECRET_KEY` and that user is promoted to Supabase `app_metadata.role=admin` on first sign-in; the application never stores passwords or issues its own login tokens.
- Agent runs, sessions, tool invocations, and encrypted/redacted transcript entries are persisted. Learners can access only their own runs.
- Run the test suite from the repository root with `uv run pytest -q --benchmark-disable` (backend and browser MCP tests); `tests/test_supabase_live.py` checks the auth contract against the real Supabase project from `backend/.env` (creating and deleting a throwaway confirmed user) and fails in CI without the `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` and `SUPABASE_SECRET_KEY` repository secrets; run benchmarks with `pytest --benchmark-only`. The tests use controlled model and browser doubles but exercise the real browser-research pipeline.

## Next product milestones

1. **Phase 0 — curated coverage-based search:** one research agent with `search` and `read` tools builds the coverage checklist and its pages, and results appear as they arrive.
2. Course generation: CourseBuilder coordinates focused research and section writing, with iterative revisions.
