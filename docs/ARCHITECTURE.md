# Architecture Overview

## Frontend
- **Pure HTML / CSS / JavaScript** served by FastAPI templates and static assets.
- **Leaflet** for the network map and station popups.
- **Plotly** for time-series charts, threshold bands, and event markers.
- **Quick View + Advanced Analysis** split on each station page.

## Backend
- **FastAPI** application in `app/main.py`.
- **MongoDashboardRepository** in `app/mongo_service.py` handles:
  - map filters and station lists
  - station summary and freshness
  - metadata tabs
  - latest cards and AQI interpretation
  - time-series extraction with aggregation
  - CSV/JSON exports
- **TTL cache** reduces repeated filter, station, and summary reads.

## Data adapters
### Current mode
The shipped application reads the current MongoDB collections directly:
- `stations_info`
- `station{station_num}` for IoT stations
- `f1_meteostation`
- `buoy_01`
- `fidas_nyuad`

### Target mode
The package also includes a PostgreSQL/PostGIS/TimescaleDB schema in:
- `database/postgresql_postgis_timescaledb.sql`

That schema is meant for the long-term production replacement so the same product can move away from direct MongoDB reads without redesigning the UI.

## Performance strategy
- connection pooling through PyMongo client configuration
- short-lived in-memory TTL caching
- tighter Mongo projections instead of full-document reads
- station-specific collection targeting rather than broad scans
- aggregation on the server side before returning chart payloads
- recommended MongoDB indexes in `database/mongodb_indexes.js`

## Pages
- `/` Discovery Hub
- `/station/{station_id}` Station detail page
- `/station/{station_id}/report` Printable report
- `/glossary` Environmental glossary
- `/alerts` Network alerts
- `/support` Support and workflow help

## API surface
- `GET /api/map/filters`
- `GET /api/map/stations`
- `GET /api/stations/{station_id}`
- `GET /api/stations/{station_id}/metadata`
- `GET /api/stations/{station_id}/latest`
- `GET /api/stations/{station_id}/timeseries`
- `GET /api/stations/{station_id}/status`
- `GET /api/stations/{station_id}/export.csv`
- `GET /api/stations/{station_id}/export.json`
- `GET /api/glossary`
- `GET /api/alerts`
