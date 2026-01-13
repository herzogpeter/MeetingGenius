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
from pydantic import TypeAdapter, ValidationError

from meetinggenius.board.reducer import apply_action
from meetinggenius.agents.orchestrator import MEETING_NATIVE_LIST_CARD_IDS
from meetinggenius.contracts import (
  BoardAction,
  BoardState,
  CardKind,
  CreateCardAction,
  ListItem,
  ListCard,
  ListCardProps,
  Rect,
  ToolingPolicy,
  TranscriptEvent,
  UpdateCardAction,
)
from meetinggenius.sqlite_store import (
  BOARD_STATE_KEY,
  DEFAULT_LOCATION_KEY,
  NO_BROWSE_KEY,
  DebouncedStatePersister,
  SQLiteKVStore,
  load_board_state,
  load_default_location,
  load_no_browse,
  resolve_db_path,
)
from meetinggenius.task_seeding import auto_seed_research_tasks
from meetinggenius.tools.research import run_research_task

app = FastAPI(title="MeetingGenius Realtime Backend")

PERSIST_STORE: SQLiteKVStore | None = None
PERSISTOR: DebouncedStatePersister | None = None

MEETING_NATIVE_BASE_LIST_CARDS: tuple[tuple[str, str], ...] = (
  ("list-decisions", "Decisions"),
  ("list-actions", "Action Items"),
  ("list-questions", "Open Questions"),
  ("list-risks", "Risks / Blockers"),
  ("list-next-steps", "Next Steps"),
)
MEETING_NATIVE_BASE_LIST_CARD_IDS = MEETING_NATIVE_LIST_CARD_IDS


def _meeting_native_seed_rect(index: int) -> Rect:
  # Mirror the frontend's 2-column auto layout.
  gutter = 16
  w = 420
  h = 280
  col_width = w + gutter
  row_height = h + gutter
  col = index % 2
  row = index // 2
  return Rect(x=gutter + col * col_width, y=gutter + row * row_height, w=w, h=h)


def _meeting_native_seed_actions(board_state: BoardState, actions: list[BoardAction]) -> list[CreateCardAction]:
  create_ids = {action.card.card_id for action in actions if isinstance(action, CreateCardAction)}
  referenced_ids: set[str] = set()
  for action in actions:
    if isinstance(action, UpdateCardAction) and action.card_id in MEETING_NATIVE_BASE_LIST_CARD_IDS:
      referenced_ids.add(action.card_id)
    elif isinstance(action, CreateCardAction) and action.card.card_id in MEETING_NATIVE_BASE_LIST_CARD_IDS:
      referenced_ids.add(action.card.card_id)

  if not referenced_ids:
    return []

  seeded: list[CreateCardAction] = []
  for idx, (card_id, title) in enumerate(MEETING_NATIVE_BASE_LIST_CARDS):
    if card_id not in referenced_ids:
      continue
    if card_id in create_ids:
      continue
    if card_id in board_state.cards:
      continue
    if card_id in board_state.dismissed:
      continue
    seeded.append(
      CreateCardAction(
        card=ListCard(
          card_id=card_id,
          kind=CardKind.LIST,
          props=ListCardProps(title=title, items=[]),
          sources=[],
        ),
        rect=_meeting_native_seed_rect(idx),
      )
    )
  return seeded


def _normalize_list_item_text(value: str) -> str:
  cleaned = value.strip().lower()
  cleaned = re.sub(r"^[\s\-\*\u2022\d\)\.]+", "", cleaned)
  cleaned = re.sub(r"\s+", " ", cleaned).strip()
  cleaned = cleaned.strip(" \t\r\n.;")
  return cleaned


