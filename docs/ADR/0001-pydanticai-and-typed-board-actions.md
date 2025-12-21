# ADR 0001 — PydanticAI + Typed Board Actions

## Context

The product requires the AI system to update a live whiteboard reliably. Unbounded generation (arbitrary UI/code) creates instability, safety issues, and makes failures hard to debug.

## Decision

- Use **PydanticAI** for the orchestrator and research workflows.
- Constrain the AI to emitting **schema-validated `BoardAction`s** which deterministically update `BoardState` via a reducer.

## Alternatives considered

- Claude Agent SDK for end-to-end orchestration.
- Multiple “UI generating agents” producing arbitrary React/components.

## Consequences

- Increased up-front schema/design work, but far better reliability and testability.
- Rendering stays deterministic; the AI only chooses components and fills props via validated actions.

