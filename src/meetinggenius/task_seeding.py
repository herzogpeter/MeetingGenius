from __future__ import annotations

import uuid

from meetinggenius.contracts import ResearchKind, ResearchTask


def auto_seed_research_tasks(text: str, *, default_location: str) -> list[ResearchTask]:
  lower = text.lower()
  tasks: list[ResearchTask] = []
  if "temperature" in lower and "december" in lower:
    tasks.append(
      ResearchTask(
        task_id=str(uuid.uuid4()),
        kind=ResearchKind.WEATHER_DECEMBER_HISTORY,
        query="December average temperature history (last 10 years)",
        location=default_location,
        month=12,
        years=10,
        assumptions={"location_inferred": True, "location_value": default_location},
      )
    )
  if "headline" in lower and "december" in lower:
    tasks.append(
      ResearchTask(
        task_id=str(uuid.uuid4()),
        kind=ResearchKind.DECEMBER_HEADLINES,
        query=f"{default_location} weather December headline",
        location=default_location,
        month=12,
        years=5,
        assumptions={"query_auto_seeded": True},
      )
    )
  return tasks

