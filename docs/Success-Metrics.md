# Success Metrics (Go/No-Go)

## Product signals

- **Time-to-first-useful-card**: < 60s after a relevant question/topic begins.
- **Utility**: ≥ 70% of sessions pin at least one card.
- **Noise**: < 10% of created cards dismissed as “not helpful”.
- **Correction burden**: users change assumptions (e.g., location) in ≤ 20% of sessions.

## Trust signals

- 100% of data-driven artifacts show **citations/links** and **assumptions**.
- 0 charts rendered from uncited or fabricated datasets.

## System signals

- Update rate: default ≤ 2 new cards/minute.
- Stability: no invalid `BoardAction` reaches the renderer (schema validated).

## Evaluation plan

- Run 5–10 real meetings with consent.
- Log:
  - created/updated/dismissed/pinned cards,
  - latency from transcript event → artifact,
  - which connectors/tools were used,
  - user feedback (1–2 questions post-meeting).

