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

Rules:
- Prefer usefulness over novelty; avoid distractions.
- Use the board-state summary to avoid duplicates: prefer updating an existing topic/card over proposing a new one.
- Prefer updating existing cards; avoid proposing new ones unless it's truly a new topic (the backend may throttle/de-dupe creates).
- Propose research tasks only when a question/data-need is explicit or strongly implied.
- When creating ResearchTasks, set fields deliberately:
  - kind:
    - weather_december_history: when people want historical December weather by year (e.g., "last 10 years").
    - december_headlines: when people want notable headlines/news for a given December time period/topic.
  - query: a short, specific search-style query; include the metric and timeframe.
  - location: only for weather tasks; default to the meeting's default location if the user doesn't specify.
  - month: use 12 for December-related tasks when applicable.
  - years: set to a small integer window when "last N years" is requested (e.g., 5, 10); otherwise omit.
  - assumptions: include any inferred choices (units C/F, "monthly average", what counts as "major headlines", etc.).
- Be conservative with assumptions; when unsure, include the assumption in the task/proposal.
- Proposals should be board-friendly and map cleanly to card kinds:
  - kind=chart for time-series style numeric data (e.g., weather history by year).
  - kind=list for headline lists or meeting notes.
- Output must be strictly valid per the OrchestratorDecision schema.

Few-shot examples (for structure only; values are illustrative):

Example A (weather history request → task + chart proposal):
{
  "research_tasks": [
    {
      "task_id": "wx_dec_hist_seattle_10y",
      "kind": "weather_december_history",
      "query": "Average December temperature in Seattle by year (last 10 years)",
      "location": "Seattle, WA",
      "month": 12,
      "years": 10,
      "assumptions": {"units": "F", "definition": "monthly average temperature"}
    }
  ],
  "proposals": [
    {
      "proposal_id": "chart_dec_temp_seattle_10y",
      "title": "Seattle: Avg December Temperature (Last 10 Years)",
      "kind": "chart",
      "rationale": "Supports discussion about winter temperature trends with a simple by-year chart.",
      "priority": 80,
      "required_tasks": ["wx_dec_hist_seattle_10y"]
    }
  ]
}

Example B (headline request → task + list proposal):
{
  "research_tasks": [
    {
      "task_id": "headlines_dec_2020_ai",
      "kind": "december_headlines",
      "query": "major AI headlines December 2020",
      "month": 12,
      "assumptions": {"scope": "global", "limit": 10}
    }
  ],
  "proposals": [
    {
      "proposal_id": "list_headlines_dec_2020_ai",
      "title": "Major AI Headlines (Dec 2020)",
      "kind": "list",
      "rationale": "Captures the referenced headlines as a scannable list with sources.",
      "priority": 70,
      "required_tasks": ["headlines_dec_2020_ai"]
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


def format_board_state_summary(state: BoardState) -> str:
  if not state.cards and not state.dismissed:
    return "Board is empty (no active or dismissed cards)."

  lines: list[str] = []
  if state.cards:
    lines.append("Active cards:")
    for card_id, card in sorted(state.cards.items(), key=lambda kv: kv[0]):
      title = getattr(getattr(card, "props", None), "title", "")
      sources = getattr(card, "sources", None)
      sources_count = len(sources) if isinstance(sources, list) else 0

      detail = ""
      kind = getattr(getattr(card, "kind", None), "value", None) or str(getattr(card, "kind", ""))
      if kind == "chart":
        points = getattr(getattr(card, "props", None), "points", None)
        y_label = getattr(getattr(card, "props", None), "y_label", None)
        points_count = len(points) if isinstance(points, list) else 0
        detail = f", points={points_count}, y_label={y_label!r}"
      elif kind == "list":
        items = getattr(getattr(card, "props", None), "items", None)
        items_count = len(items) if isinstance(items, list) else 0
        detail = f", items={items_count}"

      lines.append(f'- {card_id} ({kind}) title="{title}"{detail}, sources={sources_count}')

  if state.dismissed:
    lines.append("")
    lines.append("Dismissed cards:")
    for card_id, reason in sorted(state.dismissed.items(), key=lambda kv: kv[0]):
      reason_str = reason.strip() if isinstance(reason, str) else ""
      lines.append(f"- {card_id} reason={reason_str!r}")

  return "\n".join(lines).strip()
