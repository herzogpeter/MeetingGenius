from __future__ import annotations

import asyncio
import hashlib
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

try:
  from dotenv import load_dotenv

  load_dotenv()
except Exception:
  # Optional convenience: load `.env` if present (e.g., when running `uvicorn` directly).
  # Ignore failures so production/container env behaves normally.
  pass

from meetinggenius.board.reducer import apply_action
from meetinggenius.agents.orchestrator import MEETING_NATIVE_LIST_CARD_IDS
from meetinggenius.contracts import (
  BoardAction,
  BoardState,
  CardKind,
  CreateCardAction,
  DeleteMindmapSubtreeAction,
  ListItem,
  ListCard,
  ListCardProps,
  MindmapAction,
  MindmapNode,
  MindmapPoint,
  MindmapState,
  ReparentMindmapNodeAction,
  RenameMindmapNodeAction,
  SetMindmapNodeCollapsedAction,
  SetMindmapNodePosAction,
  UpsertMindmapNodeAction,
  Rect,
  ToolingPolicy,
  TranscriptEvent,
  UpdateCardAction,
)
from meetinggenius.sqlite_store import (
  BOARD_STATE_KEY,
  DEFAULT_LOCATION_KEY,
  MINDMAP_STATE_KEY,
  MINDMAP_AI_KEY,
  NO_BROWSE_KEY,
  DebouncedStatePersister,
  SQLiteKVStore,
  load_board_state,
  load_default_location,
  load_mindmap_state,
  load_mindmap_ai,
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

MINDMAP_ROOT_ID = "mm:root"
MEETING_NATIVE_MINDMAP_CATEGORIES: tuple[tuple[str, str, str], ...] = (
  ("mm:decisions", "Decisions", "list-decisions"),
  ("mm:actions", "Action Items", "list-actions"),
  ("mm:questions", "Open Questions", "list-questions"),
  ("mm:risks", "Risks / Blockers", "list-risks"),
  ("mm:next-steps", "Next Steps", "list-next-steps"),
)


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


def _mindmap_normalize_text(value: str) -> str:
  cleaned = value.strip().lower()
  cleaned = re.sub(r"\s+", " ", cleaned).strip()
  cleaned = cleaned.strip(" \t\r\n.;")
  return cleaned


_MINDMAP_RESERVED_SEGMENTS: dict[str, str] = {
  "mindmap": MINDMAP_ROOT_ID,
  "decisions": "mm:decisions",
  "decision": "mm:decisions",
  "action items": "mm:actions",
  "action item": "mm:actions",
  "open questions": "mm:questions",
  "open question": "mm:questions",
  "questions": "mm:questions",
  "question": "mm:questions",
  "risks blockers": "mm:risks",
  "risks and blockers": "mm:risks",
  "risk": "mm:risks",
  "risks": "mm:risks",
  "blocker": "mm:risks",
  "blockers": "mm:risks",
  "next steps": "mm:next-steps",
  "next step": "mm:next-steps",
  "follow ups": "mm:next-steps",
  "follow up": "mm:next-steps",
}


def _mindmap_route_reserved_segment(text: str) -> str | None:
  key = _normalize_title(text)
  if not key:
    return None
  return _MINDMAP_RESERVED_SEGMENTS.get(key)


def _mindmap_leaf_id(parent_id: str, text: str) -> str:
  normalized = _mindmap_normalize_text(text)
  digest = hashlib.sha1(f"{parent_id}\n{normalized}".encode("utf-8")).hexdigest()[:12]
  return f"mm:item:{digest}"


def _mindmap_path_id(parent_id: str, text: str) -> str:
  normalized = _mindmap_normalize_text(text)
  digest = hashlib.sha1(f"{parent_id}\n{normalized}".encode("utf-8")).hexdigest()[:12]
  return f"mm:path:{digest}"


def _mindmap_find_child_by_text(state: MindmapState, *, parent_id: str, text: str) -> str | None:
  wanted = _mindmap_normalize_text(text)
  if not wanted:
    return None
  best_id: str | None = None
  best_score = 0.0
  for node_id, node in state.nodes.items():
    if node.parent_id != parent_id:
      continue
    if _mindmap_normalize_text(node.text) == wanted:
      return node_id
    if _very_similar_title(node.text, text):
      score = _title_similarity(node.text, text)
      if score > best_score:
        best_id = node_id
        best_score = score
  return best_id


def _mindmap_should_global_dedupe(text: str) -> bool:
  # Avoid globally deduping short/generic segments like "Timeline" or "Shipping".
  normalized = _normalize_title(text)
  if len(normalized) < 14:
    return False
  tokens = normalized.split()
  return len(tokens) >= 3


def _mindmap_find_any_node_by_exact_text(state: MindmapState, text: str) -> str | None:
  wanted = _mindmap_normalize_text(text)
  if not wanted:
    return None
  for node_id, node in state.nodes.items():
    if _mindmap_normalize_text(node.text) == wanted:
      return node_id
  return None


def _mindmap_find_any_node_by_similar_text(state: MindmapState, text: str) -> str | None:
  wanted = _mindmap_normalize_text(text)
  if not wanted:
    return None

  similarity_threshold = 0.88
  category_ids = {node_id for node_id, _, _ in MEETING_NATIVE_MINDMAP_CATEGORIES}
  best_id: str | None = None
  best_score = 0.0

  for node_id, node in state.nodes.items():
    if node_id == state.root_id:
      continue

    if node_id in category_ids and _mindmap_normalize_text(node.text) != wanted:
      continue

    score = _title_similarity(node.text, text)
    is_similar = _very_similar_title(node.text, text)
    if score < similarity_threshold and not is_similar:
      continue
    if is_similar:
      score = max(score, similarity_threshold)

    if score > best_score:
      best_id = node_id
      best_score = score

  if best_id is None:
    return None
  return best_id


def _mindmap_auto_pos_for_child(state: MindmapState, *, parent_id: str, sibling_index: int) -> MindmapPoint:
  if parent_id == MINDMAP_ROOT_ID:
    base_y = 60.0 + len(MEETING_NATIVE_MINDMAP_CATEGORIES) * 150.0
    return MindmapPoint(x=300.0, y=base_y + sibling_index * 110.0)

  parent_pos = state.layout.get(parent_id)
  if parent_pos is None:
    parent_pos = MindmapPoint(x=40.0, y=40.0)
  return MindmapPoint(x=parent_pos.x + 360.0, y=parent_pos.y + sibling_index * 90.0)


def _format_transcript_window_for_mindmap_ai(events: list[TranscriptEvent]) -> str:
  lines: list[str] = []
  for e in events:
    status = "final" if e.is_final else "interim"
    who = f"{e.speaker}: " if e.speaker else ""
    lines.append(f"- [{e.timestamp.isoformat()}] ({status}) {who}{e.text}")
  return "\n".join(lines)


@dataclass(frozen=True)
class _StubMindmapPathProposal:
  path: list[str]


def _mindmap_extractor_mode() -> str:
  mode = (os.getenv("MEETINGGENIUS_MINDMAP_EXTRACTOR") or "").strip().lower()
  if mode:
    return mode
  if _env_bool("MEETINGGENIUS_FAKE_AI", False):
    return "stub"
  return "ai"


def _stub_strip_timestamp_and_speaker(text: str) -> str:
  cleaned = re.sub(r"^\s*\[\d{2}:\d{2}\]\s*", "", text).strip()
  cleaned = re.sub(r"^[A-Za-z][A-Za-z0-9 .'-]{0,32}:\s+", "", cleaned)
  return cleaned.strip()


def _stub_sentence_candidates(text: str) -> list[str]:
  text = text.replace("\r", "\n")
  sentences: list[str] = []
  for raw_line in re.split(r"\n+", text):
    line = raw_line.strip()
    if not line:
      continue
    line = _stub_strip_timestamp_and_speaker(line)
    if not line:
      continue
    line = line.replace("\u2014", ". ")
    for part in re.split(r"[.!?]\s+", line):
      part = part.strip()
      if not part:
        continue
      if len(part.split()) > 18 and "," in part:
        sentences.extend(seg.strip() for seg in part.split(",") if seg.strip())
      else:
        sentences.append(part)
  return sentences


def _stub_phrase_candidates(sentence: str) -> list[str]:
  cleaned = sentence.strip().strip("\"'`")
  cleaned = cleaned.strip(" ,.;:()[]")
  if ":" in cleaned:
    prefix, rest = cleaned.split(":", 1)
    if len(prefix.split()) <= 3:
      cleaned = rest.strip()
  tokens = [t for t in cleaned.split() if t]
  if not tokens:
    return []
  max_words = 3
  min_words = 3
  phrases: list[str] = []
  for idx in range(0, len(tokens), max_words):
    chunk = tokens[idx : idx + max_words]
    if len(chunk) < min_words:
      continue
    phrases.append(" ".join(chunk))
    if len(phrases) >= 6:
      break
  if not phrases:
    phrases.append(" ".join(tokens[:8]))
  return [p.strip(" ,.;:()[]") for p in phrases if p.strip(" ,.;:()[]")]


def _stub_mindmap_path_proposals(
  events: list[TranscriptEvent],
  *,
  max_phrases: int = 16,
  topic: str = "Transcript",
) -> list[_StubMindmapPathProposal]:
  if max_phrases <= 0:
    return []
  seen: set[str] = set()
  phrases: list[str] = []
  for event in events:
    for sentence in _stub_sentence_candidates(event.text):
      for phrase in _stub_phrase_candidates(sentence):
        if not phrase:
          continue
        if len(phrase.split()) < 3 and len(phrase) < 12:
          continue
        norm = _normalize_title(phrase)
        if not norm or norm in seen:
          continue
        seen.add(norm)
        phrases.append(phrase)
        if len(phrases) >= max_phrases:
          break
      if len(phrases) >= max_phrases:
        break
    if len(phrases) >= max_phrases:
      break
  if not phrases:
    fallback = next(
      (p for e in events for p in _stub_phrase_candidates(e.text) if p),
      "",
    )
    if fallback:
      phrases.append(fallback)
  return [_StubMindmapPathProposal(path=[topic, phrase]) for phrase in phrases]


def _format_mindmap_state_summary(state: MindmapState, *, max_nodes: int = 60, max_children: int = 12) -> str:
  if not state.nodes:
    return "(empty mindmap)"

  nodes = state.nodes
  root = nodes.get(state.root_id)
  if root is None:
    return f"(mindmap has {len(nodes)} nodes; missing root_id={state.root_id!r})"

  children_by_parent: dict[str, list[MindmapNode]] = {}
  for node in nodes.values():
    if not node.parent_id:
      continue
    children_by_parent.setdefault(node.parent_id, []).append(node)
  for parent_id in list(children_by_parent.keys()):
    children_by_parent[parent_id].sort(key=lambda n: _mindmap_normalize_text(n.text))

  lines: list[str] = []
  count = 0

  def visit(node_id: str, depth: int) -> None:
    nonlocal count
    if count >= max_nodes:
      return
    node = nodes.get(node_id)
    if node is None:
      return
    prefix = "  " * depth
    lines.append(f"{prefix}- {node.text}")
    count += 1
    if node.collapsed:
      return
    for child in children_by_parent.get(node_id, [])[:max_children]:
      visit(child.node_id, depth + 1)

  visit(state.root_id, 0)
  remaining = len(nodes) - count
  if remaining > 0:
    lines.append(f"- …and {remaining} more node(s)")
  return "\n".join(lines).strip()


def _mindmap_category_pos(category_index: int) -> MindmapPoint:
  return MindmapPoint(x=300.0, y=60.0 + category_index * 150.0)


def _mindmap_leaf_pos(category_index: int, item_index: int) -> MindmapPoint:
  return MindmapPoint(x=660.0, y=120.0 + category_index * 150.0 + item_index * 70.0)


def _mindmap_root_pos() -> MindmapPoint:
  return MindmapPoint(x=40.0, y=40.0)


def _apply_mindmap_action(state: MindmapState, action: MindmapAction) -> MindmapState:
  if isinstance(action, UpsertMindmapNodeAction):
    nodes = dict(state.nodes)
    nodes[action.node.node_id] = action.node
    return state.model_copy(update={"nodes": nodes})

  if isinstance(action, SetMindmapNodePosAction):
    layout = dict(state.layout)
    layout[action.node_id] = action.pos
    return state.model_copy(update={"layout": layout})

  if isinstance(action, SetMindmapNodeCollapsedAction):
    node = state.nodes.get(action.node_id)
    if node is None:
      return state
    nodes = dict(state.nodes)
    nodes[action.node_id] = node.model_copy(update={"collapsed": action.collapsed})
    return state.model_copy(update={"nodes": nodes})

  if isinstance(action, RenameMindmapNodeAction):
    node = state.nodes.get(action.node_id)
    if node is None:
      return state
    nodes = dict(state.nodes)
    nodes[action.node_id] = node.model_copy(update={"text": action.text})
    return state.model_copy(update={"nodes": nodes})

  if isinstance(action, DeleteMindmapSubtreeAction):
    if action.node_id == state.root_id:
      return MindmapState.empty()

    nodes = dict(state.nodes)
    layout = dict(state.layout)
    to_delete: list[str] = [action.node_id]

    idx = 0
    while idx < len(to_delete):
      current = to_delete[idx]
      idx += 1
      for node_id, node in list(nodes.items()):
        if node.parent_id == current:
          to_delete.append(node_id)

    for node_id in to_delete:
      nodes.pop(node_id, None)
      layout.pop(node_id, None)

    return state.model_copy(update={"nodes": nodes, "layout": layout})

  if isinstance(action, ReparentMindmapNodeAction):
    if action.node_id == state.root_id:
      return state
    node = state.nodes.get(action.node_id)
    if node is None:
      return state
    if action.new_parent_id is not None and action.new_parent_id not in state.nodes:
      return state

    # Prevent cycles by disallowing reparenting under a descendant.
    descendant_ids: set[str] = set()
    queue = [action.node_id]
    while queue:
      cur = queue.pop()
      for nid, n in state.nodes.items():
        if n.parent_id == cur and nid not in descendant_ids:
          descendant_ids.add(nid)
          queue.append(nid)
    if action.new_parent_id in descendant_ids:
      return state

    nodes = dict(state.nodes)
    nodes[action.node_id] = node.model_copy(update={"parent_id": action.new_parent_id})
    return state.model_copy(update={"nodes": nodes})

  return state


def _ensure_meeting_native_mindmap(state: MindmapState, items_by_card_id: dict[str, list[str]]) -> tuple[list[MindmapAction], MindmapState]:
  actions: list[MindmapAction] = []
  next_state = state

  if next_state.root_id != MINDMAP_ROOT_ID:
    next_state = next_state.model_copy(update={"root_id": MINDMAP_ROOT_ID})

  if MINDMAP_ROOT_ID not in next_state.nodes:
    root = MindmapNode(node_id=MINDMAP_ROOT_ID, parent_id=None, text="Mindmap")
    actions.append(UpsertMindmapNodeAction(node=root))
    next_state = _apply_mindmap_action(next_state, actions[-1])
  if MINDMAP_ROOT_ID not in next_state.layout:
    pos_action = SetMindmapNodePosAction(node_id=MINDMAP_ROOT_ID, pos=_mindmap_root_pos())
    actions.append(pos_action)
    next_state = _apply_mindmap_action(next_state, pos_action)

  for idx, (node_id, title, legacy_card_id) in enumerate(MEETING_NATIVE_MINDMAP_CATEGORIES):
    if node_id not in next_state.nodes:
      cat = MindmapNode(node_id=node_id, parent_id=MINDMAP_ROOT_ID, text=title)
      upsert = UpsertMindmapNodeAction(node=cat)
      actions.append(upsert)
      next_state = _apply_mindmap_action(next_state, upsert)
    if node_id not in next_state.layout:
      pos = _mindmap_category_pos(idx)
      pos_action = SetMindmapNodePosAction(node_id=node_id, pos=pos)
      actions.append(pos_action)
      next_state = _apply_mindmap_action(next_state, pos_action)

    raw_items = items_by_card_id.get(legacy_card_id) or []
    if not raw_items:
      continue

    # Determine next leaf index for autoplace.
    existing_child_count = sum(1 for n in next_state.nodes.values() if n.parent_id == node_id)
    leaf_index = existing_child_count

    for raw in raw_items:
      text = raw.strip()
      if not text:
        continue
      leaf_id = _mindmap_leaf_id(node_id, text)
      if leaf_id in next_state.nodes:
        continue

      leaf = MindmapNode(node_id=leaf_id, parent_id=node_id, text=text)
      upsert = UpsertMindmapNodeAction(node=leaf)
      actions.append(upsert)
      next_state = _apply_mindmap_action(next_state, upsert)

      if leaf_id not in next_state.layout:
        pos_action = SetMindmapNodePosAction(node_id=leaf_id, pos=_mindmap_leaf_pos(idx, leaf_index))
        actions.append(pos_action)
        next_state = _apply_mindmap_action(next_state, pos_action)
      leaf_index += 1

  return actions, next_state


def _apply_mindmap_path_proposals(
  state: MindmapState,
  proposals: list[Any],
  *,
  max_new_nodes: int = 12,
  max_new_root_topics: int = 4,
) -> tuple[list[MindmapAction], MindmapState]:
  seed_actions, next_state = _ensure_meeting_native_mindmap(state, {})
  actions: list[MindmapAction] = list(seed_actions)

  category_ids = {node_id for node_id, _, _ in MEETING_NATIVE_MINDMAP_CATEGORIES}
  created = 0
  created_root_topics = 0
  seen_paths: set[str] = set()

  capped_max_new_nodes = max(0, int(max_new_nodes))
  capped_max_root_topics = max(0, int(max_new_root_topics))

  for proposal in proposals:
    raw_path = getattr(proposal, "path", None)
    if not isinstance(raw_path, list) or not raw_path:
      continue

    parts: list[str] = []
    for seg in raw_path:
      if not isinstance(seg, str):
        continue
      cleaned = seg.strip()
      if cleaned:
        parts.append(cleaned[:120])

    if not parts:
      continue

    signature = " > ".join(_mindmap_normalize_text(p) for p in parts if p.strip())
    if not signature or signature in seen_paths:
      continue
    seen_paths.add(signature)

    parent_id = next_state.root_id
    for seg in parts:
      reserved = _mindmap_route_reserved_segment(seg)
      if reserved is not None and reserved in next_state.nodes:
        parent_id = reserved
        continue

      # If a segment matches an existing top-level topic, reuse that topic rather than
      # creating a duplicate under some other branch.
      if parent_id != MINDMAP_ROOT_ID:
        root_match = _mindmap_find_child_by_text(next_state, parent_id=MINDMAP_ROOT_ID, text=seg)
        if root_match is not None:
          parent_id = root_match
          continue

      if _mindmap_should_global_dedupe(seg):
        global_match = _mindmap_find_any_node_by_similar_text(next_state, seg)
        if global_match is not None:
          parent_id = global_match
          continue

      existing = _mindmap_find_child_by_text(next_state, parent_id=parent_id, text=seg)
      if existing is not None:
        parent_id = existing
        continue

      if created >= capped_max_new_nodes:
        break

      node_id = _mindmap_path_id(parent_id, seg)

      is_root_topic = parent_id == MINDMAP_ROOT_ID and node_id not in category_ids
      if is_root_topic and created_root_topics >= capped_max_root_topics:
        break

      node = MindmapNode(node_id=node_id, parent_id=parent_id, text=seg)
      upsert = UpsertMindmapNodeAction(node=node)
      actions.append(upsert)
      next_state = _apply_mindmap_action(next_state, upsert)
      created += 1
      if is_root_topic:
        created_root_topics += 1

      if node_id not in next_state.layout:
        if parent_id == MINDMAP_ROOT_ID:
          sibling_index = sum(
            1
            for n in next_state.nodes.values()
            if n.parent_id == parent_id and n.node_id not in category_ids and n.node_id != node_id
          )
        else:
          sibling_index = sum(1 for n in next_state.nodes.values() if n.parent_id == parent_id and n.node_id != node_id)
        pos = _mindmap_auto_pos_for_child(next_state, parent_id=parent_id, sibling_index=sibling_index)
        pos_action = SetMindmapNodePosAction(node_id=node_id, pos=pos)
        actions.append(pos_action)
        next_state = _apply_mindmap_action(next_state, pos_action)

      parent_id = node_id

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


def _model_provider(model: str) -> str:
  model = (model or "").strip()
  if ":" in model:
    return model.split(":", 1)[0].strip().lower()
  return model.lower()


def _missing_ai_config_hint(model: str) -> str | None:
  provider = _model_provider(model)
  if provider == "openai":
    if not os.getenv("OPENAI_API_KEY"):
      return "set OPENAI_API_KEY (or set MEETINGGENIUS_MODEL to an Anthropic model + ANTHROPIC_API_KEY)."
  if provider == "anthropic":
    if not os.getenv("ANTHROPIC_API_KEY"):
      return "set ANTHROPIC_API_KEY (or set MEETINGGENIUS_MODEL to an OpenAI model + OPENAI_API_KEY)."
  return None


def _humanize_ai_error(err: Exception, *, model: str) -> str:
  text = str(err) or err.__class__.__name__
  lower = text.lower()

  hint = _missing_ai_config_hint(model)
  if hint is not None:
    return f"AI loop failed: missing provider credentials; {hint}"

  if "insufficient_quota" in lower or "status_code: 429" in lower or "rate limit" in lower:
    return "AI loop failed: provider quota/rate limit (HTTP 429)."
  if "status_code: 401" in lower or "invalid_api_key" in lower:
    return "AI loop failed: invalid API key (HTTP 401)."

  return "AI loop failed."


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


def _mindmap_actions_to_json(actions: list[MindmapAction]) -> list[dict[str, Any]]:
  return [a.model_dump(mode="json") for a in actions]


def _mindmap_state_to_json(state: MindmapState) -> dict[str, Any]:
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


def _normalize_transcript_text(text: str) -> str:
  return " ".join(text.strip().lower().split())


def _normalize_transcript_speaker(speaker: str | None) -> str:
  return " ".join((speaker or "").strip().lower().split())


@dataclass
class RealtimeState:
  clients: set[WebSocket] = field(default_factory=set)
  clients_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

  transcript: deque[tuple[float, TranscriptEvent]] = field(default_factory=deque)
  transcript_version: int = 0
  board_state: BoardState = field(default_factory=BoardState.empty)
  mindmap_state: MindmapState = field(default_factory=MindmapState.empty)
  default_location: str | None = None
  no_browse_override: bool | None = None
  mindmap_ai_override: bool | None = None
  version: int = 0
  mindmap_version: int = 0
  state_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

  ai_runner: "AIRunner" | None = None
  mindmap_ai_runner: "MindmapAIRunner" | None = None

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
      self.transcript_version += 1
      self.board_state = BoardState.empty()
      self.mindmap_state = MindmapState.empty()
      self.default_location = None
      self.no_browse_override = None
      self.mindmap_ai_override = None
      self.version += 1
      self.mindmap_version += 1
    if PERSISTOR is not None:
      await PERSISTOR.schedule_clear()
    await self.status("State reset.")
    await self.broadcast({"type": "board_actions", "actions": [], "state": _state_to_json(BoardState.empty())})
    await self.broadcast(
      {"type": "mindmap_actions", "actions": [], "state": _mindmap_state_to_json(MindmapState.empty())}
    )
    await self.broadcast({"type": "mindmap_status", "status": "idle"})

  async def add_transcript_event(self, event: TranscriptEvent) -> None:
    max_events = _env_int("MEETINGGENIUS_TRANSCRIPT_MAX_EVENTS", 50)
    max_seconds = _env_int("MEETINGGENIUS_TRANSCRIPT_MAX_SECONDS", 120)

    now = time.time()
    cutoff = now - max_seconds

    async with self.state_lock:
      replaced = False
      if event.event_id:
        for idx, (ts, existing) in enumerate(self.transcript):
          if existing.event_id == event.event_id:
            self.transcript[idx] = (ts, event)
            self.transcript_version += 1
            replaced = True
            break

      if not replaced:
        if not event.event_id and self.transcript:
          _, last_event = self.transcript[-1]
          if (
            _normalize_transcript_speaker(last_event.speaker)
            == _normalize_transcript_speaker(event.speaker)
            and _normalize_transcript_text(last_event.text) == _normalize_transcript_text(event.text)
          ):
            return

        self.transcript.append((now, event))
        self.transcript_version += 1
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

  async def snapshot_mindmap_ai(self) -> tuple[int, int, list[TranscriptEvent], MindmapState, bool | None]:
    async with self.state_lock:
      version = self.mindmap_version
      transcript_version = self.transcript_version
      events = [e for _, e in self.transcript]
      state = self.mindmap_state
      mindmap_ai = self.mindmap_ai_override
    return version, transcript_version, events, state, mindmap_ai

  async def get_mindmap_state(self) -> MindmapState:
    async with self.state_lock:
      return self.mindmap_state

  async def apply_mindmap_actions_now(self, actions: list[MindmapAction]) -> tuple[int, MindmapState]:
    async with self.state_lock:
      next_state = self.mindmap_state
      for action in actions:
        next_state = _apply_mindmap_action(next_state, action)
      self.mindmap_state = next_state
      self.mindmap_version += 1
      version = self.mindmap_version
    if PERSISTOR is not None:
      await PERSISTOR.schedule_save()
    return version, next_state

  async def update_meeting_native_mindmap(self) -> tuple[list[MindmapAction], MindmapState] | None:
    async with self.state_lock:
      events = [e for _, e in self.transcript]
      mindmap_state = self.mindmap_state

      items_by_card_id = _extract_meeting_native_items(events)
      actions, next_state = _ensure_meeting_native_mindmap(mindmap_state, items_by_card_id)
      if not actions:
        return None

      self.mindmap_state = next_state
      self.mindmap_version += 1

    if PERSISTOR is not None:
      await PERSISTOR.schedule_save()
    return actions, next_state

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

  async def get_mindmap_ai_override(self) -> bool | None:
    async with self.state_lock:
      return self.mindmap_ai_override

  async def set_mindmap_ai_override(self, value: bool | None) -> None:
    async with self.state_lock:
      self.mindmap_ai_override = value
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
    self._warned_missing_ai_config = False

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
        model = os.getenv("MEETINGGENIUS_MODEL") or "openai:gpt-4o-mini"
        await self._state.error(
          _humanize_ai_error(e, model=model),
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

    missing_ai_hint = _missing_ai_config_hint(model)
    offline_meeting_native = (
      _env_bool("MEETINGGENIUS_OFFLINE_MEETING_NATIVE", False) or model == "test" or missing_ai_hint is not None
    )
    if missing_ai_hint is not None and not self._warned_missing_ai_config:
      await self._state.status(f"AI disabled: {missing_ai_hint}")
      self._warned_missing_ai_config = True
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


class MindmapAIRunner:
  def __init__(self, state: RealtimeState) -> None:
    self._state = state
    self._min_interval_s = _env_float("MEETINGGENIUS_MINDMAP_AI_MIN_INTERVAL_SECONDS", 2.5)
    self._lock = asyncio.Lock()
    self._task: asyncio.Task[None] | None = None
    self._pending = False
    self._last_started_at = 0.0
    self._last_processed_transcript_version = -1
    self._warned_missing_ai_config = False

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
        model = os.getenv("MEETINGGENIUS_MODEL") or "openai:gpt-4o-mini"
        await self._state.error(
          _humanize_ai_error(e, model=model),
          details={"error": str(e), "traceback": traceback.format_exc(limit=25)},
        )

  async def _run_once(self) -> None:
    _, transcript_version, events, mindmap_state, mindmap_ai_override = await self._state.snapshot_mindmap_ai()
    if not events:
      return
    if transcript_version == self._last_processed_transcript_version:
      return

    mindmap_ai_enabled = (
      mindmap_ai_override if mindmap_ai_override is not None else _env_bool("MEETINGGENIUS_MINDMAP_AI", True)
    )
    if not mindmap_ai_enabled:
      return

    extractor_mode = _mindmap_extractor_mode()

    # Use a stable window: last N final events + the most recent interim event (if any).
    final_events = [e for e in events if e.is_final]
    window: list[TranscriptEvent] = final_events[-18:]
    latest_interim = next((e for e in reversed(events) if not e.is_final), None)
    if latest_interim is not None:
      if not window or latest_interim.timestamp >= window[-1].timestamp:
        if len(latest_interim.text.strip()) >= 24:
          window = window + [latest_interim]

    if not window:
      return

    if extractor_mode == "stub":
      stub_max = _env_int("MEETINGGENIUS_MINDMAP_STUB_MAX_PHRASES", 16)
      await self._state.broadcast({"type": "mindmap_status", "status": "running"})
      try:
        proposals = _stub_mindmap_path_proposals(window, max_phrases=stub_max)
      finally:
        await self._state.broadcast({"type": "mindmap_status", "status": "idle"})
    else:
      model = os.getenv("MEETINGGENIUS_MODEL") or "openai:gpt-4o-mini"
      missing_ai_hint = _missing_ai_config_hint(model)
      if missing_ai_hint is not None:
        if not self._warned_missing_ai_config:
          await self._state.status(f"Mindmap AI disabled: {missing_ai_hint}")
          self._warned_missing_ai_config = True
        return

      if _env_bool("MEETINGGENIUS_OFFLINE_MINDMAP", False) or model == "test":
        return

      policy = ToolingPolicy(no_browse=True)

      try:
        from meetinggenius.agents.mindmap_extractor import MindmapExtractorDeps, build_mindmap_extractor_agent
      except ModuleNotFoundError as e:
        raise ModuleNotFoundError("Missing AI dependencies; run: `python -m pip install -e .`") from e

      transcript_window = _format_transcript_window_for_mindmap_ai(window)
      mindmap_summary = _format_mindmap_state_summary(mindmap_state)
      prompt = "\n".join(
        [
          "Meeting transcript window:",
          transcript_window,
          "",
          "Existing mindmap (reuse exact node text when it matches):",
          mindmap_summary,
          "",
          "Return a JSON array of MindmapPathProposal objects.",
        ]
      ).strip()

      extractor = build_mindmap_extractor_agent(model)
      deps = MindmapExtractorDeps(policy=policy, mindmap_state=mindmap_state)
      await self._state.broadcast({"type": "mindmap_status", "status": "running"})
      try:
        proposals = await asyncio.to_thread(lambda: extractor.run_sync(prompt, deps=deps).output)
      finally:
        await self._state.broadcast({"type": "mindmap_status", "status": "idle"})

    has_any_final = any(e.is_final for e in events)
    latest_event = events[-1] if events else None

    max_new_nodes = _env_int("MEETINGGENIUS_MINDMAP_MAX_NEW_NODES_PER_RUN", 12)
    max_new_root_topics = _env_int("MEETINGGENIUS_MINDMAP_MAX_NEW_ROOT_TOPICS_PER_RUN", 4)

    if latest_event is not None and not latest_event.is_final:
      if has_any_final:
        max_new_nodes = _env_int("MEETINGGENIUS_MINDMAP_MAX_NEW_NODES_PER_INTERIM_RUN", 3)
        max_new_root_topics = _env_int("MEETINGGENIUS_MINDMAP_MAX_NEW_ROOT_TOPICS_PER_INTERIM_RUN", 0)
      else:
        max_new_nodes = _env_int("MEETINGGENIUS_MINDMAP_MAX_NEW_NODES_BEFORE_FINAL", 6)
        max_new_root_topics = _env_int("MEETINGGENIUS_MINDMAP_MAX_NEW_ROOT_TOPICS_BEFORE_FINAL", 2)

    actions, _ = _apply_mindmap_path_proposals(
      mindmap_state,
      proposals,
      max_new_nodes=max_new_nodes,
      max_new_root_topics=max_new_root_topics,
    )
    if actions:
      _, applied_state = await self._state.apply_mindmap_actions_now(actions)
      await self._state.broadcast(
        {
          "type": "mindmap_actions",
          "actions": _mindmap_actions_to_json(actions),
          "state": _mindmap_state_to_json(applied_state),
        }
      )

    self._last_processed_transcript_version = transcript_version


STATE = RealtimeState()
STATE.ai_runner = AIRunner(STATE)
STATE.mindmap_ai_runner = MindmapAIRunner(STATE)


async def _persistence_snapshot() -> tuple[BoardState, MindmapState, str | None, bool | None, bool | None]:
  async with STATE.state_lock:
    return (
      STATE.board_state,
      STATE.mindmap_state,
      STATE.default_location,
      STATE.no_browse_override,
      STATE.mindmap_ai_override,
    )


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
    raw_mindmap = PERSIST_STORE.get_value_json(MINDMAP_STATE_KEY)
    raw_location = PERSIST_STORE.get_value_json(DEFAULT_LOCATION_KEY)
    raw_no_browse = PERSIST_STORE.get_value_json(NO_BROWSE_KEY)
    raw_mindmap_ai = PERSIST_STORE.get_value_json(MINDMAP_AI_KEY)
    board_state = load_board_state(raw_board) if raw_board else None
    mindmap_state = load_mindmap_state(raw_mindmap) if raw_mindmap else None
    default_location = load_default_location(raw_location) if raw_location else None
    no_browse = load_no_browse(raw_no_browse) if raw_no_browse else None
    mindmap_ai = load_mindmap_ai(raw_mindmap_ai) if raw_mindmap_ai else None
  except Exception:
    print("WARN: failed to load persisted state; starting with defaults.")
    traceback.print_exc(limit=15)
    return

  if board_state is None and mindmap_state is None and default_location is None and no_browse is None and mindmap_ai is None:
    return

  async with STATE.state_lock:
    if board_state is not None:
      STATE.board_state = board_state
    if mindmap_state is not None:
      STATE.mindmap_state = mindmap_state
    STATE.default_location = default_location
    STATE.no_browse_override = no_browse
    STATE.mindmap_ai_override = mindmap_ai


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
  await ws.accept()
  await STATE.add_client(ws)
  try:
    await ws.send_json({"type": "status", "message": "Connected."})
    _, _, board_state = await STATE.snapshot()
    await ws.send_json({"type": "board_actions", "actions": [], "state": _state_to_json(board_state)})
    mindmap_state = await STATE.get_mindmap_state()
    await ws.send_json({"type": "mindmap_actions", "actions": [], "state": _mindmap_state_to_json(mindmap_state)})
    await ws.send_json({"type": "mindmap_status", "status": "idle"})

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
        updated = await STATE.update_meeting_native_mindmap()
        if updated is not None:
          actions, next_state = updated
          await STATE.broadcast(
            {
              "type": "mindmap_actions",
              "actions": _mindmap_actions_to_json(actions),
              "state": _mindmap_state_to_json(next_state),
            }
          )
        mindmap_ai_override = await STATE.get_mindmap_ai_override()
        mindmap_ai_enabled = (
          mindmap_ai_override if mindmap_ai_override is not None else _env_bool("MEETINGGENIUS_MINDMAP_AI", True)
        )
        if mindmap_ai_enabled and STATE.mindmap_ai_runner is not None:
          await STATE.mindmap_ai_runner.request()
        if event.is_final and STATE.ai_runner is not None:
          await STATE.ai_runner.request()
        continue

      if msg_type == "run_ai":
        await ws.send_json({"type": "status", "message": "AI run requested by user."})
        if STATE.ai_runner is not None:
          await STATE.ai_runner.request()
        continue

      if msg_type == "set_session_context":
        has_default_location = "default_location" in data
        default_location: str | None = None
        if has_default_location:
          raw_location = data.get("default_location")
          if not isinstance(raw_location, str) or not raw_location.strip():
            await ws.send_json(
              {
                "type": "error",
                "message": "Invalid set_session_context payload.",
                "details": {"default_location": "Expected non-empty string."},
              }
            )
            continue
          default_location = raw_location.strip()

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

        mindmap_ai: bool | None = None
        if "mindmap_ai" in data:
          raw_mindmap_ai = data.get("mindmap_ai")
          if not isinstance(raw_mindmap_ai, bool):
            await ws.send_json(
              {
                "type": "error",
                "message": "Invalid set_session_context payload.",
                "details": {"mindmap_ai": "Expected boolean."},
              }
            )
            continue
          mindmap_ai = raw_mindmap_ai

        if has_default_location and default_location is not None:
          await STATE.set_default_location(default_location)
        else:
          current_default = await STATE.get_default_location()
          if current_default is None:
            fallback_location = os.getenv("MEETINGGENIUS_DEFAULT_LOCATION") or "Seattle"
            await STATE.set_default_location(fallback_location)
        if no_browse is not None:
          await STATE.set_no_browse_override(no_browse)
        if mindmap_ai is not None:
          await STATE.set_mindmap_ai_override(mindmap_ai)

        parts: list[str] = []
        if has_default_location and default_location is not None:
          parts.append(f"location={default_location}")
        if no_browse is not None:
          parts.append(f"external_research={'off' if no_browse else 'on'}")
        if mindmap_ai is not None:
          parts.append(f"mindmap_ai={'on' if mindmap_ai else 'off'}")
        updated = no_browse is not None or mindmap_ai is not None

        await ws.send_json(
          {
            "type": "status",
            "message": (
              f"Session context updated ({', '.join(parts)})."
              if updated
              else (
                f"Session default location set to {default_location}." if has_default_location else "Session context updated."
              )
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

      if msg_type == "client_mindmap_action":
        raw_action = data.get("action")
        if not isinstance(raw_action, dict):
          await ws.send_json(
            {
              "type": "error",
              "message": "Invalid client_mindmap_action payload.",
              "details": {"action": "Expected JSON object."},
            }
          )
          continue

        try:
          action = TypeAdapter(MindmapAction).validate_python(raw_action)
        except ValidationError as e:
          await ws.send_json(
            {
              "type": "error",
              "message": "Invalid mindmap action payload.",
              "details": {"errors": e.errors()},
            }
          )
          continue

        if getattr(action, "type", None) not in {
          "set_node_pos",
          "set_collapsed",
          "rename_node",
          "reparent_node",
          "delete_subtree",
        }:
          await ws.send_json(
            {
              "type": "error",
              "message": "Unsupported mindmap action type.",
              "details": {
                "allowed": [
                  "set_node_pos",
                  "set_collapsed",
                  "rename_node",
                  "reparent_node",
                  "delete_subtree",
                ],
                "type": getattr(action, "type", None),
              },
            }
          )
          continue

        _, next_state = await STATE.apply_mindmap_actions_now([action])
        await STATE.broadcast(
          {
            "type": "mindmap_actions",
            "actions": _mindmap_actions_to_json([action]),
            "state": _mindmap_state_to_json(next_state),
          }
        )
        continue

      await ws.send_json(
        {"type": "error", "message": f"Unknown message type: {msg_type!r}", "details": {"type": msg_type}}
      )

  except WebSocketDisconnect:
    pass
  finally:
    await STATE.remove_client(ws)
