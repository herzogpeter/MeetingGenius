from __future__ import annotations

import asyncio
import json
import os
import re
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from meetinggenius.board.reducer import apply_action
from meetinggenius.contracts import (
  BoardAction,
  BoardState,
  CreateCardAction,
  ToolingPolicy,
  TranscriptEvent,
  UpdateCardAction,
)
from meetinggenius.task_seeding import auto_seed_research_tasks
from meetinggenius.tools.research import run_research_task

app = FastAPI(title="MeetingGenius Realtime Backend")


def _env_bool(name: str, default: bool = False) -> bool:
  val = os.getenv(name)
  if val is None:
    return default
  return val.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
  val = os.getenv(name)
  if val is None:
    return default
  try:
    return int(val)
  except ValueError:
    return default


def _env_float(name: str, default: float) -> float:
  val = os.getenv(name)
  if val is None:
    return default
  try:
    return float(val)
  except ValueError:
    return default


def _actions_to_json(actions: list[BoardAction]) -> list[dict[str, Any]]:
  return [a.model_dump(mode="json") for a in actions]


def _state_to_json(state: BoardState) -> dict[str, Any]:
  return state.model_dump(mode="json")


def _normalize_title(value: str) -> str:
  cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower())
  return " ".join(cleaned.split())


def _title_similarity(a: str, b: str) -> float:
  a_norm = _normalize_title(a)
  b_norm = _normalize_title(b)
  if not a_norm or not b_norm:
    return 0.0
  if a_norm == b_norm:
    return 1.0
  a_tokens = set(a_norm.split())
  b_tokens = set(b_norm.split())
  if not a_tokens or not b_tokens:
    return 0.0
  return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def _very_similar_title(a: str, b: str) -> bool:
  a_norm = _normalize_title(a)
  b_norm = _normalize_title(b)
  if not a_norm or not b_norm:
    return False
  if a_norm == b_norm:
    return True

  if _title_similarity(a_norm, b_norm) >= 0.85:
    return True

  if (a_norm in b_norm or b_norm in a_norm) and min(len(a_norm), len(b_norm)) >= 12:
    return True

  a_tokens = set(a_norm.split())
  b_tokens = set(b_norm.split())
  overlap = len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens))
  return overlap >= 0.9


def _card_title_for_match(card: Any) -> str:
  props = getattr(card, "props", None)
  title = getattr(props, "title", None)
  return title if isinstance(title, str) else ""


def _find_similar_card_id(state: BoardState, *, kind: Any, title: str) -> str | None:
  best_id: str | None = None
  best_score = 0.0
  for card_id, card in state.cards.items():
    if getattr(card, "kind", None) != kind:
      continue
    existing_title = _card_title_for_match(card)
    if not existing_title:
      continue
    if not _very_similar_title(existing_title, title):
      continue
    score = _title_similarity(existing_title, title)
    if score > best_score:
      best_id = card_id
      best_score = score
  return best_id


@dataclass
class RealtimeState:
  clients: set[WebSocket] = field(default_factory=set)
  clients_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

  transcript: deque[tuple[float, TranscriptEvent]] = field(default_factory=deque)
  board_state: BoardState = field(default_factory=BoardState.empty)
  version: int = 0
  state_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

  ai_runner: "AIRunner" | None = None

  async def add_client(self, ws: WebSocket) -> None:
    async with self.clients_lock:
      self.clients.add(ws)

  async def remove_client(self, ws: WebSocket) -> None:
    async with self.clients_lock:
      self.clients.discard(ws)

  async def broadcast(self, payload: dict[str, Any]) -> None:
    async with self.clients_lock:
      clients = list(self.clients)

    to_remove: list[WebSocket] = []
    for ws in clients:
      try:
        await ws.send_json(payload)
      except Exception:
        to_remove.append(ws)

    if to_remove:
      async with self.clients_lock:
        for ws in to_remove:
          self.clients.discard(ws)

  async def status(self, message: str) -> None:
    await self.broadcast({"type": "status", "message": message})

  async def error(self, message: str, *, details: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"type": "error", "message": message}
    if details is not None:
      payload["details"] = details
    await self.broadcast(payload)

  async def reset(self) -> None:
    async with self.state_lock:
      self.transcript.clear()
      self.board_state = BoardState.empty()
      self.version += 1
    await self.status("State reset.")
    await self.broadcast({"type": "board_actions", "actions": [], "state": _state_to_json(BoardState.empty())})

  async def add_transcript_event(self, event: TranscriptEvent) -> None:
    max_events = _env_int("MEETINGGENIUS_TRANSCRIPT_MAX_EVENTS", 50)
    max_seconds = _env_int("MEETINGGENIUS_TRANSCRIPT_MAX_SECONDS", 120)

    now = time.time()
    cutoff = now - max_seconds

    async with self.state_lock:
      self.transcript.append((now, event))
      while self.transcript and self.transcript[0][0] < cutoff:
        self.transcript.popleft()
      while len(self.transcript) > max_events:
        self.transcript.popleft()

  async def snapshot(self) -> tuple[int, list[TranscriptEvent], BoardState]:
    async with self.state_lock:
      version = self.version
      events = [e for _, e in self.transcript]
      state = self.board_state
    return version, events, state

  async def apply_board_actions(self, *, expected_version: int, actions: list[BoardAction]) -> BoardState | None:
    async with self.state_lock:
      if self.version != expected_version:
        return None
      next_state = self.board_state
      for action in actions:
        next_state = apply_action(next_state, action)
      self.board_state = next_state
      return next_state


