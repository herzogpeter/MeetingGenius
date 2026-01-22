# MeetingGenius

Prototype for an AI-powered meeting whiteboard using PydanticAI and schema-validated board actions.

## Docs

- `docs/PRD.md`
- `docs/Rapid-Prototype-Plan.md`
- `docs/Backlog.md`
- `docs/Architecture.md`
- `docs/Demo-Runbook.md`
- `Handoff.md`

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

Set one of (required):

- `OPENAI_API_KEY` (default model string: `openai:gpt-4o-mini`)
- `ANTHROPIC_API_KEY`

Optional:

- `MEETINGGENIUS_MODEL` (e.g. `anthropic:claude-3-5-sonnet-latest`)
- `MEETINGGENIUS_DEFAULT_LOCATION` (default: `Seattle`)
- `MEETINGGENIUS_DB_PATH` (default: `./meetinggenius.sqlite3` in the repo root)
- `MEETINGGENIUS_PERSIST_DEBOUNCE_SECONDS` (default: `1.25`)
- `MEETINGGENIUS_NO_BROWSE=1` (disables external research tools unless overridden by `set_session_context.no_browse`)
- `MEETINGGENIUS_MAX_CREATE_CARDS_PER_MINUTE` (default: `2`)
- `MEETINGGENIUS_MIN_SECONDS_BETWEEN_CREATES` (default: `20`)
- `MEETINGGENIUS_DEDUPE_TITLE_SIMILARITY=0|1` (default: `1`)

## Run backend (WebSocket)

```bash
uvicorn meetinggenius.server:app --reload --port 8000
```

WebSocket endpoint: `ws://localhost:8000/ws`

## Research tools (backend)

Research is tool-driven and pluggable. A `ResearchTask` can be expressed generically as:

- `tool_name`: string tool identifier
- `args`: dict of tool arguments
- `requires_browse`: bool (default `true`); blocked when `MEETINGGENIUS_NO_BROWSE=1`

Legacy `ResearchTask.kind/query/location/month/years` fields are still supported for backward compatibility but are deprecated in favor of `tool_name` + `args`.

Built-in tools:

- `weather.history_by_month` — `{ location, month=12, years=10, unit="both" }` → `WeatherHistoryData`
- `news.headlines_by_month` — `{ query, month=12, years=5, limit=8 }` → `HeadlinesData`

## Persistence (backend)

The backend persists server state to SQLite so boards survive restarts and reconnecting clients converge.

- Stored in a single SQLite table `kv(key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)`.
- Keys: `board_state` (cards/layout/dismissed), `default_location` (session context), `no_browse` (session context).
- Writes are debounced (flush at most once every ~`MEETINGGENIUS_PERSIST_DEBOUNCE_SECONDS` seconds).
- Sending `{"type":"reset"}` clears the in-memory state and deletes the persisted keys.

### WebSocket messages

Client → server:

- `{"type":"ping"}`
- `{"type":"reset"}`
- `{"type":"run_ai"}` (requests an AI run using the current transcript window)
- `{"type":"transcript_event","event":{...}}`
- `{"type":"set_session_context","default_location":"United States","no_browse":false}` (overrides `MEETINGGENIUS_DEFAULT_LOCATION` and, when present, overrides `MEETINGGENIUS_NO_BROWSE` for this server session)
- `{"type":"client_board_action","action":{"type":"move_card",...}}` (allowed: `move_card`, `dismiss_card`)

Server → client:

- `{"type":"pong"}`
- `{"type":"status","message":"..."}`
- `{"type":"board_actions","actions":[...],"state":{...}}`
- `{"type":"error","message":"...","details":{...}}`

## Run frontend (prototype)

Vite + React app that connects to the backend WebSocket and renders the current board state:

```bash
cd apps/web && npm install && npm run dev
```

Open `http://localhost:5173`.

Optional:

```bash
VITE_WS_URL=ws://localhost:8000/ws npm run dev
```

## Optional: run both (demo)

```bash
./demo.sh
```

This starts both services (backend on `http://localhost:8000`, frontend on `http://localhost:5173`) and prints the demo steps + prompts.

Notes:

- In the web UI header, use the `External research` toggle (On/Off). For data-backed cards (weather/news), keep it `On`.
- `Run AI now` forces a run using the current transcript window (useful if you tweak assumptions or want to re-run without sending a new message).

Demo prompts:

- Standup: `Summarize today's standup into 3 wins, 3 blockers, and 3 next steps.`
- Planning: `Turn our planning discussion into a prioritized backlog with owners and rough estimates.`
- Sales call: `Extract buyer pain points, objections, and next steps from this sales call.`

## LAN mic mode (HTTPS + WSS)

Chrome requires a secure origin for live mic mode on another device. Use the HTTPS demo script:

```bash
./demo-https.sh
```

If LAN IP auto-detection fails (or you want to pin it):

```bash
BIND_HOST=0.0.0.0 PUBLIC_HOST=192.168.1.50 ./demo-https.sh
```

Install mkcert and trust the local CA (one-time):

```bash
brew install mkcert
mkcert -install
```

## Run a quick simulation

```bash
meetinggenius simulate "I wonder what the local temperature trends are for december this year?"
```
