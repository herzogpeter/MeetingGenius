from __future__ import annotations

import argparse
import asyncio
import os
from datetime import UTC, datetime

from dotenv import load_dotenv

from meetinggenius.board.reducer import apply_action
from meetinggenius.contracts import BoardState, ToolingPolicy, TranscriptEvent
from meetinggenius.task_seeding import auto_seed_research_tasks
from meetinggenius.tools.research import run_research_task


def main() -> None:
  load_dotenv()

  parser = argparse.ArgumentParser(prog="meetinggenius")
  sub = parser.add_subparsers(dest="cmd", required=True)

  sim = sub.add_parser("simulate", help="Run a single-turn simulation from a prompt string.")
  sim.add_argument("text", type=str, help="Simulated transcript text")
  sim.add_argument("--location", type=str, default="Seattle", help="Default location assumption")
  sim.add_argument("--no-browse", action="store_true", help="Disable external research tools")

  args = parser.parse_args()

  if args.cmd == "simulate":
    asyncio.run(_simulate(args.text, default_location=args.location, no_browse=args.no_browse))


async def _simulate(text: str, *, default_location: str, no_browse: bool) -> None:
  try:
    from meetinggenius.agents.board_planner import BoardPlannerDeps, build_board_planner_agent
    from meetinggenius.agents.orchestrator import (
      OrchestratorDeps,
      build_orchestrator_agent,
      format_transcript_window,
    )
  except ModuleNotFoundError as e:
    raise ModuleNotFoundError("Missing dependencies; run: `python -m pip install -e .`") from e

  model = os.getenv("MEETINGGENIUS_MODEL") or "openai:gpt-4o-mini"
  policy = ToolingPolicy(no_browse=no_browse)
  board_state = BoardState.empty()

  transcript = [
    TranscriptEvent(
      timestamp=datetime.now(tz=UTC),
      speaker="Participant",
      text=text,
      is_final=True,
    )
  ]

  orchestrator = build_orchestrator_agent(model)
  deps = OrchestratorDeps(policy=policy, default_location=default_location, board_state=board_state)
  user_prompt = format_transcript_window(transcript)
  decision = orchestrator.run_sync(user_prompt, deps=deps).output

  tasks = decision.research_tasks
  if not tasks:
    tasks = auto_seed_research_tasks(text, default_location=default_location)

  results = []
  for t in tasks:
    try:
      results.append(await run_research_task(t, no_browse=no_browse))
    except Exception as e:
      label = t.tool_name or t.kind
      print(f"[research:{label}] failed: {e}")

  planner = build_board_planner_agent(model)
  planner_deps = BoardPlannerDeps(
    policy=policy,
    board_state=board_state,
    orchestrator_decision=decision,
    research_results=results,
  )
  actions = planner.run_sync("Generate board actions for the current meeting context.", deps=planner_deps).output

  for a in actions:
    board_state = apply_action(board_state, a)

  print("BoardActions:")
  for a in actions:
    print(a.model_dump(mode="json"))
  print("\nBoardState cards:", list(board_state.cards.keys()))
