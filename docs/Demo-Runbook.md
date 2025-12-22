# Demo Runbook (Reliable “December Cards”)

Goal: reliably demo these two whiteboard cards:

- December temperature trends (`chart` card)
- December headlines (`list` card)

## Prereqs

- Python 3.11+ (recommended) + `pip`
- Node.js 18+ (recommended) + `npm`
- One LLM provider key set: `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`

Optional env vars:

- `MEETINGGENIUS_MODEL` (defaults to `openai:gpt-4o-mini`)
- `MEETINGGENIUS_DEFAULT_LOCATION` (defaults to `Seattle`; demo tip: set to `United States` for broader headline coverage)
- `MEETINGGENIUS_NO_BROWSE=1` (disables external research tools; cards will not populate with real data)

## Start the backend

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .

uvicorn meetinggenius.server:app --reload --port 8000
```

Backend WebSocket: `ws://localhost:8000/ws`

## Start the frontend

```bash
cd apps/web && npm install && npm run dev
```

Open `http://localhost:5173`.

If you need to override the WS URL:

```bash
VITE_WS_URL=ws://localhost:8000/ws npm run dev
```

## Optional: start both with one command

```bash
./demo.sh
```

Expected URLs:

- Backend: `http://localhost:8000` (WebSocket: `ws://localhost:8000/ws`)
- Frontend: `http://localhost:5173`

## Automated smoke test (repeatable “wow moments”)

With the backend running, run:

```bash
python smoke_ws.py
```

To override the WebSocket URL or timeout:

```bash
MEETINGGENIUS_WS_URL=ws://localhost:8000/ws MEETINGGENIUS_SMOKE_TIMEOUT_S=180 python smoke_ws.py
```

If you see `missing dependency 'websockets'`, install it in your venv:

```bash
python -m pip install websockets
```

## Demo script (exact phrases + expected outcomes)

In the web UI:

- Use the header `External research` toggle (On/Off). For this runbook, keep it `On`.
- Use the left “Transcript” panel to send text transcript events.
- If you want to force/re-run without sending a new transcript event, click `Run AI now` in the header.

1) Click `Reset`.
- Expected: whiteboard clears; header status shows “State reset.”

2) Paste this into “Text” and click `Send`:

`Show the temperature trends for December over the last 10 years.`

- Expected: header status cycles through “Running orchestrator…”, “Research tasks: 1”, “Running board planner…”.
- Expected card: a new `chart` card appears with ~10 yearly points (December average temperature history) and a “Sources” section.

3) Paste this into “Text” and click `Send`:

`Pull the top December headlines for the last 5 years.`

- Expected: similar status messages; then a new `list` card appears.
- Expected card: a `list` card with multiple linked bullet items and a “Sources” section.

## Demo prompts (standup / planning / sales call)

These are good “general” prompts when you don’t want to depend on external data sources.

- Standup: `Summarize today's standup into 3 wins, 3 blockers, and 3 next steps.`
- Planning: `Turn our planning discussion into a prioritized backlog with owners and rough estimates.`
- Sales call: `Extract buyer pain points, objections, and next steps from this sales call.`

## Troubleshooting (fast)

- UI shows `WS: closed`/`error`: ensure backend is running on port `8000` and the frontend is using `VITE_WS_URL=ws://localhost:8000/ws` if needed.
- Cards never appear: confirm `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` is set; confirm `External research` is On if you expect data-backed cards; confirm `MEETINGGENIUS_NO_BROWSE` is not `1`.
- Headlines list is empty: set `MEETINGGENIUS_DEFAULT_LOCATION=United States` and retry step (3) (then click `Reset` to keep the demo clean).