class AIRunner:
  def __init__(self, state: RealtimeState) -> None:
    self._state = state
    self._min_interval_s = _env_float("MEETINGGENIUS_AI_MIN_INTERVAL_SECONDS", 10.0)
    self._lock = asyncio.Lock()
    self._task: asyncio.Task[None] | None = None
    self._pending = False
    self._last_started_at = 0.0
    self._create_timestamps: deque[float] = deque()
    self._last_create_at = 0.0

  async def request(self) -> None:
    async with self._lock:
      self._pending = True
      if self._task is None or self._task.done():
        self._task = asyncio.create_task(self._run_loop())

  async def _run_loop(self) -> None:
    while True:
      async with self._lock:
        if not self._pending:
          return
        self._pending = False
        delay = max(0.0, self._min_interval_s - (time.time() - self._last_started_at))

      if delay > 0:
        await asyncio.sleep(delay)

      self._last_started_at = time.time()
      try:
        await self._run_once()
      except Exception as e:
        await self._state.error(
          "AI loop failed.",
          details={"error": str(e), "traceback": traceback.format_exc(limit=25)},
        )

  async def _run_once(self) -> None:
    version, events, board_state = await self._state.snapshot()
    if not events:
      return

    await self._state.status("Running orchestrator…")

    model = os.getenv("MEETINGGENIUS_MODEL") or "openai:gpt-4o-mini"
    default_location = os.getenv("MEETINGGENIUS_DEFAULT_LOCATION") or "Seattle"
    no_browse = _env_bool("MEETINGGENIUS_NO_BROWSE", False)
    policy = ToolingPolicy(no_browse=no_browse)

    try:
      from meetinggenius.agents.board_planner import BoardPlannerDeps, build_board_planner_agent
      from meetinggenius.agents.orchestrator import (
        OrchestratorDeps,
        build_orchestrator_agent,
        format_board_state_summary,
        format_transcript_window,
      )
    except ModuleNotFoundError as e:
      raise ModuleNotFoundError("Missing AI dependencies; run: `python -m pip install -e .`") from e

    transcript_window = format_transcript_window(events)
    board_summary = format_board_state_summary(board_state)
    orchestrator = build_orchestrator_agent(model)
    orchestrator_deps = OrchestratorDeps(
      policy=policy,
      default_location=default_location,
      board_state=board_state,
    )
    orchestrator_prompt = "\n".join(
      [
        "Meeting transcript window:",
        transcript_window,
        "",
        "Current board state:",
        board_summary,
        "",
        "Noise controls:",
        "- Prefer updating existing cards; avoid creating new ones unless it's a truly new topic.",
        "- The backend may throttle or convert `create_card` actions to reduce duplicates.",
        "",
        "Return a valid OrchestratorDecision for this context.",
      ]
    ).strip()
    decision = await asyncio.to_thread(
      lambda: orchestrator.run_sync(orchestrator_prompt, deps=orchestrator_deps).output
    )

    tasks = decision.research_tasks
    if not tasks:
      combined_text = "\n".join(e.text for e in events if e.text)
      tasks = auto_seed_research_tasks(combined_text, default_location=default_location)

    results = []
    if tasks:
      await self._state.status(f"Research tasks: {len(tasks)}")

    for task in tasks:
      try:
        results.append(await run_research_task(task, no_browse=no_browse))
      except Exception as e:
        await self._state.status(f"Research failed for {task.kind}: {e}")

    await self._state.status("Running board planner…")
    planner = build_board_planner_agent(model)
    planner_deps = BoardPlannerDeps(
      policy=policy,
      board_state=board_state,
      orchestrator_decision=decision,
      research_results=results,
    )
    planner_prompt = "\n".join(
      [
        "Meeting transcript window:",
        transcript_window,
        "",
        "Current board state:",
        board_summary,
        "",
        "Noise controls:",
        "- Prefer `update_card` over `create_card` when possible.",
        "- Creating new cards is rate-limited; some creates may be dropped.",
        "- Similar-title creates may be converted into updates.",
        "",
        "Orchestrator decision (JSON):",
        decision.model_dump_json(indent=2),
        "",
        "Research results (JSON):",
        json.dumps([r.model_dump(mode="json") for r in results], indent=2),
        "",
        "Output a JSON array that schema-validates as a list of BoardAction objects.",
      ]
    ).strip()
    if no_browse:
      planner_prompt += "\n\nNote: external research is disabled; avoid creating factual external-data cards."
    actions = await asyncio.to_thread(
      lambda: planner.run_sync(planner_prompt, deps=planner_deps).output
    )

    processed_actions, throttle_msg, next_timestamps, next_last_create = self._post_process_actions(
      board_state, actions
    )

    next_state = await self._state.apply_board_actions(expected_version=version, actions=processed_actions)
    if next_state is None:
      await self._state.status("Discarded AI result (state changed).")
      return

    self._create_timestamps = next_timestamps
    self._last_create_at = next_last_create
    if throttle_msg:
      await self._state.status(throttle_msg)

    await self._state.broadcast(
      {
        "type": "board_actions",
        "actions": _actions_to_json(processed_actions),
        "state": _state_to_json(next_state),
      }
    )

  def _post_process_actions(
    self, board_state: BoardState, actions: list[BoardAction]
  ) -> tuple[list[BoardAction], str | None, deque[float], float]:
    dedupe_enabled = _env_bool("MEETINGGENIUS_DEDUPE_TITLE_SIMILARITY", True)
    max_per_minute = _env_int("MEETINGGENIUS_MAX_CREATE_CARDS_PER_MINUTE", 2)
    min_between_s = _env_float("MEETINGGENIUS_MIN_SECONDS_BETWEEN_CREATES", 20.0)

    deduped: list[BoardAction] = []
    for action in actions:
      if not dedupe_enabled or not isinstance(action, CreateCardAction):
        deduped.append(action)
        continue

      card = action.card
      title = _card_title_for_match(card)
      if not title:
        deduped.append(action)
        continue

      similar_id = _find_similar_card_id(board_state, kind=getattr(card, "kind", None), title=title)
      if similar_id is None:
        deduped.append(action)
        continue

      patch: dict[str, Any] = {"props": card.props.model_dump(mode="python")}
      if getattr(card, "sources", None):
        patch["sources"] = [c.model_dump(mode="python") for c in card.sources]
      deduped.append(
        UpdateCardAction(
          card_id=similar_id,
          patch=patch,
          citations=card.sources if getattr(card, "sources", None) else None,
        )
      )

    now = time.time()
    next_timestamps = deque(self._create_timestamps)
    while next_timestamps and now - next_timestamps[0] > 60.0:
      next_timestamps.popleft()
    next_last_create = self._last_create_at

    throttled = 0
    output: list[BoardAction] = []
    for action in deduped:
      if not isinstance(action, CreateCardAction):
        output.append(action)
        continue

      if min_between_s > 0 and now - next_last_create < min_between_s:
        throttled += 1
        continue

      if max_per_minute <= 0 or len(next_timestamps) >= max_per_minute:
        throttled += 1
        continue

      output.append(action)
      next_timestamps.append(now)
      next_last_create = now

    msg = None
    if throttled:
      msg = (
        f"Throttled {throttled} create_card action(s) "
        f"(max {max_per_minute}/min, min {int(min_between_s)}s between creates)."
      )

    return output, msg, next_timestamps, next_last_create


