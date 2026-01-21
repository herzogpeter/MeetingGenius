# MeetingGenius Web (Prototype)

One-page React prototype that connects to a backend WebSocket and renders the current `BoardState` as draggable/resizable cards.

## Run locally

```bash
cd apps/web
npm install
npm run dev
```

Open `http://localhost:5173`.

To override the WebSocket URL:

```bash
VITE_WS_URL=ws://localhost:8000/ws npm run dev
```

## Live mic mode (optional)

The Transcript panel supports optional live microphone transcription via the browser Web Speech API (`SpeechRecognition` / `webkitSpeechRecognition`).

- Browser support: works best in Chrome-based browsers; some browsers don’t implement this API.
- Origin requirement: most browsers require `https://` (or `http://localhost`) for microphone access.

How to use:

1. Start the backend so the UI shows `WS: open`.
2. In the Transcript panel, click `Start mic` and allow microphone permission.
3. Speak — transcript events are sent to the backend as they are recognized.
4. Optional:
   - Enable `Send interim results` to send partial chunks (`is_final: false`) before final results arrive.
   - Change `Language` to improve recognition quality.

## Backend WebSocket expectations

Connect to `ws://localhost:8000/ws`.

Send:

```json
{ "type": "transcript_event", "event": { "timestamp": "...", "speaker": "User", "text": "...", "is_final": true } }
```

```json
{ "type": "reset" }
```

Receive:

```json
{ "type": "board_actions", "actions": [...], "state": { "cards": {}, "layout": {}, "dismissed": {} } }
```

```json
{ "type": "status", "message": "..." }
```

Notes:

- `chart` cards render as a line chart from `props.points` (`{label,value}`).
- `list` cards render as bullets from `props.items` (`{text,url?,meta?}`).
- The “Dismiss” button is client-side only (it hides the card locally).

## Build

```bash
npm run build
```

## E2E (Playwright)

An optional E2E test drives the UI “Replay transcript (simulation)” and checks that the Mindmap view updates.

One-time setup:

```bash
cd apps/web
npm ci
npm run playwright:install
```

Run:

```bash
cd apps/web
npm run test:e2e -- e2e/mindmap-replay.spec.ts
```

Notes:

- The Playwright config starts backend+frontend via `scripts/e2e-serve.sh` (defaults: backend `8010`, frontend `5174`).
- Set `E2E_STRICT=1` to enable simple thresholds (override with `E2E_MIN_NODES` / `E2E_MIN_UNIQUE_RATIO`).
