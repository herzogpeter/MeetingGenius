## Codex-Orch Pilot (Local Loop)
- Boss reads `.codex-orch.yaml`, then spawns worker jobs with scoped objectives and inputs.
- Workers run inside `.orch/runs/<run-id>/jobs/<job-id>/wt`, make minimal changes, and never commit.
- `patch_allowlist` is `docs/**` for this pilot; workers must not edit outside that tree.
- `allowed_commands` is limited (e.g., `python`, `pytest`, `rg`, `git diff`) and network access may be restricted.
- Workers leave changes unstaged; the orchestrator captures results via `git diff` and attaches patches to artifacts.
- Artifacts/logs land under `artifact_dir=.orch` alongside run metadata and job outputs.
- Backend dev: `uvicorn meetinggenius.server:app --reload --port 8000` (WebSocket at `/ws`).
- Frontend dev: `cd apps/web && npm install && npm run dev` (Vite).
- Quick CLI/smoke: `python -m meetinggenius simulate ...` and `python smoke_ws.py` against the WS URL.