STATE = RealtimeState()
STATE.ai_runner = AIRunner(STATE)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
  await ws.accept()
  await STATE.add_client(ws)
  try:
    await ws.send_json({"type": "status", "message": "Connected."})
    _, _, board_state = await STATE.snapshot()
    await ws.send_json({"type": "board_actions", "actions": [], "state": _state_to_json(board_state)})

    while True:
      data = await ws.receive_json()
      if not isinstance(data, dict):
        await ws.send_json({"type": "error", "message": "Invalid message; expected JSON object."})
        continue

      msg_type = data.get("type")
      if msg_type == "ping":
        await ws.send_json({"type": "pong"})
        continue

      if msg_type == "reset":
        await STATE.reset()
        continue

      if msg_type == "transcript_event":
        try:
          event = TranscriptEvent.model_validate(data.get("event"))
        except ValidationError as e:
          await ws.send_json(
            {
              "type": "error",
              "message": "Invalid transcript_event payload.",
              "details": {"errors": e.errors()},
            }
          )
          continue

        await STATE.add_transcript_event(event)
        if event.is_final and STATE.ai_runner is not None:
          await STATE.ai_runner.request()
        continue

      await ws.send_json(
        {"type": "error", "message": f"Unknown message type: {msg_type!r}", "details": {"type": msg_type}}
      )

  except WebSocketDisconnect:
    pass
  finally:
    await STATE.remove_client(ws)
