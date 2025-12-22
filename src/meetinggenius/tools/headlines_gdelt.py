from __future__ import annotations

import calendar
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from meetinggenius.contracts import Citation, HeadlineItem, HeadlinesData


def _to_gdelt_dt(dt: datetime) -> str:
  return dt.astimezone(UTC).strftime("%Y%m%d%H%M%S")


class HeadlinesByMonthArgs(BaseModel):
  query: str
  month: int = Field(default=12, ge=1, le=12)
  years: int = Field(default=5, ge=1, le=50)
  limit: int = Field(default=8, ge=1, le=100)


async def get_december_headlines(
  *,
  query: str,
  years: int = 5,
  max_per_year: int = 8,
) -> tuple[HeadlinesData, list[Citation]]:
  data, citations = await get_headlines_by_month(query=query, month=12, years=years, limit=max_per_year)
  return data, citations


async def get_headlines_by_month(
  *,
  query: str,
  month: int = 12,
  years: int = 5,
  limit: int = 8,
) -> tuple[HeadlinesData, list[Citation]]:
  base_url = "https://api.gdeltproject.org/api/v2/doc/doc"
  now_year = datetime.now(tz=UTC).year
  start_year = max(1900, now_year - years)
  end_year = now_year - 1

  items: list[HeadlineItem] = []
  citations: list[Citation] = []

  async with httpx.AsyncClient(timeout=20.0) as client:
    for year in range(start_year, end_year + 1):
      last_day = calendar.monthrange(year, month)[1]
      start = datetime(year=year, month=month, day=1, tzinfo=UTC)
      end = datetime(year=year, month=month, day=last_day, hour=23, minute=59, second=59, tzinfo=UTC)

      params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": limit,
        "sort": "HybridRel",
        "startdatetime": _to_gdelt_dt(start),
        "enddatetime": _to_gdelt_dt(end),
      }
      resp = await client.get(base_url, params=params)
      resp.raise_for_status()
      payload = resp.json()

      articles = payload.get("articles") or []
      for a in articles:
        title = a.get("title")
        url = a.get("url")
        if not title or not url:
          continue
        a_any: dict[str, Any] = a if isinstance(a, dict) else {}
        items.append(
          HeadlineItem(
            title=str(title),
            url=str(url),
            source=a_any.get("sourceCountry") or a_any.get("source") or None,
            published_at=_parse_dt(a_any.get("seendate")),
          )
        )

      citations.append(
        Citation(
          url=str(httpx.URL(base_url).copy_merge_params(params)),
          title="GDELT 2.1 DOC API",
        )
      )

  data = HeadlinesData(query=query, items=items)
  return data, citations


def _parse_dt(value: str | None) -> datetime | None:
  if not value:
    return None
  try:
    # Common GDELT format: "2024-12-03 12:34:56.000"
    v = value.replace(".000", "")
    return datetime.fromisoformat(v).replace(tzinfo=UTC)
  except ValueError:
    return None
