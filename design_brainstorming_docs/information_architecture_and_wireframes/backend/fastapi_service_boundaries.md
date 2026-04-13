# Initial FastAPI Service Boundaries

## Service 1: Map Service
Purpose:
- return filtered station markers and map-facing summaries

Endpoints:
- `GET /api/map/stations`
- `GET /api/map/filters`

Responsibilities:
- filter station list
- return marker metadata
- return filter values

## Service 2: Station Summary Service
Purpose:
- return station identity and overview payloads

Endpoints:
- `GET /api/stations/{station_id}`
- `GET /api/stations/{station_id}/status`

Responsibilities:
- station name
- type
- coordinates
- freshness
- status
- quick summary

## Service 3: Live Readings Service
Purpose:
- return latest values and live cards

Endpoints:
- `GET /api/stations/{station_id}/latest`
- `GET /api/stations/{station_id}/latest/cards`

Responsibilities:
- current values
- min/max summaries
- threshold tags
- last update timestamp

## Service 4: Metadata Service
Purpose:
- return metadata and glossary-support payloads

Endpoints:
- `GET /api/stations/{station_id}/metadata`

Responsibilities:
- instruments
- variable definitions
- units
- date coverage
- glossary-ready labels

## Service 5: Time-Series Service
Purpose:
- return chart data for advanced analysis

Endpoints:
- `GET /api/stations/{station_id}/timeseries`

Responsibilities:
- parameter selection
- time range
- aggregation
- sensor toggles
