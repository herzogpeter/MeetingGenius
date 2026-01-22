from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, model_validator


class TranscriptEvent(BaseModel):
  model_config = ConfigDict(extra="forbid")

  timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
  event_id: str | None = None
  speaker: str | None = None
  text: str
  confidence: float | None = Field(default=None, ge=0.0, le=1.0)
  is_final: bool = True


class Citation(BaseModel):
  model_config = ConfigDict(extra="forbid")

  url: AnyUrl
  title: str | None = None
  retrieved_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
  published_at: datetime | None = None


class ResearchKind(str, Enum):
  WEATHER_DECEMBER_HISTORY = "weather_december_history"
  DECEMBER_HEADLINES = "december_headlines"


class WeatherPoint(BaseModel):
  model_config = ConfigDict(extra="forbid")

  year: int = Field(ge=1900, le=3000)
  avg_temp_c: float
  avg_temp_f: float


class WeatherHistoryData(BaseModel):
  model_config = ConfigDict(extra="forbid")

  location_label: str
  month: int = Field(ge=1, le=12)
  points: list[WeatherPoint]


class HeadlineItem(BaseModel):
  model_config = ConfigDict(extra="forbid")

  title: str
  url: AnyUrl
  published_at: datetime | None = None
  source: str | None = None


class HeadlinesData(BaseModel):
  model_config = ConfigDict(extra="forbid")

  query: str
  items: list[HeadlineItem]


class ResearchTask(BaseModel):
  model_config = ConfigDict(extra="forbid")

  task_id: str
  tool_name: str | None = Field(
    default=None,
    description="Tool identifier for generic research tasks (preferred). Example: 'weather.history_by_month'.",
  )
  args: dict[str, Any] = Field(
    default_factory=dict,
    description="Tool arguments for generic research tasks (preferred).",
  )
  requires_browse: bool = Field(
    default=True,
    description="Whether this task requires external web access/browsing.",
  )

  # Legacy fields (deprecated): kept for backward compatibility with existing orchestrator prompts.
  kind: ResearchKind | None = Field(default=None, description="DEPRECATED: use tool_name + args instead.")
  query: str | None = Field(default=None, description="DEPRECATED: use tool_name + args instead.")
  location: str | None = Field(default=None, description="DEPRECATED: use tool_name + args instead.")
  month: int | None = Field(default=None, ge=1, le=12, description="DEPRECATED: use tool_name + args instead.")
  years: int | None = Field(default=None, ge=1, le=50, description="DEPRECATED: use tool_name + args instead.")
  assumptions: dict[str, Any] = Field(default_factory=dict)

  @model_validator(mode="after")
  def _validate_task_kind_or_tool(self) -> "ResearchTask":
    if not self.tool_name and self.kind is None:
      raise ValueError("ResearchTask must include either tool_name or kind (legacy).")
    return self


class WeatherHistoryResult(BaseModel):
  model_config = ConfigDict(extra="forbid")

  kind: Literal[ResearchKind.WEATHER_DECEMBER_HISTORY]
  data: WeatherHistoryData


class HeadlinesResult(BaseModel):
  model_config = ConfigDict(extra="forbid")

  kind: Literal[ResearchKind.DECEMBER_HEADLINES]
  data: HeadlinesData


ResearchData = Annotated[
  Union[WeatherHistoryResult, HeadlinesResult],
  Field(discriminator="kind"),
]


class ResearchResult(BaseModel):
  model_config = ConfigDict(extra="forbid")

  task_id: str
  result: ResearchData
  citations: list[Citation] = Field(default_factory=list)


class CardKind(str, Enum):
  CHART = "chart"
  LIST = "list"


class ChartSeriesPoint(BaseModel):
  model_config = ConfigDict(extra="forbid")

  label: str
  value: float


class ChartCardProps(BaseModel):
  model_config = ConfigDict(extra="forbid")

  title: str
  subtitle: str | None = None
  x_label: str = "Year"
  y_label: str = "Value"
  points: list[ChartSeriesPoint]


class ListItem(BaseModel):
  model_config = ConfigDict(extra="forbid")

  text: str
  url: AnyUrl | None = None
  meta: str | None = None


class ListCardProps(BaseModel):
  model_config = ConfigDict(extra="forbid")

  title: str
  items: list[ListItem]


class ChartCard(BaseModel):
  model_config = ConfigDict(extra="forbid")

  card_id: str
  kind: Literal[CardKind.CHART]
  props: ChartCardProps
  sources: list[Citation] = Field(default_factory=list)


class ListCard(BaseModel):
  model_config = ConfigDict(extra="forbid")

  card_id: str
  kind: Literal[CardKind.LIST]
  props: ListCardProps
  sources: list[Citation] = Field(default_factory=list)