def _extract_meeting_native_items(events: list[TranscriptEvent]) -> dict[str, list[str]]:
  buckets: dict[str, list[str]] = {card_id: [] for card_id, _ in MEETING_NATIVE_BASE_LIST_CARDS}

  patterns: list[tuple[str, re.Pattern[str]]] = [
    ("list-decisions", re.compile(r"^\s*(?:decision|decisions)\s*[:\-–]\s*(.+)$", re.IGNORECASE)),
    ("list-actions", re.compile(r"^\s*(?:action item|action items|action)\s*[:\-–]\s*(.+)$", re.IGNORECASE)),
    ("list-questions", re.compile(r"^\s*(?:open question|open questions|question|questions)\s*[:\-–]\s*(.+)$", re.IGNORECASE)),
    ("list-risks", re.compile(r"^\s*(?:risk|risks|blocker|blockers|risk\s*/\s*blocker)\s*[:\-–]\s*(.+)$", re.IGNORECASE)),
    ("list-next-steps", re.compile(r"^\s*(?:next step|next steps)\s*[:\-–]\s*(.+)$", re.IGNORECASE)),
  ]

  for event in events:
    text = event.text or ""
    if not text.strip():
      continue
    for raw_line in text.splitlines():
      line = raw_line.strip()
      if not line:
        continue
      for card_id, pattern in patterns:
        match = pattern.match(line)
        if not match:
          continue
        item = match.group(1).strip()
        if item:
          buckets[card_id].append(item)
        break

  return {card_id: items for card_id, items in buckets.items() if items}


def _meeting_native_update_actions(
  board_state: BoardState, items_by_card_id: dict[str, list[str]], *, max_new_items: int = 5
) -> list[UpdateCardAction]:
  remaining = max(0, max_new_items)
  if remaining == 0:
    return []

  updates: list[UpdateCardAction] = []
  for card_id in (cid for cid, _ in MEETING_NATIVE_BASE_LIST_CARDS):
    if remaining <= 0:
      break
    items = items_by_card_id.get(card_id) or []
    if not items:
      continue

    existing = board_state.cards.get(card_id)
    if existing is None or getattr(existing, "kind", None) != CardKind.LIST:
      continue

    existing_items: list[ListItem] = list(getattr(getattr(existing, "props", None), "items", []) or [])
    existing_norm = {_normalize_list_item_text(i.text) for i in existing_items if getattr(i, "text", None)}
    next_items = [i.model_dump(mode="python") for i in existing_items]

    added = 0
    for raw in items:
      if remaining <= 0:
        break
      normalized = _normalize_list_item_text(raw)
      if not normalized or normalized in existing_norm:
        continue
      next_items.append(ListItem(text=raw.strip()).model_dump(mode="python"))
      existing_norm.add(normalized)
      added += 1
      remaining -= 1

    if added:
      updates.append(UpdateCardAction(card_id=card_id, patch={"props": {"items": next_items}}, citations=None))

  return updates


