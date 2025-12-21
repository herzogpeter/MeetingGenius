# Risks and Mitigations (Prototype)

## Value risks

- **Too noisy / distracting** → strict throttles, dedupe, “draft” mode, easy dismiss/pin.
- **Not trusted** → citations required; separate “generated text” from “retrieved data”; assumptions visible/editable.
- **Wrong context (location, timeframe)** → conservative defaults + explicit assumption UI.

## Technical risks

- **Latency too high** → cache, limit tool calls, incremental updates, local-first rendering.
- **Competing agents cause conflicts** → single orchestrator + typed `BoardAction` reducer.
- **Hallucinated structure** → schema validation + repair loops; reject unsafe actions.

## Privacy risks

- **Recording sensitivity** → explicit consent, retention controls, “no-browse” mode, minimize stored audio.

