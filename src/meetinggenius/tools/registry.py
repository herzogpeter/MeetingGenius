from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from meetinggenius.contracts import Citation, HeadlinesData, WeatherHistoryData


class ExternalResearchDisabledError(RuntimeError):
  pass


@dataclass(frozen=True)
class ToolCallResult:
  data: BaseModel
  citations: list[Citation]


ToolHandler = Callable[[BaseModel], Awaitable[ToolCallResult]]


@dataclass(frozen=True)
class ResearchTool:
  name: str
  args_model: type[BaseModel]
  data_model: type[BaseModel]
  handler: ToolHandler


class ResearchToolRegistry:
  def __init__(self) -> None:
    self._tools: dict[str, ResearchTool] = {}

  def register(self, tool: ResearchTool) -> None:
    if tool.name in self._tools:
      raise ValueError(f"Tool already registered: {tool.name}")
    self._tools[tool.name] = tool

  def get(self, name: str) -> ResearchTool:
    try:
      return self._tools[name]
    except KeyError as e:
      raise KeyError(f"Unknown research tool: {name}") from e

  def list_tool_names(self) -> list[str]:
    return sorted(self._tools.keys())

  async def run(
    self,
    *,
    tool_name: str,
    args: dict[str, Any],
    requires_browse: bool,
    no_browse: bool,
  ) -> ToolCallResult:
    if requires_browse and no_browse:
      raise ExternalResearchDisabledError("External research is disabled (no_browse=True).")

    tool = self.get(tool_name)
    parsed_args = tool.args_model.model_validate(args)
    result = await tool.handler(parsed_args)

    # Validate outputs are consistent with the tool contract.
    tool.data_model.model_validate(result.data)
    for c in result.citations:
      Citation.model_validate(c)

    return result


_DEFAULT_REGISTRY: ResearchToolRegistry | None = None


def get_default_research_tool_registry() -> ResearchToolRegistry:
  global _DEFAULT_REGISTRY
  if _DEFAULT_REGISTRY is not None:
    return _DEFAULT_REGISTRY

  registry = ResearchToolRegistry()

  # Built-in tools (additive; safe to import lazily here).
  from meetinggenius.tools.headlines_gdelt import HeadlinesByMonthArgs, get_headlines_by_month
  from meetinggenius.tools.weather_open_meteo import WeatherHistoryByMonthArgs, get_weather_history_by_month

  async def _weather_handler(args: BaseModel) -> ToolCallResult:
    a = WeatherHistoryByMonthArgs.model_validate(args)
    data, citations = await get_weather_history_by_month(
      location=a.location,
      month=a.month,
      years=a.years,
      unit=a.unit,
    )
    return ToolCallResult(data=data, citations=citations)

  async def _headlines_handler(args: BaseModel) -> ToolCallResult:
    a = HeadlinesByMonthArgs.model_validate(args)
    data, citations = await get_headlines_by_month(
      query=a.query,
      month=a.month,
      years=a.years,
      limit=a.limit,
    )
    return ToolCallResult(data=data, citations=citations)

  registry.register(
    ResearchTool(
      name="weather.history_by_month",
      args_model=WeatherHistoryByMonthArgs,
      data_model=WeatherHistoryData,
      handler=_weather_handler,
    )
  )
  registry.register(
    ResearchTool(
      name="news.headlines_by_month",
      args_model=HeadlinesByMonthArgs,
      data_model=HeadlinesData,
      handler=_headlines_handler,
    )
  )

  _DEFAULT_REGISTRY = registry
  return registry