def _meeting_native_create_or_update_actions(
  board_state: BoardState, items_by_card_id: dict[str, list[str]], *, max_new_items: int = 5
) -> tuple[list[BoardAction], BoardState]:
  remaining = max(0, max_new_items)
  if remaining == 0:
    return [], board_state

  actions: list[BoardAction] = []
  next_state = board_state

  for idx, (card_id, title) in enumerate(MEETING_NATIVE_BASE_LIST_CARDS):
    if remaining <= 0:
      break
    if card_id in board_state.dismissed:
      continue

    items = items_by_card_id.get(card_id) or []
    if not items:
      continue

    if card_id in next_state.cards:
      continue

    seen: set[str] = set()
    seed_items: list[ListItem] = []
    for raw in items:
      if remaining <= 0:
        break
      normalized = _normalize_list_item_text(raw)
      if not normalized or normalized in seen:
        continue
      seen.add(normalized)
      seed_items.append(ListItem(text=raw.strip()))
      remaining -= 1

    if not seed_items:
      continue

    create = CreateCardAction(
      card=ListCard(
        card_id=card_id,
        kind=CardKind.LIST,
        props=ListCardProps(title=title, items=seed_items),
        sources=[],
      ),
      rect=_meeting_native_seed_rect(idx),
    )
    actions.append(create)
    next_state = apply_action(next_state, create)

  if remaining <= 0:
    return actions, next_state

  filtered = {cid: items for cid, items in items_by_card_id.items() if items and cid not in board_state.dismissed}
  updates = _meeting_native_update_actions(next_state, filtered, max_new_items=remaining)
  for update in updates:
    actions.append(update)
    next_state = apply_action(next_state, update)

  return actions, next_state


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
  default_location: str | None = None
  no_browse_override: bool | None = None
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
      self.default_location = None
      self.no_browse_override = None
      self.version += 1
    if PERSISTOR is not None:
      await PERSISTOR.schedule_clear()
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

  async def board_export_payload(self) -> dict[str, Any]:
    async with self.state_lock:
      payload: dict[str, Any] = {"type": "board_export", "state": _state_to_json(self.board_state)}
      if self.default_location is not None:
        payload["default_location"] = self.default_location
      if self.no_browse_override is not None:
        payload["no_browse"] = self.no_browse_override
      return payload

  async def replace_board_state(
    self,
    state: BoardState,
    *,
    has_default_location: bool,
    default_location: str | None,
    has_no_browse: bool,
    no_browse: bool | None,
  ) -> BoardState:
    async with self.state_lock:
      self.board_state = state
      if has_default_location:
        self.default_location = default_location
      if has_no_browse:
        self.no_browse_override = no_browse
      self.version += 1
      return self.board_state

  async def get_default_location(self) -> str | None:
    async with self.state_lock:
      return self.default_location

  async def set_default_location(self, value: str) -> None:
    async with self.state_lock:
      self.default_location = value
    if PERSISTOR is not None:
      await PERSISTOR.schedule_save()

  async def get_no_browse_override(self) -> bool | None:
    async with self.state_lock:
      return self.no_browse_override

  async def set_no_browse_override(self, value: bool | None) -> None:
    async with self.state_lock:
      self.no_browse_override = value
    if PERSISTOR is not None:
      await PERSISTOR.schedule_save()

  async def apply_board_actions(self, *, expected_version: int, actions: list[BoardAction]) -> BoardState | None:
    async with self.state_lock:
      if self.version != expected_version:
        return None
      next_state = self.board_state
      for action in actions:
        next_state = apply_action(next_state, action)
      self.board_state = next_state
      self.version += 1
    if PERSISTOR is not None:
      await PERSISTOR.schedule_save()
    return next_state

  async def apply_board_actions_now(self, actions: list[BoardAction]) -> tuple[int, BoardState]:
    async with self.state_lock:
      next_state = self.board_state
      for action in actions:
        next_state = apply_action(next_state, action)
      self.board_state = next_state
      self.version += 1
      version = self.version
    if PERSISTOR is not None:
      await PERSISTOR.schedule_save()
    return version, next_state


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

    model = os.getenv("MEETINGGENIUS_MODEL") or "openai:gpt-4o-mini"
    session_location = await self._state.get_default_location()
    default_location = session_location or (os.getenv("MEETINGGENIUS_DEFAULT_LOCATION") or "Seattle")
    session_no_browse = await self._state.get_no_browse_override()
    no_browse = session_no_browse if session_no_browse is not None else _env_bool("MEETINGGENIUS_NO_BROWSE", False)
    policy = ToolingPolicy(no_browse=no_browse)

    offline_meeting_native = _env_bool("MEETINGGENIUS_OFFLINE_MEETING_NATIVE", False) or model == "test"
    if offline_meeting_native:
      items_by_card_id = _extract_meeting_native_items(events)
      actions, post_process_state = _meeting_native_create_or_update_actions(board_state, items_by_card_id, max_new_items=5)

      if not actions:
        return

      processed_actions, throttle_msg, next_timestamps, next_last_create = self._post_process_actions(
        post_process_state, actions
      )
      next_state = await self._state.apply_board_actions(expected_version=version, actions=processed_actions)
      if next_state is None:
        await self._state.status("Discarded meeting-native result (state changed).")
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
      return

    await self._state.status("Running orchestrator…")

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
        f"Default location: {default_location}",
        f"External browsing/research enabled: {not no_browse}",
        "Meeting-native artifacts are ALWAYS allowed (decisions, action items, questions, risks/blockers, next steps) and do not require research tasks.",
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
    if no_browse and tasks:
      await self._state.status(f"External research disabled; ignoring {len(tasks)} suggested research task(s).")
      tasks = []
      decision = decision.model_copy(update={"research_tasks": tasks})

    if not no_browse and not tasks:
      combined_text = "\n".join(e.text for e in events if e.text)
      tasks = auto_seed_research_tasks(combined_text, default_location=default_location)
      if tasks:
        decision = decision.model_copy(update={"research_tasks": tasks})

    results = []
    if tasks:
      await self._state.status(f"Research tasks: {len(tasks)}")

    for task in tasks:
      try:
        results.append(await run_research_task(task, no_browse=no_browse))
      except Exception as e:
        label = task.tool_name or task.kind
        await self._state.status(f"Research failed for {label}: {e}")

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
        "- Meeting-native artifacts (decisions/actions/questions/risks/next steps) are always allowed even if external research is disabled; they should have sources=[] and no citations.",
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

    seed_actions = _meeting_native_seed_actions(board_state, actions)
    post_process_state = board_state
    if seed_actions:
      actions = seed_actions + actions
      for action in seed_actions:
        post_process_state = apply_action(post_process_state, action)

    items_by_card_id = _extract_meeting_native_items(events)
    if items_by_card_id:
      pre_fallback_state = post_process_state
      for action in actions:
        if isinstance(action, CreateCardAction) and action.card.card_id in MEETING_NATIVE_BASE_LIST_CARD_IDS:
          pre_fallback_state = apply_action(pre_fallback_state, action)
        elif isinstance(action, UpdateCardAction) and action.card_id in MEETING_NATIVE_BASE_LIST_CARD_IDS:
          pre_fallback_state = apply_action(pre_fallback_state, action)

      fallback_actions, fallback_state = _meeting_native_create_or_update_actions(
        pre_fallback_state, items_by_card_id, max_new_items=5
      )
      if fallback_actions:
        actions = actions + fallback_actions
        post_process_state = fallback_state

    processed_actions, throttle_msg, next_timestamps, next_last_create = self._post_process_actions(
      post_process_state, actions
    )

    if no_browse:
      sanitized: list[BoardAction] = []
      dropped = 0
      stripped = 0
      for action in processed_actions:
        if isinstance(action, CreateCardAction) and action.card.sources:
          dropped += 1
          continue

        if isinstance(action, UpdateCardAction) and (action.citations or "sources" in action.patch):
          patch = dict(action.patch)
          had_sources = "sources" in patch
          patch.pop("sources", None)
          if had_sources or action.citations:
            stripped += 1
            action = action.model_copy(update={"patch": patch, "citations": None})

        sanitized.append(action)

      if dropped:
        await self._state.status(f"Skipped {dropped} action(s) with external citations (external research is off).")
      if stripped:
        await self._state.status(f"Removed citations from {stripped} action(s) (external research is off).")

      processed_actions = sanitized

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
      if isinstance(action, CreateCardAction) and action.card.card_id in MEETING_NATIVE_BASE_LIST_CARD_IDS:
        deduped.append(action)
        continue
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
      if isinstance(action, CreateCardAction) and action.card.card_id in MEETING_NATIVE_BASE_LIST_CARD_IDS:
        output.append(action)
        continue
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


