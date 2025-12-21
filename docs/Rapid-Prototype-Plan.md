# Rapid Prototype Plan

Goal: prove feasibility + value with a narrow set of artifacts and real data connectors.

## Milestones

### Week 1 — Whiteboard + transcript

- Canvas/whiteboard UI with draggable/resizable “cards”.
- Card types (start small): `ChartCard`, `ListCard` (optionally `TableCard`).
- Board state store + basic placement.
- Microphone capture → streaming STT → transcript panel.

### Week 2 — PydanticAI orchestrator + research

- Define typed contracts: `TranscriptEvent`, `ResearchTask`, `ResearchResult`, `BoardAction`.
- Implement orchestrator loop (windowed transcript → proposals/tasks) with strict rate limits.
- Add 2 data connectors:
  - Historical temps (e.g., Open-Meteo / Meteostat).
  - Headlines (e.g., GDELT or a news API).
- Attach citations/links to every result.

### Week 3 — Board planning + evaluation

- Board planner converts research + proposals → validated `BoardAction`s.
- Iteration loop: update existing cards vs creating new ones (dedupe).
- Pilot tests (5–10 sessions), gather metrics, refine thresholds and UX controls.

## Demo script (two “wow” moments)

1) Ask for December temperature trends → chart card appears with cited data and location assumption.
2) Ask about December headlines over 5 years → list card appears next to chart with links.

