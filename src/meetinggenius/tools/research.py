from __future__ import annotations

from typing import Any

from meetinggenius.contracts import (
  HeadlinesResult,
  ResearchKind,
  ResearchResult,
  ResearchTask,
  WeatherHistoryResult,
)
from meetinggenius.contracts import HeadlinesData, WeatherHistoryData
from meetinggenius.tools.registry import ExternalResearchDisabledError, get_default_research_tool_registry


async def run_research_task(task: ResearchTask, *, no_browse: bool) -> ResearchResult:
  if task.tool_name:
    return await _run_tool_task(task, no_browse=no_browse)
  if task.kind is not None:
    return await _run_legacy_task(task, no_browse=no_browse)
  raise ValueError("Invalid ResearchTask: missing both tool_name and kind.")


async def _run_tool_task(task: ResearchTask, *, no_browse: bool) -> ResearchResult:
  tool_name = task.tool_name
  if not tool_name:
    raise ValueError("tool_name is required for tool-based research tasks")

  registry = get_default_research_tool_registry()
  try:
    tool_result = await registry.run(
      tool_name=tool_name,
      args=task.args or {},
      requires_browse=task.requires_browse,
      no_browse=no_browse,
    )
  except ExternalResearchDisabledError:
    raise
  except KeyError as e:
    raise ValueError(str(e)) from e

  data = tool_result.data
  citations = tool_result.citations

  if tool_name == "weather.history_by_month":
    weather = WeatherHistoryData.model_validate(data)
    return ResearchResult(
      task_id=task.task_id,
      result=WeatherHistoryResult(kind=ResearchKind.WEATHER_DECEMBER_HISTORY, data=weather),
      citations=citations,
    )

  if tool_name == "news.headlines_by_month":
    headlines = HeadlinesData.model_validate(data)
    return ResearchResult(
      task_id=task.task_id,
      result=HeadlinesResult(kind=ResearchKind.DECEMBER_HEADLINES, data=headlines),
      citations=citations,
    )

  raise ValueError(f"Unsupported research tool_name: {tool_name}")


async def _run_legacy_task(task: ResearchTask, *, no_browse: bool) -> ResearchResult:
  kind = task.kind
  if kind == ResearchKind.WEATHER_DECEMBER_HISTORY:
    if not task.location:
      raise ValueError("location is required for weather history research")
    years = task.years or 10
    month = task.month or 12
    args: dict[str, Any] = {"location": task.location, "month": month, "years": years, "unit": "both"}
    adapted = task.model_copy(update={"tool_name": "weather.history_by_month", "args": args, "requires_browse": True})
    return await _run_tool_task(adapted, no_browse=no_browse)

  if kind == ResearchKind.DECEMBER_HEADLINES:
    if not task.query:
      raise ValueError("query is required for headlines research")
    years = task.years or 5
    month = task.month or 12
    limit = int((task.assumptions or {}).get("limit") or 8)
    args = {"query": task.query, "month": month, "years": years, "limit": limit}
    adapted = task.model_copy(update={"tool_name": "news.headlines_by_month", "args": args, "requires_browse": True})
    return await _run_tool_task(adapted, no_browse=no_browse)

  raise ValueError(f"Unsupported research kind: {kind}")