async def _persistence_snapshot() -> tuple[BoardState, str | None, bool | None]:
  async with STATE.state_lock:
    return STATE.board_state, STATE.default_location, STATE.no_browse_override


@app.on_event("startup")
async def _load_persisted_state() -> None:
  global PERSIST_STORE, PERSISTOR

  db_path = resolve_db_path()
  PERSIST_STORE = SQLiteKVStore(db_path)
  PERSISTOR = DebouncedStatePersister(
    store=PERSIST_STORE,
    snapshot_provider=_persistence_snapshot,
    debounce_seconds=_env_float("MEETINGGENIUS_PERSIST_DEBOUNCE_SECONDS", 1.25),
  )

  if not db_path.exists():
    return

  try:
    raw_board = PERSIST_STORE.get_value_json(BOARD_STATE_KEY)
    raw_location = PERSIST_STORE.get_value_json(DEFAULT_LOCATION_KEY)
    raw_no_browse = PERSIST_STORE.get_value_json(NO_BROWSE_KEY)
    board_state = load_board_state(raw_board) if raw_board else None
    default_location = load_default_location(raw_location) if raw_location else None
    no_browse = load_no_browse(raw_no_browse) if raw_no_browse else None
  except Exception:
    print("WARN: failed to load persisted state; starting with defaults.")
    traceback.print_exc(limit=15)
    return

  if board_state is None and default_location is None and no_browse is None:
    return

  async with STATE.state_lock:
    if board_state is not None:
      STATE.board_state = board_state
    STATE.default_location = default_location
    STATE.no_browse_override = no_browse


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

      if msg_type == "export_board":
        await ws.send_json(await STATE.board_export_payload())
        continue

      if msg_type == "import_board":
        raw_state = data.get("state")
        if not isinstance(raw_state, dict):
          await ws.send_json(
            {
              "type": "error",
              "message": "Invalid import_board payload.",
              "details": {"state": "Expected JSON object."},
            }
          )
          continue

        try:
          next_board_state = BoardState.model_validate(raw_state)
        except ValidationError as e:
          await ws.send_json(
            {
              "type": "error",
              "message": "Invalid import_board payload.",
              "details": {"errors": e.errors()},
            }
          )
          continue

        has_default_location = "default_location" in data
        default_location: str | None = None
        if has_default_location:
          raw_location = data.get("default_location")
          if raw_location is None:
            default_location = None
          elif isinstance(raw_location, str) and raw_location.strip():
            default_location = raw_location.strip()
          else:
            await ws.send_json(
              {
                "type": "error",
                "message": "Invalid import_board payload.",
                "details": {"default_location": "Expected non-empty string or null."},
              }
            )
            continue

        has_no_browse = "no_browse" in data
        no_browse: bool | None = None
        if has_no_browse:
          raw_no_browse = data.get("no_browse")
          if raw_no_browse is None or isinstance(raw_no_browse, bool):
            no_browse = raw_no_browse
          else:
            await ws.send_json(
              {
                "type": "error",
                "message": "Invalid import_board payload.",
                "details": {"no_browse": "Expected boolean or null."},
              }
            )
            continue

        imported_state = await STATE.replace_board_state(
          next_board_state,
          has_default_location=has_default_location,
          default_location=default_location,
          has_no_browse=has_no_browse,
          no_browse=no_browse,
        )

        if PERSISTOR is not None:
          await PERSISTOR.save_now()

        await STATE.status("Board imported.")
        await STATE.broadcast({"type": "board_actions", "actions": [], "state": _state_to_json(imported_state)})
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

      if msg_type == "run_ai":
        await ws.send_json({"type": "status", "message": "AI run requested by user."})
        if STATE.ai_runner is not None:
          await STATE.ai_runner.request()
        continue

      if msg_type == "set_session_context":
        default_location = data.get("default_location")
        if not isinstance(default_location, str) or not default_location.strip():
          await ws.send_json(
            {
              "type": "error",
              "message": "Invalid set_session_context payload.",
              "details": {"default_location": "Expected non-empty string."},
            }
          )
          continue

        no_browse: bool | None = None
        if "no_browse" in data:
          raw_no_browse = data.get("no_browse")
          if not isinstance(raw_no_browse, bool):
            await ws.send_json(
              {
                "type": "error",
                "message": "Invalid set_session_context payload.",
                "details": {"no_browse": "Expected boolean."},
              }
            )
            continue
          no_browse = raw_no_browse

        await STATE.set_default_location(default_location.strip())
        if no_browse is not None:
          await STATE.set_no_browse_override(no_browse)

        await ws.send_json(
          {
            "type": "status",
            "message": (
              f"Session context updated (location={default_location.strip()}, "
              f"external_research={'off' if no_browse else 'on'})."
              if no_browse is not None
              else f"Session default location set to {default_location.strip()}."
            ),
          }
        )
        continue

      if msg_type == "client_board_action":
        raw_action = data.get("action")
        if not isinstance(raw_action, dict):
          await ws.send_json(
            {
              "type": "error",
              "message": "Invalid client_board_action payload.",
              "details": {"action": "Expected JSON object."},
            }
          )
          continue

        try:
          action = TypeAdapter(BoardAction).validate_python(raw_action)
        except ValidationError as e:
          await ws.send_json(
            {
              "type": "error",
              "message": "Invalid board action payload.",
              "details": {"errors": e.errors()},
            }
          )
          continue

        if getattr(action, "type", None) not in {"move_card", "dismiss_card"}:
          await ws.send_json(
            {
              "type": "error",
              "message": "Unsupported board action type.",
              "details": {"allowed": ["move_card", "dismiss_card"], "type": getattr(action, "type", None)},
            }
          )
          continue

        _, next_state = await STATE.apply_board_actions_now([action])
        await STATE.broadcast(
          {"type": "board_actions", "actions": _actions_to_json([action]), "state": _state_to_json(next_state)}
        )
        continue

      await ws.send_json(
        {"type": "error", "message": f"Unknown message type: {msg_type!r}", "details": {"type": msg_type}}
      )

  except WebSocketDisconnect:
    pass
  finally:
    await STATE.remove_client(ws)
