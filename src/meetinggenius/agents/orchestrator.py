from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_ai import Agent

from meetinggenius.contracts import BoardState, CardKind, OrchestratorDecision, ToolingPolicy, TranscriptEvent


@dataclass(frozen=True)
class OrchestratorDeps:
  policy: ToolingPolicy
  default_location: str | None = None
  board_state: BoardState = field(default_factory=BoardState.empty)


SYSTEM_PROMPT = """
You observe a live meeting transcript and decide what would be helpful to place on a shared whiteboard.

You will receive BOTH:
- a transcript window (what was said recently)
- a board-state summary (what cards already exist, including titles/kinds)

Core rules:
- Prefer usefulness over novelty; avoid distractions.
- Use the board-state summary to avoid duplicates: prefer updating an existing topic/card over proposing a new one.
- Be conservative with assumptions; when you infer something, record it in `assumptions`.

When to emit ResearchTasks:
- Emit ResearchTasks only when external data is explicitly requested or strongly implied (e.g., historical weather, facts, headlines).
- Do not emit research tasks for internal meeting artifacts (action items, decisions, brainstorming notes).
- If the needed data is already on the board and has sources, avoid repeating the task unless the meeting asks to refresh/expand it.

How to fill ResearchTask fields (be precise):
- `kind`:
  - `weather_december_history`: historical average temperatures by year for a location/month.
  - `december_headlines`: headlines/news for a topic/location in a December time window.
- `task_id`: stable and readable so proposals can reference it (prefer deterministic):
  - `weather:{Location}:{Month}:{Years}` (e.g., `weather:Seattle:12:10`)
  - `headlines:{TopicOrLocation}:{Month}:{Years}` (e.g., `headlines:Seattle weather:12:5`)
- `query`: a short, search-style query describing what to fetch (include month + metric/timeframe).
- `location`: set when location matters (weather always; headlines when the transcript implies locality).
  - If inferred, set it anyway and record `{"location_inferred": true, "location_value": "..."}`
- `month`: set when a month is mentioned; use `12` for December-related tasks.
- `years`: set when the transcript requests a time window; otherwise choose a reasonable default (10 weather, 5 headlines) and record it.

How to propose artifacts (board-friendly):
- Proposals should map cleanly to card kinds:
  - `kind="chart"` for numeric series data (weather history).
  - `kind="list"` for headline lists or meeting-derived lists.
- Use `required_tasks` to list the ResearchTask.task_id(s) needed for the proposal.
- If the board-state summary already shows the matching card, set `proposal_id` to the existing `card_id` (so the planner can update it).

Output must be strictly valid per the OrchestratorDecision schema.

Few-shot examples (structure only; do NOT copy text verbatim into your output):

Example A (weather history request → task + chart proposal)
{
  "research_tasks": [
    {
      "task_id": "weather:Seattle:12:10",
      "kind": "weather_december_history",
      "query": "Seattle December average temperature history (last 10 years)",
      "location": "Seattle",
      "month": 12,
      "years": 10,
      "assumptions": {}
    }
  ],
  "proposals": [
    {
      "proposal_id": "chart-weather-seattle-december",
      "title": "Seattle: Avg December Temp (Last 10 Years)",
      "kind": "chart",
      "rationale": "Makes the requested historical December temperature trend easy to see at a glance.",
      "priority": 80,
      "required_tasks": ["weather:Seattle:12:10"]
    }
  ]
}

Example B (headline request → task + list proposal)
{
  "research_tasks": [
    {
      "task_id": "headlines:AI:12:5",
      "kind": "december_headlines",
      "query": "major AI headlines December (last 5 years)",
      "month": 12,
      "years": 5,
      "assumptions": {"scope": "global", "limit": 10}
    }
  ],
  "proposals": [
    {
      "proposal_id": "list-headlines-ai-december",
      "title": "Major AI Headlines (Recent Decembers)",
      "kind": "list",
      "rationale": "Captures the referenced headlines as a scannable list with sources.",
      "priority": 70,
      "required_tasks": ["headlines:AI:12:5"]
    }
  ]
}
""".strip()


def build_orchestrator_agent(model: str) -> Agent[OrchestratorDeps, OrchestratorDecision]:
  return Agent(
    model=model,
    output_type=OrchestratorDecision,
    system_prompt=SYSTEM_PROMPT,
    deps_type=OrchestratorDeps,
    retries=2,
    defer_model_check=True,
  )


def format_transcript_window(events: list[TranscriptEvent]) -> str:
  lines: list[str] = []
  for e in events:
    who = f"{e.speaker}: " if e.speaker else ""
    lines.append(f"- [{e.timestamp.isoformat()}] {who}{e.text}")
  return "\n".join(lines)


def format_board_state_summary(state: BoardState, *, max_cards: int = 25, max_dismissed: int = 10) -> str:
  """Summarize the current board so the model can update instead of duplicating cards."""
  if not state.cards and not state.dismissed:
    return "(empty board)"

  lines: list[str] = []

  if state.cards:
    lines.append("Existing cards (use update_card with card_id to modify these):")
    items = list(state.cards.items())
    items.sort(
      key=lambda kv: (
        str(getattr(kv[1], "kind", "")),
        str(getattr(getattr(kv[1], "props", None), "title", "")),
        kv[0],
      )
    )
    for i, (card_id, card) in enumerate(items[:max_cards], start=1):
      title = getattr(getattr(card, "props", None), "title", None) or ""
      sources = getattr(card, "sources", None) or []
      if getattr(card, "kind", None) == CardKind.CHART:
        props = card.props  # type: ignore[attr-defined]
        lines.append(
          f"- {card_id} [chart] {title!r} (points={len(props.points)}, y_label={props.y_label!r}, sources={len(sources)})"
        )
      else:
        props = card.props  # type: ignore[attr-defined]
        lines.append(f"- {card_id} [list] {title!r} (items={len(props.items)}, sources={len(sources)})")

    remaining = len(items) - max_cards
    if remaining > 0:
      lines.append(f"- …and {remaining} more cards not shown")

  if state.dismissed:
    lines.append("Dismissed cards (avoid recreating unless explicitly requested):")
    dismissed_items = sorted(state.dismissed.items(), key=lambda kv: kv[0])
    for card_id, reason in dismissed_items[:max_dismissed]:
      reason_str = f" — {reason}" if reason else ""
      lines.append(f"- {card_id}{reason_str}")
    remaining = len(dismissed_items) - max_dismissed
    if remaining > 0:
      lines.append(f"- …and {remaining} more dismissed cards not shown")

  return "\n".join(lines).strip()
