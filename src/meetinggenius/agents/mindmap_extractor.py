from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent

from meetinggenius.contracts import MindmapState, ToolingPolicy


@dataclass(frozen=True)
class MindmapExtractorDeps:
  policy: ToolingPolicy
  mindmap_state: MindmapState = field(default_factory=MindmapState.empty)


class MindmapPathProposal(BaseModel):
  model_config = ConfigDict(extra="forbid")

  path: list[str] = Field(
    description="A hierarchical path from a top-level topic down to a specific point. "
    "Example: ['Product launch', 'Timeline', 'Ship date moved to Friday'].",
    min_length=1,
    max_length=6,
  )


SYSTEM_PROMPT = """
You maintain a live mindmap of a meeting from streaming transcript text.

You will receive:
- a transcript window (some lines may be INTERIM / partial)
- a summary of the existing mindmap nodes

Your job:
- Propose NEW mindmap paths that should exist based on what was said.
- Keep it stable and low-noise: do not add nodes for incomplete/interim fragments.
- Prefer reusing existing node text exactly when it matches an existing topic (avoid near-duplicates).
- Each path should be short and readable (1-6 segments; each segment ideally 2-6 words, max 8).

Title quality rules:
- Each segment must be understandable standalone and include a concrete, specific noun.
- Rewrite transcript fragments into crisp summaries (<= 8 words) that stay faithful to what was said.
- Forbid vague filler words ("things", "stuff", "concepts", "matters", "nice", etc.), pronouns-only
  segments, or overly short fragments.
- When applicable, route under meeting-native buckets: Decisions / Action Items / Open Questions /
  Risks / Next Steps.
- Prefer fewer, higher-quality paths over many low-quality ones.

Rules:
- Do NOT delete, merge, or reparent nodes.
- Do NOT invent facts; only reflect what is in the transcript window.
- Stay conservative: if unsure, output fewer paths.
- Output MUST be strictly valid per the MindmapPathProposal schema (a JSON array).
""".strip()


def build_mindmap_extractor_agent(model: str) -> Agent[MindmapExtractorDeps, list[MindmapPathProposal]]:
  return Agent(
    model=model,
    output_type=list[MindmapPathProposal],
    system_prompt=SYSTEM_PROMPT,
    deps_type=MindmapExtractorDeps,
    retries=2,
    defer_model_check=True,
  )
