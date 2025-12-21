from __future__ import annotations

from datetime import UTC, datetime

import httpx

from meetinggenius.contracts import Citation, HeadlineItem, HeadlinesData


def _to_gdelt_dt(dt: datetime) -> str:
  return dt.astimezone(UTC).strftime("%Y%m%d%H%M%S")


async def get_december_headlines(
  *,
  query: str,
  years: int = 5,
  max_per_year: int = 8,
) -> tuple[HeadlinesData, list[Citation]]:
  base_url = "https://api.gdeltproject.org/api/v2/doc/doc"
  now_year = datetime.now(tz=UTC).year
  start_year = max(1900, now_year - years)
  end_year = now_year - 1

  items: list[HeadlineItem] = []
  citations: list[Citation] = []

  async with httpx.AsyncClient(timeout=20.0) as client:
    for year in range(start_year, end_year + 1):
      start = datetime(year=year, month=12, day=1, tzinfo=UTC)
      end = datetime(year=year, month=12, day=31, hour=23, minute=59, second=59, tzinfo=UTC)

      params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max_per_year,
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
        items.append(
          HeadlineItem(
            title=str(title),
            url=str(url),
            source=a.get("sourceCountry") or a.get("source") or None,
            published_at=_parse_dt(a.get("seendate")),
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
