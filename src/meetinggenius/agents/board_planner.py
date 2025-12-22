from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_ai import Agent

from meetinggenius.contracts import BoardAction, BoardState, OrchestratorDecision, ResearchResult, ToolingPolicy


@dataclass(frozen=True)
class BoardPlannerDeps:
  policy: ToolingPolicy
  board_state: BoardState = field(default_factory=BoardState.empty)
  orchestrator_decision: OrchestratorDecision = field(default_factory=OrchestratorDecision)
  research_results: list[ResearchResult] = field(default_factory=list)


SYSTEM_PROMPT = """
You convert orchestrator proposals and research results into concrete BoardActions.

You will receive BOTH:
- a transcript window and a board-state summary (what cards already exist)
- an orchestrator decision (proposals + research_tasks)
- research results (including citations)

Reliability rules:
- Avoid card spam: prefer updating an existing card over creating a new one.
  - If `proposal_id` matches an existing `card_id`, update that card.
  - Otherwise, match by same kind + similar title/topic and update when reasonable.
- Prefer `update_card` over `create_card` unless it's truly a new topic (creates may be throttled/de-duped by the backend).
- Never fabricate factual data. If a proposal requires research but the required research results are missing, do not invent numbers or headlines.
- Any externally sourced factual chart/list MUST include citations in the card (`card.sources`). For updates, also patch `sources` and include `UpdateCardAction.citations`.
- Output must be a JSON array that schema-validates as a list of BoardAction objects.

Mapping rules (research → card props):
- WeatherHistoryData → Chart card
  - props.points: one point per year: `{ "label": "<year>", "value": <avg_temp_f> }`
  - Use a single unit consistently:
    - Fahrenheit: `value = avg_temp_f` and set `props.y_label = "Avg Temp (°F)"`
    - Celsius: `value = avg_temp_c` and set `props.y_label = "Avg Temp (°C)"`
  - Sort points by year ascending.
  - Attach `ResearchResult.citations` as `card.sources` (dedupe by URL if you can).

- HeadlinesData → List card
  - props.items: one per headline:
    - `text = title`
    - `url = url`
    - `meta = "<source> · <YYYY-MM-DD>"` (omit missing parts)
  - Attach `ResearchResult.citations` as `card.sources`.

Updates:
- Use `UpdateCardAction.patch` as a deep-merge dict (e.g., `{ "props": { ... }, "sources": [ ... ] }`).
- For research-driven updates, set `UpdateCardAction.citations` to the same citation list you used for `sources`.

Non-research meeting lists:
- You may create/update list cards derived from the transcript (e.g., action items, decisions) without citations.
- Do not make them sound like externally verified facts.

Few-shot examples (structure only; do NOT copy text verbatim into your output):

Example A (weather result → create chart card)
[
  {
    "type": "create_card",
    "card": {
      "card_id": "chart-weather-seattle-december",
      "kind": "chart",
      "props": {
        "title": "Seattle: Avg December Temp (Last 10 Years)",
        "x_label": "Year",
        "y_label": "Avg Temp (°F)",
        "points": [
          {"label": "2015", "value": 42.1},
          {"label": "2016", "value": 41.8}
        ]
      },
      "sources": [{"url": "https://example.com/weather", "title": "Historical climate normals"}]
    }
  }
]

Example B (existing list card → update items + sources from headlines research)
[
  {
    "type": "update_card",
    "card_id": "list-headlines-ai-december",
    "patch": {
      "props": {
        "title": "Major AI Headlines (Recent Decembers)",
        "items": [
          {"text": "Example headline", "url": "https://example.com/news", "meta": "Example Source · 2020-12-10"}
        ]
      },
      "sources": [{"url": "https://example.com/citations", "title": "News search results"}]
    },
    "citations": [{"url": "https://example.com/citations", "title": "News search results"}]
  }
]
""".strip()


def build_board_planner_agent(model: str) -> Agent[BoardPlannerDeps, list[BoardAction]]:
  return Agent(
    model=model,
    output_type=list[BoardAction],
    system_prompt=SYSTEM_PROMPT,
    deps_type=BoardPlannerDeps,
    retries=2,
    defer_model_check=True,
  )
