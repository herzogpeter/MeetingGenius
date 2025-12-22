from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from meetinggenius.contracts import (
  BoardAction,
  BoardState,
  Card,
  CreateCardAction,
  DismissCardAction,
  MoveCardAction,
  UpdateCardAction,
)


def apply_action(state: BoardState, action: BoardAction) -> BoardState:
  next_state = deepcopy(state)

  if isinstance(action, CreateCardAction):
    card: Card = action.card
    next_state.cards[card.card_id] = card
    if action.rect is not None:
      next_state.layout[card.card_id] = action.rect
    next_state.dismissed.pop(card.card_id, None)
    return next_state

  if isinstance(action, UpdateCardAction):
    existing = next_state.cards.get(action.card_id)
    if existing is None:
      return next_state

    patched = _apply_patch(existing.model_dump(mode="python"), action.patch)
    try:
      updated = existing.__class__.model_validate(patched)
    except ValidationError:
      sanitized = _sanitize_card_dict(patched)
      if sanitized is patched:
        return next_state
      try:
        updated = existing.__class__.model_validate(sanitized)
      except ValidationError:
        return next_state
    next_state.cards[action.card_id] = updated
    return next_state

  if isinstance(action, MoveCardAction):
    if action.card_id in next_state.cards:
      next_state.layout[action.card_id] = action.rect
    return next_state

  if isinstance(action, DismissCardAction):
    next_state.cards.pop(action.card_id, None)
    next_state.layout.pop(action.card_id, None)
    next_state.dismissed[action.card_id] = action.reason or ""
    return next_state

  return next_state


def _apply_patch(obj: Any, patch: dict[str, Any]) -> Any:
  if not isinstance(obj, dict):
    return obj

  result = dict(obj)
  for key, value in patch.items():
    if isinstance(value, dict) and isinstance(result.get(key), dict):
      result[key] = _apply_patch(result[key], value)
    else:
      result[key] = value
  return result


def _sanitize_card_dict(card: Any) -> Any:
  if not isinstance(card, dict):
    return card

  changed = False
  kind = card.get("kind")
  out: dict[str, Any] = card

  if kind == "list":
    props = out.get("props")
    if isinstance(props, dict):
      items = props.get("items")
      if isinstance(items, list):
        next_items: list[Any] = []
        items_changed = False
        for item in items:
          if isinstance(item, dict) and "url" in item:
            url = item.get("url")
            if url is None or (isinstance(url, str) and not url.strip()):
              next_item = dict(item)
              next_item.pop("url", None)
              next_items.append(next_item)
              items_changed = True
              continue
          next_items.append(item)
        if items_changed:
          next_props = dict(props)
          next_props["items"] = next_items
          out = dict(out)
          out["props"] = next_props
          changed = True

  sources = out.get("sources")
  if isinstance(sources, list):
    next_sources: list[Any] = []
    sources_changed = False
    for source in sources:
      if isinstance(source, dict):
        url = source.get("url")
        if url is None or (isinstance(url, str) and not url.strip()):
          sources_changed = True
          continue
      next_sources.append(source)
    if sources_changed:
      out = dict(out)
      out["sources"] = next_sources
      changed = True

  return out if changed else card
