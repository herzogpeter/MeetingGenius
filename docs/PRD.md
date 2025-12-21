# PRD — AI-Powered Meeting Whiteboard (Prototype)

## Summary

Build a “silent meeting assistant” that listens to a live meeting and updates a shared digital whiteboard with helpful artifacts (charts, lists, tables, FAQs, checklists) based on the conversation, with citations and minimal disruption.

## Target users

- Product / engineering / leadership meetings where shared understanding and decisions matter.
- Facilitators who want better structure without constantly taking notes.

## Jobs-to-be-done

- “Help us align faster on what’s true / decided / next.”
- “Surface relevant data quickly when questions arise.”
- “Leave the meeting with a clean set of outcomes (decisions, actions, open questions).”

## Primary scenarios (prototype focus)

1) **Data question → chart**
   - Example: “What are local temperature trends in December this year?”
   - Expected: fetch historical Dec temps (past 10 years), render a trend chart card with assumptions + citations.

2) **Context question → list**
   - Example: “December weather headlines over the past five years might be interesting.”
   - Expected: fetch relevant headlines, render a bulleted list card with links, placed near the chart.

## Non-goals (prototype)

- Perfect speaker diarization, meeting minutes, or “always correct” summaries.
- Complex board layout algorithms beyond basic placement.
- Enterprise auth/compliance beyond basic consent + retention toggles.

## Functional requirements (MVP)

- Live transcript ingestion (streaming STT).
- Meeting orchestrator that proposes artifacts and research tasks from transcript windows.
- Research workers that fetch external data and return structured results with citations.
- Whiteboard that can create/update/move cards based on validated “BoardActions”.
- User controls: pin/lock, dismiss, and edit key assumptions (e.g., location).

## Non-functional requirements (MVP)

- Latency: first useful artifact within 60s of relevant discussion.
- Noise control: rate-limit new artifacts; dedupe similar ones.
- Trust: every data-driven artifact includes sources; clearly label assumptions.
- Privacy: explicit user consent to record; configurable retention; “no-browse” mode.

