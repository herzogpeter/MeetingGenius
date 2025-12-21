from __future__ import annotations

from meetinggenius.contracts import (
  HeadlinesResult,
  ResearchKind,
  ResearchResult,
  ResearchTask,
  WeatherHistoryResult,
)
from meetinggenius.tools.headlines_gdelt import get_december_headlines
from meetinggenius.tools.weather_open_meteo import get_weather_history_december


async def run_research_task(task: ResearchTask, *, no_browse: bool) -> ResearchResult:
  if no_browse:
    raise RuntimeError("External research is disabled (no_browse=True).")

  if task.kind == ResearchKind.WEATHER_DECEMBER_HISTORY:
    if not task.location:
      raise ValueError("location is required for weather history research")
    years = task.years or 10
    data, citations = await get_weather_history_december(task.location, years=years)
    return ResearchResult(
      task_id=task.task_id,
      result=WeatherHistoryResult(kind=ResearchKind.WEATHER_DECEMBER_HISTORY, data=data),
      citations=citations,
    )

  if task.kind == ResearchKind.DECEMBER_HEADLINES:
    years = task.years or 5
    data, citations = await get_december_headlines(query=task.query, years=years)
    return ResearchResult(
      task_id=task.task_id,
      result=HeadlinesResult(kind=ResearchKind.DECEMBER_HEADLINES, data=data),
      citations=citations,
    )

  raise ValueError(f"Unsupported research kind: {task.kind}")

