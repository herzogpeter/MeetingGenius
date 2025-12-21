# Backlog (Prototype)

## Epics

1) Whiteboard UI (cards + layout)
2) Live transcript ingestion
3) PydanticAI orchestrator + state
4) Research tools/connectors (temps + headlines)
5) Board actions + validation pipeline
6) User controls (pin/lock/dismiss/edit assumptions)
7) Instrumentation + evaluation

## Milestone checklist

### Week 1 — Whiteboard + transcript

- [ ] Whiteboard canvas with card container + drag/resize
- [ ] `ChartCard` (line chart) + `ListCard` (bullets + links)
- [ ] Board state store + action reducer (`BoardAction` → `BoardState`)
- [ ] STT integration (streaming) + transcript panel
- [ ] Basic board placement rules (simple grid/pack; no fancy layout)
- [ ] User controls: dismiss card + pin/lock card

### Week 2 — PydanticAI orchestrator + research tools

- [ ] Pydantic models for events/tasks/results/actions
- [ ] Orchestrator loop with throttling + dedupe
- [ ] Research tool: weather history connector + caching + citations
- [ ] Research tool: headlines connector + caching + citations
- [ ] “No-browse mode” toggle that disables external research tools

### Week 3 — Board planning + evaluation

- [ ] Board planner: create vs update policy
- [ ] Board layout hints for “place next to related card”
- [ ] Telemetry: action counts, latency, user interactions
- [ ] Pilot sessions (5–10) with feedback capture

## Task pool (seed)

- Whiteboard canvas with card container + drag/resize
- `ChartCard` (line chart) + `ListCard` (bullets + links)
- Board state store + action reducer (`BoardAction` → `BoardState`)
- STT integration (streaming) + transcript panel
- Pydantic models for events/tasks/results/actions
- Orchestrator loop with throttling + dedupe
- Weather history connector + caching + citations
- Headlines connector + caching + citations
- Board planner: create vs update policy
- Telemetry: action counts, latency, user interactions
