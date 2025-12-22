#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable


DEFAULT_WS_URL = "ws://localhost:8000/ws"


def _env_float(name: str, default: float) -> float:
  val = os.getenv(name)
  if val is None:
    return default
  try:
    return float(val)
  except ValueError:
    return default


def _now_iso() -> str:
  return datetime.now(tz=UTC).isoformat()


def _as_dict(value: Any) -> dict[str, Any] | None:
  if isinstance(value, dict):
    return value
  return None


@dataclass(frozen=True)
class FoundCard:
  card_id: str
  kind: str
  title: str


@dataclass(frozen=True)
class CardScan:
  chart_candidates: list[FoundCard]
  list_candidates: list[FoundCard]
  chart_good: list[FoundCard]
  list_good: list[FoundCard]


def _scan_cards(state: dict[str, Any]) -> CardScan:
  cards = _as_dict(state.get("cards")) or {}
  chart_candidates: list[FoundCard] = []
  list_candidates: list[FoundCard] = []
  chart_good: list[FoundCard] = []
  list_good: list[FoundCard] = []

  for card_id, raw_card in cards.items():
    card = _as_dict(raw_card)
    if not card:
      continue

    kind = card.get("kind")
    props = _as_dict(card.get("props")) or {}
    sources = card.get("sources")
    sources_ok = isinstance(sources, list) and len(sources) > 0

    title = props.get("title")
    if not isinstance(title, str) or not title.strip():
      title = str(title) if title is not None else "(untitled)"

    if kind == "chart":
      points = props.get("points")
      if isinstance(points, list) and len(points) > 0:
        found = FoundCard(card_id=str(card_id), kind="chart", title=title)
        chart_candidates.append(found)
        if sources_ok:
          chart_good.append(found)
    elif kind == "list":
      items = props.get("items")
      if isinstance(items, list) and len(items) > 0:
        found = FoundCard(card_id=str(card_id), kind="list", title=title)
        list_candidates.append(found)
        if sources_ok:
          list_good.append(found)

  return CardScan(
    chart_candidates=chart_candidates,
    list_candidates=list_candidates,
    chart_good=chart_good,
    list_good=list_good,
  )


