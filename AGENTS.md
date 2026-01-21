# Repository Guidelines

## Project Structure & Module Organization

- `src/meetinggenius/`: Python backend (FastAPI WebSocket server, agents, tools, SQLite persistence).
  - Key modules: `server.py`, `contracts.py`, `board/reducer.py`, `agents/`, `tools/`.
- `apps/web/`: Vite + React prototype UI (TypeScript) that connects to `ws://localhost:8000/ws`.
- `docs/`: Product + architecture docs (start with `docs/Architecture.md` and `docs/Demo-Runbook.md`).
- Scripts: `demo.sh` (runs backend + frontend), `dev.sh` (wrapper for `demo.sh`).

## Build, Test, and Development Commands

- Backend install (editable): `python -m venv .venv && source .venv/bin/activate && python -m pip install -U pip && python -m pip install -e .`
- Run backend: `uvicorn meetinggenius.server:app --reload --port 8000`
- Run frontend: `cd apps/web && npm ci && npm run dev` (open `http://localhost:5173`)
- Run both (demo): `./demo.sh`
- Build frontend (CI parity): `cd apps/web && npm run build`
- Python compile check (CI parity): `python -m compileall -q src`

## Coding Style & Naming Conventions

- Python: 4-space indent, type hints where practical. Ruff is configured in `pyproject.toml` (line length: 100).
- Web: TypeScript + React. ESLint is configured in `apps/web/eslint.config.js`; run `npm run lint`.
- Naming: Python `snake_case` modules/functions; React components `PascalCase.tsx`; hooks `useX.ts`.

## Testing Guidelines

- There is no dedicated unit test suite yet; CI validates Python compilation and the web build.
- For protocol/contract changes, do a manual smoke run: start the backend + UI and confirm the UI shows `WS: open`.
- Optional UI E2E: see `apps/web/playwright.config.ts` and run `cd apps/web && npx playwright test e2e/mindmap-replay.spec.ts`.

## Commit & Pull Request Guidelines

- Commit messages follow a Conventional Commits-style pattern, e.g. `feat: ...`, `fix(web): ...`, `docs: ...`, `chore: ...`.
- Branch names: `feat/<short-description>`, `fix/<short-description>`, `chore/<short-description>`.
- PRs: use `.github/pull_request_template.md`, include what changed + how you tested; add screenshots for UI changes.

## Security & Configuration Tips

- Keep secrets in `.env` (see `.env.example`) and never commit API keys.
- Avoid committing local artifacts (e.g., `meetinggenius.sqlite3*`, `.orch/`, generated session JSONs under `docs/`).
