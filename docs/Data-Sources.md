# Data Sources (Prototype)

## Weather (historical temperatures)

Candidate sources (choose 1 for MVP):

- Open-Meteo (simple API, good for prototypes)
- Meteostat (historical station data; may require more handling)
- NOAA (authoritative, but more setup)

Requirements:

- Ability to query by location + date range
- Citation/linkable provenance for displayed datasets
- Caching to reduce latency and rate-limit risk

## Headlines (December over past 5 years)

Candidate sources:

- GDELT (broad coverage, queryable; good prototype fit)
- NewsAPI / other commercial APIs (may require key/terms compliance)

Requirements:

- Query by date range + optional location/topic
- Return URL + publisher + published date for citation

