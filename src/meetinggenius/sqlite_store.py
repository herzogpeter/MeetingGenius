from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from meetinggenius.contracts import BoardState


BOARD_STATE_KEY = "board_state"
DEFAULT_LOCATION_KEY = "default_location"
NO_BROWSE_KEY = "no_browse"


def _repo_root() -> Path:
  return Path(__file__).resolve().parents[2]


def resolve_db_path() -> Path:
  raw = os.getenv("MEETINGGENIUS_DB_PATH") or "meetinggenius.sqlite3"
  path = Path(raw)
  if not path.is_absolute():
    path = _repo_root() / path
  return path


def _utc_now_iso() -> str:
  return datetime.now(tz=UTC).isoformat()


class SQLiteKVStore:
  def __init__(self, path: Path) -> None:
    self._path = path

  @property
  def path(self) -> Path:
    return self._path

  def _connect(self) -> sqlite3.Connection:
    self._path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(self._path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(
      "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)"
    )
    return conn

  def get_value_json(self, key: str) -> str | None:
    with self._connect() as conn:
      row = conn.execute("SELECT value_json FROM kv WHERE key = ?", (key,)).fetchone()
      if not row:
        return None
      value = row[0]
      return value if isinstance(value, str) else None

  def set_many(self, values: dict[str, str]) -> None:
    now = _utc_now_iso()
    rows = [(k, v, now) for k, v in values.items()]
    with self._connect() as conn:
      conn.executemany(
        "INSERT INTO kv (key, value_json, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
        rows,
      )

  def delete_many(self, keys: list[str]) -> None:
    if not keys:
      return
    with self._connect() as conn:
      conn.executemany("DELETE FROM kv WHERE key = ?", [(k,) for k in keys])


def load_board_state(value_json: str) -> BoardState:
  data = json.loads(value_json)
  return BoardState.model_validate(data)


def load_default_location(value_json: str) -> str | None:
  value = json.loads(value_json)
  return value if isinstance(value, str) and value.strip() else None


def load_no_browse(value_json: str) -> bool | None:
  value = json.loads(value_json)
  return value if isinstance(value, bool) else None


def dump_board_state(state: BoardState) -> str:
  return json.dumps(state.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))


def dump_default_location(value: str | None) -> str:
  return json.dumps(value, ensure_ascii=False)


def dump_no_browse(value: bool | None) -> str:
  return json.dumps(value, ensure_ascii=False)


@dataclass
class DebouncedStatePersister:
  store: SQLiteKVStore
  snapshot_provider: Callable[[], Awaitable[tuple[BoardState, str | None, bool | None]]]
  debounce_seconds: float = 1.0
  _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  _event: asyncio.Event = field(default_factory=asyncio.Event)
  _task: asyncio.Task[None] | None = None
  _pending_save: bool = False
  _pending_clear: bool = False
  _last_op_at: float = 0.0

  async def schedule_save(self) -> None:
    async with self._lock:
      self._pending_save = True
      self._ensure_task_locked()
      self._event.set()

  async def schedule_clear(self) -> None:
    async with self._lock:
      self._pending_clear = True
      self._pending_save = False
      self._ensure_task_locked()
      self._event.set()

  def _ensure_task_locked(self) -> None:
    if self._task is None or self._task.done():
      self._task = asyncio.create_task(self._run_loop())

  async def _run_loop(self) -> None:
    while True:
      await self._event.wait()
      self._event.clear()

      async with self._lock:
        pending_clear = self._pending_clear
        pending_save = self._pending_save and not pending_clear
        self._pending_clear = False
        self._pending_save = False

      if pending_save:
        elapsed = time.monotonic() - self._last_op_at
        delay = max(0.0, self.debounce_seconds - elapsed)
        if delay > 0:
          await asyncio.sleep(delay)

      self._last_op_at = time.monotonic()

      if pending_clear:
        await asyncio.to_thread(self.store.delete_many, [BOARD_STATE_KEY, DEFAULT_LOCATION_KEY, NO_BROWSE_KEY])
        continue

      if pending_save:
        board_state, default_location, no_browse = await self.snapshot_provider()
        payload = {
          BOARD_STATE_KEY: dump_board_state(board_state),
          DEFAULT_LOCATION_KEY: dump_default_location(default_location),
          NO_BROWSE_KEY: dump_no_browse(no_browse),
        }
        await asyncio.to_thread(self.store.set_many, payload)
        continue

      async with self._lock:
        if not self._pending_clear and not self._pending_save:
          return
