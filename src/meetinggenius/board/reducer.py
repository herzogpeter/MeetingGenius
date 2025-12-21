from __future__ import annotations

from copy import deepcopy
from typing import Any

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
    updated = existing.__class__.model_validate(patched)
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