async def _wait_for(
  ws: Any,
  *,
  deadline: float,
  predicate: Callable[[dict[str, Any]], bool],
  label: str,
  on_state: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
  last_error: str | None = None
  last_status: str | None = None
  while True:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
      extra = []
      if last_status:
        extra.append(f"last status={last_status!r}")
      if last_error:
        extra.append(f"last error={last_error!r}")
      extra_msg = f" ({', '.join(extra)})" if extra else ""
      raise TimeoutError(f"Timed out waiting for {label}.{extra_msg}")

    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
    if not isinstance(raw, (str, bytes, bytearray)):
      continue

    try:
      msg = json.loads(raw)
    except Exception:
      continue

    msg_obj = _as_dict(msg)
    if not msg_obj:
      continue

    msg_type = msg_obj.get("type")
    if msg_type == "status":
      last_status = str(msg_obj.get("message"))
      continue
    if msg_type == "error":
      last_error = str(msg_obj.get("message"))
      continue
    if msg_type != "board_actions":
      continue

    state = _as_dict(msg_obj.get("state"))
    if not state:
      continue
    if on_state is not None:
      on_state(state)
    if predicate(state):
      return state


async def _run() -> int:
  try:
    import websockets  # type: ignore[import-not-found]
  except ModuleNotFoundError:
    print("FAIL: missing dependency 'websockets'.", file=sys.stderr)
    print("Install: python -m pip install websockets", file=sys.stderr)
    return 2

  ws_url = os.getenv("MEETINGGENIUS_WS_URL", DEFAULT_WS_URL)
  timeout_s = _env_float("MEETINGGENIUS_SMOKE_TIMEOUT_S", 180.0)
  deadline = time.monotonic() + timeout_s

  seen_chart_candidates: dict[str, FoundCard] = {}
  seen_list_candidates: dict[str, FoundCard] = {}
  seen_charts: dict[str, FoundCard] = {}
  seen_lists: dict[str, FoundCard] = {}

  def observe(state: dict[str, Any]) -> None:
    scan = _scan_cards(state)
    for c in scan.chart_candidates:
      seen_chart_candidates[c.card_id] = c
    for c in scan.list_candidates:
      seen_list_candidates[c.card_id] = c
    for c in scan.chart_good:
      seen_charts[c.card_id] = c
    for c in scan.list_good:
      seen_lists[c.card_id] = c

  print(f"Connecting: {ws_url}")
  try:
    async with websockets.connect(ws_url) as ws:
      await _wait_for(
        ws,
        deadline=deadline,
        predicate=lambda _s: True,
        label="initial board state",
        on_state=observe,
      )
      await ws.send(json.dumps({"type": "reset"}))
      await _wait_for(
        ws,
        deadline=deadline,
        predicate=lambda s: len((_as_dict(s.get("cards")) or {})) == 0,
        label="reset board state",
        on_state=observe,
      )

      await ws.send(
        json.dumps(
          {
            "type": "transcript_event",
            "event": {
              "timestamp": _now_iso(),
              "speaker": "User",
              "text": "Show the temperature trends for December over the last 10 years.",
              "is_final": True,
            },
          }
        )
      )

      await _wait_for(
        ws,
        deadline=deadline,
        predicate=lambda s: len(_scan_cards(s).chart_good) > 0,
        label="chart card with points+sources",
        on_state=observe,
      )

      await ws.send(
        json.dumps(
          {
            "type": "transcript_event",
            "event": {
              "timestamp": _now_iso(),
              "speaker": "User",
              "text": "Pull the top December headlines for the last 5 years.",
              "is_final": True,
            },
          }
        )
      )

      await _wait_for(
        ws,
        deadline=deadline,
        predicate=lambda s: len(_scan_cards(s).chart_good) > 0 and len(_scan_cards(s).list_good) > 0,
        label="chart+list cards with props+sources",
        on_state=observe,
      )
  except OSError as e:
    print("\nFAIL: cannot connect to WebSocket.", file=sys.stderr)
    print(f"- url={ws_url!r}", file=sys.stderr)
    print(f"- error={e}", file=sys.stderr)
    print("Hint: start the backend with `uvicorn meetinggenius.server:app --reload --port 8000`.", file=sys.stderr)
    return 1
  except TimeoutError as e:
    print(f"\nFAIL: {e}", file=sys.stderr)
    print("\nChart candidates (points present, sources may be missing):", file=sys.stderr)
    for c in sorted(seen_chart_candidates.values(), key=lambda x: x.card_id):
      print(f"- {c.card_id}: {c.title}", file=sys.stderr)
    print("\nCharts found (points+sources):", file=sys.stderr)
    for c in sorted(seen_charts.values(), key=lambda x: x.card_id):
      print(f"- {c.card_id}: {c.title}", file=sys.stderr)
    print("\nList candidates (items present, sources may be missing):", file=sys.stderr)
    for c in sorted(seen_list_candidates.values(), key=lambda x: x.card_id):
      print(f"- {c.card_id}: {c.title}", file=sys.stderr)
    print("\nLists found (items+sources):", file=sys.stderr)
    for c in sorted(seen_lists.values(), key=lambda x: x.card_id):
      print(f"- {c.card_id}: {c.title}", file=sys.stderr)
    return 1

  print("\nPASS: demo smoke test satisfied.")
  print("\nChart cards (points+sources):")
  for c in sorted(seen_charts.values(), key=lambda x: x.card_id):
    print(f"- {c.card_id}: {c.title}")
  print("\nList cards (items+sources):")
  for c in sorted(seen_lists.values(), key=lambda x: x.card_id):
    print(f"- {c.card_id}: {c.title}")
  return 0


def main() -> None:
  try:
    code = asyncio.run(_run())
  except KeyboardInterrupt:
    print("\nFAIL: interrupted", file=sys.stderr)
    sys.exit(130)
  except Exception as e:
    print(f"\nFAIL: unexpected error: {e}", file=sys.stderr)
    sys.exit(1)
  else:
    sys.exit(code)


if __name__ == "__main__":
  main()