Card = Annotated[Union[ChartCard, ListCard], Field(discriminator="kind")]


class Rect(BaseModel):
  model_config = ConfigDict(extra="forbid")

  x: float
  y: float
  w: float = Field(gt=0)
  h: float = Field(gt=0)


class LayoutHint(BaseModel):
  model_config = ConfigDict(extra="forbid")

  near_card_id: str | None = None
  column: int | None = None
  order: int | None = None


class CreateCardAction(BaseModel):
  model_config = ConfigDict(extra="forbid")

  type: Literal["create_card"] = "create_card"
  card: Card
  rect: Rect | None = None
  layout_hint: LayoutHint | None = None


class UpdateCardAction(BaseModel):
  model_config = ConfigDict(extra="forbid")

  type: Literal["update_card"] = "update_card"
  card_id: str
  patch: dict[str, Any]
  citations: list[Citation] | None = None


class MoveCardAction(BaseModel):
  model_config = ConfigDict(extra="forbid")

  type: Literal["move_card"] = "move_card"
  card_id: str
  rect: Rect


class DismissCardAction(BaseModel):
  model_config = ConfigDict(extra="forbid")

  type: Literal["dismiss_card"] = "dismiss_card"
  card_id: str
  reason: str | None = None


BoardAction = Annotated[
  Union[CreateCardAction, UpdateCardAction, MoveCardAction, DismissCardAction],
  Field(discriminator="type"),
]


class ArtifactProposal(BaseModel):
  model_config = ConfigDict(extra="forbid")

  proposal_id: str
  title: str
  kind: CardKind
  rationale: str
  priority: int = Field(default=50, ge=0, le=100)
  required_tasks: list[str] = Field(default_factory=list)


class OrchestratorDecision(BaseModel):
  model_config = ConfigDict(extra="forbid")

  research_tasks: list[ResearchTask] = Field(default_factory=list)
  proposals: list[ArtifactProposal] = Field(default_factory=list)
  assumptions: dict[str, Any] = Field(default_factory=dict)


class BoardState(BaseModel):
  model_config = ConfigDict(extra="forbid")

  cards: dict[str, Card] = Field(default_factory=dict)
  layout: dict[str, Rect] = Field(default_factory=dict)
  dismissed: dict[str, str] = Field(default_factory=dict)

  @classmethod
  def empty(cls) -> "BoardState":
    return cls()


class MindmapPoint(BaseModel):
  model_config = ConfigDict(extra="forbid")

  x: float
  y: float


class MindmapNode(BaseModel):
  model_config = ConfigDict(extra="forbid")

  node_id: str
  parent_id: str | None = None
  text: str
  collapsed: bool = False
  sources: list[Citation] = Field(default_factory=list)


class MindmapState(BaseModel):
  model_config = ConfigDict(extra="forbid")

  root_id: str = "mm:root"
  nodes: dict[str, MindmapNode] = Field(default_factory=dict)
  layout: dict[str, MindmapPoint] = Field(default_factory=dict)

  @classmethod
  def empty(cls) -> "MindmapState":
    return cls()


class UpsertMindmapNodeAction(BaseModel):
  model_config = ConfigDict(extra="forbid")

  type: Literal["upsert_node"] = "upsert_node"
  node: MindmapNode


class SetMindmapNodePosAction(BaseModel):
  model_config = ConfigDict(extra="forbid")

  type: Literal["set_node_pos"] = "set_node_pos"
  node_id: str
  pos: MindmapPoint


class SetMindmapNodeCollapsedAction(BaseModel):
  model_config = ConfigDict(extra="forbid")

  type: Literal["set_collapsed"] = "set_collapsed"
  node_id: str
  collapsed: bool


class RenameMindmapNodeAction(BaseModel):
  model_config = ConfigDict(extra="forbid")

  type: Literal["rename_node"] = "rename_node"
  node_id: str
  text: str


class ReparentMindmapNodeAction(BaseModel):
  model_config = ConfigDict(extra="forbid")

  type: Literal["reparent_node"] = "reparent_node"
  node_id: str
  new_parent_id: str | None


class DeleteMindmapSubtreeAction(BaseModel):
  model_config = ConfigDict(extra="forbid")

  type: Literal["delete_subtree"] = "delete_subtree"
  node_id: str


MindmapAction = Annotated[
  Union[
    UpsertMindmapNodeAction,
    SetMindmapNodePosAction,
    SetMindmapNodeCollapsedAction,
    RenameMindmapNodeAction,
    ReparentMindmapNodeAction,
    DeleteMindmapSubtreeAction,
  ],
  Field(discriminator="type"),
]


@dataclass(frozen=True)
class ToolingPolicy:
  no_browse: bool = False
  max_cards_per_minute: int = 2
