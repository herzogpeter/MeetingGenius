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

Rules:
- Prefer updating existing cards (same topic) over creating new ones.
- Prefer `update_card` over `create_card` unless it's truly a new topic (creates may be throttled/de-duped by the backend).
- Never create a chart/list that implies factual data without citations.
- Include citations in created cards via card.sources and in updates via citations when relevant.
- Output must be a list of BoardAction objects (schema validated).
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
