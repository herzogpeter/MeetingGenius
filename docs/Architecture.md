# Architecture (Prototype)

## Overview

Event-driven system with a single source of truth for the board state.

1) **Streaming STT** produces `TranscriptEvent`s.
2) **Orchestrator (PydanticAI agent)** maintains compact meeting state and emits:
   - `ResearchTask`s (fetch data),
   - `ArtifactProposal`s (candidate cards to show/update).
3) **Research workers (tools)** execute tasks, returning `ResearchResult`s with citations.
4) **Board planner** converts proposals + results into validated `BoardAction`s.
5) **Renderer** deterministically renders from `BoardState`.

## Why PydanticAI

- Typed models for all boundaries (safer, testable, debuggable).
- Tool inputs/outputs validated with Pydantic (reject/repair invalid actions).
- Clear separation between “model reasoning” and “deterministic rendering”.

## Core contracts (draft)

- `TranscriptEvent`: `{ ts, speaker?, text, confidence? }`
- `ResearchTask`: `{ id, kind, query, constraints, assumptions }`
- `ResearchResult`: `{ task_id, data, citations, fetched_at }`
- `ArtifactProposal`: `{ kind, title, rationale, priority, required_tasks[] }`
- `BoardAction`:
  - `create_card({ card_id, kind, props, sources, layout_hint })`
  - `update_card({ card_id, patch, sources? })`
  - `move_card({ card_id, x, y, w, h })`
  - `dismiss_card({ card_id, reason })`

## Reference implementation (draft)

- `src/meetinggenius/contracts.py`
- `src/meetinggenius/board/reducer.py`

## Safety rails

- Rate-limit actions; dedupe by semantic similarity.
- Require citations for data cards; label assumptions.
- “No-browse” mode restricts research tools to approved sources.
