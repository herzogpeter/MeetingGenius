# MeetingGenius

Prototype for an AI-powered meeting whiteboard using PydanticAI and schema-validated board actions.

## Docs

- `docs/PRD.md`
- `docs/Rapid-Prototype-Plan.md`
- `docs/Backlog.md`
- `docs/Architecture.md`
- `docs/Demo-Runbook.md`

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
- `MEETINGGENIUS_NO_BROWSE=1` (disables external research tools)
- `MEETINGGENIUS_MAX_CREATE_CARDS_PER_MINUTE` (default: `2`)
- `MEETINGGENIUS_MIN_SECONDS_BETWEEN_CREATES` (default: `20`)
- `MEETINGGENIUS_DEDUPE_TITLE_SIMILARITY=0|1` (default: `1`)

## Run backend (WebSocket)

```bash
uvicorn meetinggenius.server:app --reload --port 8000
```

WebSocket endpoint: `ws://localhost:8000/ws`

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
./dev.sh
```

## Run a quick simulation

```bash
meetinggenius simulate "I wonder what the local temperature trends are for december this year?"
```
