# Handoff — MeetingGenius Prototype (Boss/Supervisor Context)

This document captures current state, key learnings, known issues, and the next steps for continuing development in a fresh agent thread.

## What We Built (Current Capabilities)

### End-to-end “AI whiteboard” loop

- **Frontend** (`apps/web/`): Vite + React UI with Transcript panel and a draggable/resizable whiteboard.
- **Backend** (`src/meetinggenius/server.py`): FastAPI WebSocket server (`ws://localhost:8000/ws`) that:
  - collects a rolling transcript window
  - runs an AI loop (orchestrator → research → board planner)
  - applies schema-validated `BoardAction`s to `BoardState`
  - broadcasts updates to all connected clients

### Meeting-agnostic behavior

- **Meeting-native artifacts** (no external research required): decisions, action items, open questions, risks/blockers, next steps.
- **External research** is **ON by default** with an **opt-out toggle** (session-level, persisted).

### Reliability + UX controls

- **Noise controls**: dedupe similar-title creates, rate-limit `create_card`, and convert duplicate creates into updates.
- **Multi-client sync**: user drag/resize + dismiss actions are sent to backend and broadcast to other clients.
- **Run AI now**: explicit trigger to schedule the AI loop without adding transcript noise.

### Persistence + sharing

- **SQLite persistence**: board state and session context survive backend restarts (`MEETINGGENIUS_DB_PATH`, default `./meetinggenius.sqlite3`).
- **Board export/import**: download/upload board JSON via WebSocket messages.
- **Telemetry export**: frontend captures lightweight session telemetry as downloadable JSON.

## Key Files and Where Things Live

### Backend

- `src/meetinggenius/server.py` — WebSocket protocol, AI loop, throttling/dedupe, persistence wiring.
- `src/meetinggenius/contracts.py` — Pydantic schemas (board/actions/transcript/research contracts).
- `src/meetinggenius/sqlite_store.py` — SQLite KV store + debounced persister.
- `src/meetinggenius/tools/registry.py` — Research tool registry (pluggable).
- `src/meetinggenius/tools/research.py` — Research dispatcher (tool-based tasks + legacy adapter).
- `src/meetinggenius/tools/weather_open_meteo.py` — Tool plugin: `weather.history_by_month`.
- `src/meetinggenius/tools/headlines_gdelt.py` — Tool plugin: `news.headlines_by_month`.
- `src/meetinggenius/agents/orchestrator.py` — Orchestrator prompt + board-state summary helper.
- `src/meetinggenius/agents/board_planner.py` — Board planner prompt + meeting-native card rules.

### Frontend

- `apps/web/src/App.tsx` — Header (assumptions, toggles, run/export/import), transcript wiring.
- `apps/web/src/components/Whiteboard.tsx` — Card rendering + drag/resize + dismiss → `client_board_action`.
- `apps/web/src/hooks/useBoardSocket.ts` — WebSocket client + message send helpers.
- `apps/web/src/telemetry/sessionTelemetry.ts` — Session telemetry capture + export.

### Scripts and docs

- `demo.sh` — one-command demo runner (backend + frontend) and printed demo prompts.
- `docs/Demo-Runbook.md` — demo steps.
- `smoke_ws.py` — WebSocket smoke test (expects weather/headlines outputs when external research is on).
- `docs/demo-board-export.json` — example importable board export (demo artifact).

## WebSocket Protocol Summary

Endpoint: `ws://localhost:8000/ws`

Client → server:

- `{ "type": "transcript_event", "event": { ...TranscriptEvent... } }`
- `{ "type": "reset" }`
- `{ "type": "ping" }`
- `{ "type": "run_ai" }`
- `{ "type": "client_board_action", "action": <BoardAction> }` (allowed: `move_card`, `dismiss_card`)
- `{ "type": "set_session_context", "default_location": "...", "no_browse": true|false }`
- `{ "type": "export_board" }`
- `{ "type": "import_board", "state": <BoardState>, "default_location"?: "...", "no_browse"?: true|false }`

Server → client:

- `{ "type": "status", "message": "..." }`
- `{ "type": "error", "message": "...", "details"?: {...} }`
- `{ "type": "pong" }`
- `{ "type": "board_actions", "actions": [ ...BoardAction... ], "state": <BoardState> }`
- `{ "type": "board_export", "state": <BoardState>, "default_location"?, "no_browse"? }`

## How to Run Locally

Preferred:

- `./demo.sh`

Manual:

- Backend: `uvicorn meetinggenius.server:app --reload --port 8000`
- Frontend: `cd apps/web && npm install && npm run dev`

## Model Configuration

The backend uses a single model string for both agents:

- Default: `openai:gpt-4o-mini`
- Override: `MEETINGGENIUS_MODEL`

Env keys:

- OpenAI: `OPENAI_API_KEY`
- Anthropic: `ANTHROPIC_API_KEY`

## Known Issues / Sharp Edges

### 1) “AI loop failed.” due to provider quota/billing (common)

Symptoms:

- UI shows “AI loop failed.”
- Server error details show `status_code: 429` and `insufficient_quota`.

Fix:

- Add billing/credits for the OpenAI project OR switch provider/model:
  - `export ANTHROPIC_API_KEY="..."`
  - `export MEETINGGENIUS_MODEL="anthropic:claude-3-5-haiku-latest"`
  - restart backend (existing `uvicorn` won’t pick up new env).

### 2) Whiteboard area is “blank/grey” even though transcript is sent

Likely cause:

- The board planner may emit `update_card` actions for meeting-native stable IDs (`list-decisions`, etc.) before those cards exist.
- `update_card` on a missing card is a no-op in the reducer, so the board remains empty.

Recommended fix:

- Seed the five meeting-native base list cards automatically **on the first AI run** (not on reset, to keep smoke tests/semantics), and exempt them from throttling/dedupe.

## Next Steps (Highest ROI)

1) **Fix “blank grey whiteboard”** by seeding meeting-native base cards on first AI run.
2) Extend session context to include **years/month** (UI already tracks years; currently not enforced structurally).
3) Add “meeting templates” button(s) to create/pin base cards immediately (standup/planning/sales call layouts).
4) Improve layout: place stable meeting-native cards in predictable columns.
5) Add “pin/lock” so users can prevent AI from modifying specific cards.

