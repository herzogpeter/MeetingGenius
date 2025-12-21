from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from meetinggenius.contracts import Citation, WeatherHistoryData, WeatherPoint


@dataclass(frozen=True)
class GeoLocation:
  label: str
  latitude: float
  longitude: float


async def geocode_location(location: str) -> tuple[GeoLocation, Citation]:
  url = "https://geocoding-api.open-meteo.com/v1/search"
  params = {"name": location, "count": 1, "language": "en", "format": "json"}
  async with httpx.AsyncClient(timeout=15.0) as client:
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

  results = data.get("results") or []
  if not results:
    raise ValueError(f"Could not geocode location: {location}")

  r0 = results[0]
  label = ", ".join([p for p in [r0.get("name"), r0.get("admin1"), r0.get("country")] if p])
  geo = GeoLocation(label=label, latitude=float(r0["latitude"]), longitude=float(r0["longitude"]))
  cite = Citation(url=str(httpx.URL(url).copy_merge_params(params)), title="Open-Meteo Geocoding API")
  return geo, cite


async def fetch_december_avg_temps(
  *,
  latitude: float,
  longitude: float,
  start_year: int,
  end_year: int,
) -> tuple[list[WeatherPoint], list[Citation]]:
  points: list[WeatherPoint] = []
  citations: list[Citation] = []

  base_url = "https://archive-api.open-meteo.com/v1/archive"
  async with httpx.AsyncClient(timeout=20.0) as client:
    for year in range(start_year, end_year + 1):
      start_date = f"{year}-12-01"
      end_date = f"{year}-12-31"
      params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "temperature_2m_mean",
        "timezone": "UTC",
      }
      resp = await client.get(base_url, params=params)
      resp.raise_for_status()
      payload = resp.json()

      daily = (payload.get("daily") or {}).get("temperature_2m_mean") or []
      temps = [t for t in daily if t is not None]
      if not temps:
        continue

      avg_c = float(sum(temps) / len(temps))
      avg_f = (avg_c * 9.0 / 5.0) + 32.0
      points.append(WeatherPoint(year=year, avg_temp_c=avg_c, avg_temp_f=avg_f))

      citations.append(
        Citation(
          url=str(httpx.URL(base_url).copy_merge_params(params)),
          title="Open-Meteo Historical Weather API (archive)",
          retrieved_at=datetime.now(tz=UTC),
        )
      )

  return points, citations


async def get_weather_history_december(location: str, years: int = 10) -> tuple[WeatherHistoryData, list[Citation]]:
  geo, geo_cite = await geocode_location(location)

  now_year = datetime.now(tz=UTC).year
  end_year = now_year - 1
  start_year = max(1900, end_year - (years - 1))

  points, citations = await fetch_december_avg_temps(
    latitude=geo.latitude,
    longitude=geo.longitude,
    start_year=start_year,
    end_year=end_year,
  )

  data = WeatherHistoryData(location_label=geo.label, month=12, points=points)
  return data, [geo_cite, *citations]
