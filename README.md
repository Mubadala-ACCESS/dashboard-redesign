# Mubadala ACCESS EcoMonitor Redesign

A production-oriented environmental monitoring dashboard built with:
- **Frontend:** HTML, CSS, and vanilla JavaScript
- **Backend:** FastAPI
- **Current data source:** existing MongoDB
- **Future data source:** PostgreSQL + PostGIS + TimescaleDB schema included

This package ships a complete redesigned application with:
- discovery hub map
- quick-view and advanced-analysis station workflows
- metadata modal and printable station reports
- glossary and alerts pages
- CSV and JSON export endpoints
- MongoDB performance index script
- PostgreSQL replacement schema
- Mongo-to-Postgres migration utility

---

## 1. Package structure

```text
maccess-dashboard-redesign/
  app/
    __init__.py
    air_quality.py
    cache.py
    main.py
    metadata_service.py
    mongo_service.py
    settings.py
    data/
      glossary.json
      thresholds.json
      metadata/
  frontend/
    static/
      css/main.css
      js/app.js
      js/home.js
      js/station.js
      img/favicon.svg
    templates/
  database/
    mongodb_indexes.js
    postgresql_postgis_timescaledb.sql
  scripts/
    migrate_mongo_to_postgres.py
  docs/
    ARCHITECTURE.md
  .env.example
  .gitignore
  Dockerfile
  docker-compose.yml
  requirements.txt
  README.md
```

---

## 2. What is included in the redesign

### Discovery Hub
- map-first homepage
- search by station name, ID, or station number
- filters for privacy, device type, and status
- public-facing purpose section
- onboarding modal
- mobile filter modal

### Station detail experience
- **Quick View** for public users
  - interpreted latest metrics
  - AQI-style particulate interpretation
  - event markers
  - freshness messaging
- **Advanced Analysis** for researchers
  - time-series charts
  - threshold bands
  - event overlays
  - metric selection
  - aggregation control
  - raw data preview
  - CSV and JSON export
  - buoy profile detail section

### Supporting pages
- glossary page
- alerts page
- support page
- printable report page

---

## 3. Supported current MongoDB collections

The shipped backend reads these collections directly:
- `stations_info`
- `station{station_num}` for IoT stations
- `f1_meteostation`
- `buoy_01`
- `fidas_nyuad`

It also supports the legacy special-station mapping:
- station `5463` -> `f1_meteostation`
- station `100` -> `fidas_nyuad`
- station `8394` -> `buoy_01`

---

## 4. Local development setup

### Prerequisites
- Python 3.11 or 3.12
- access to the existing MongoDB instance
- optional: PostgreSQL 16 + PostGIS + TimescaleDB for migration work

### Step 1: create environment file

Copy the example file:

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
MONGO_URI=mongodb://YOUR_HOST:27017/
MONGO_DB_NAME=all_stations_db
MONGO_STATIONS_INFO_COLLECTION=stations_info
MONGO_BUOY_COLLECTION=buoy_01
MONGO_METEO_COLLECTION=f1_meteostation
MONGO_FIDAS_COLLECTION=fidas_nyuad
APP_HOST=0.0.0.0
APP_PORT=8000
```

### Step 2: install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: run the application

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open:
- `http://localhost:8000/`

### Step 4: health check

```bash
curl http://localhost:8000/health
```

Expected result:
- JSON showing service name, `ok`, and the active Mongo database name.

---

## 5. Docker deployment

### Build and run with Docker

```bash
docker build -t maccess-ecomonitor .
docker run --rm -p 8000:8000 --env-file .env maccess-ecomonitor
```

### Run with Docker Compose

```bash
docker compose up --build
```

The included compose file starts:
- `web` FastAPI app
- `postgres` PostGIS container for the future relational migration path

The app still reads MongoDB in the current adapter, so your `.env` must point to a reachable Mongo instance.

---

## 6. Improve current MongoDB performance immediately

Apply the included index script:

```bash
mongosh "mongodb://YOUR_HOST:27017/all_stations_db" database/mongodb_indexes.js
```

What it does:
- adds fast lookup indexes for map filters and station search
- adds descending time indexes for all realtime collections
- adds station collection time indexes for `station####` collections

---

## 7. PostgreSQL replacement database

The long-term replacement schema is in:

```text
database/postgresql_postgis_timescaledb.sql
```

### What it gives you
- normalized station catalog
- metric catalog
- station metric definitions
- hypertables for observations
- dedicated buoy profile storage
- health snapshots and event storage
- materialized views for fast dashboard reads
- geospatial support through PostGIS

### Load the schema

```bash
psql "postgresql://postgres:postgres@localhost:5432/ecomonitor" -f database/postgresql_postgis_timescaledb.sql
```

---

## 8. Migrate MongoDB data into PostgreSQL

The migration utility is:

```text
scripts/migrate_mongo_to_postgres.py
```

### Environment variables needed

```env
MONGO_URI=mongodb://YOUR_HOST:27017/
MONGO_DB_NAME=all_stations_db
POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/ecomonitor
```

### Run the migration

```bash
python scripts/migrate_mongo_to_postgres.py
```

The migration script:
- upserts stations from `stations_info`
- migrates IoT station observations
- migrates special collections for meteo, Fidas, and buoy
- stores buoy profiles in a dedicated table
- refreshes materialized views after load

---

## 9. API endpoints

### Page routes
- `GET /`
- `GET /station/{station_id}`
- `GET /station/{station_id}/report`
- `GET /glossary`
- `GET /alerts`
- `GET /support`

### JSON routes
- `GET /health`
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

### Example queries

```bash
curl "http://localhost:8000/api/map/stations?privacy=all&device_type=all&status=Active&search="
```

```bash
curl "http://localhost:8000/api/stations/100/timeseries?period=7D&aggregation=1h"
```

```bash
curl -OJ "http://localhost:8000/api/stations/100/export.csv?period=30D&aggregation=1d"
```

---

## 10. Configuration reference

### Core application
- `APP_NAME`
- `APP_ENV`
- `APP_HOST`
- `APP_PORT`
- `APP_BASE_URL`
- `CORS_ORIGINS`

### MongoDB
- `MONGO_URI`
- `MONGO_DB_NAME`
- `MONGO_STATIONS_INFO_COLLECTION`
- `MONGO_BUOY_COLLECTION`
- `MONGO_METEO_COLLECTION`
- `MONGO_FIDAS_COLLECTION`
- `MONGO_MAX_POOL_SIZE`
- `MONGO_MIN_POOL_SIZE`
- `MONGO_SERVER_SELECTION_TIMEOUT_MS`
- `MONGO_CONNECT_TIMEOUT_MS`
- `MONGO_SOCKET_TIMEOUT_MS`

### Dashboard behavior
- `CACHE_TTL_SECONDS`
- `DEFAULT_TIMEZONE`
- `STALE_THRESHOLD_HOURS`
- `DEFAULT_MAP_LAT`
- `DEFAULT_MAP_LON`
- `DEFAULT_MAP_ZOOM`

---

## 11. Frontend customization

### Branding
Update:
- `frontend/templates/base.html`
- `frontend/static/css/main.css`
- `frontend/static/img/favicon.svg`

### Glossary content
Update:
- `app/data/glossary.json`

### Threshold bands
Update:
- `app/data/thresholds.json`

### Metadata tabs
Update the JSON files under:
- `app/data/metadata/`

---

## 12. Production recommendations

### App serving
- run behind Nginx or a cloud load balancer
- terminate TLS at the edge
- keep `uvicorn` behind a process manager or containers
- scale horizontally only after moving sessionless caching to Redis if needed

### Database
- keep Mongo indexes current until the relational migration is complete
- move long-term analytics reads to PostgreSQL/TimescaleDB
- refresh materialized views on a schedule once PostgreSQL becomes primary

### Monitoring
- track `/health`
- log request latency for `/api/map/stations`, `/api/stations/*/latest`, `/api/stations/*/timeseries`
- alert on stale station freshness counts and Mongo timeout rates

---

## 13. Validation checklist

After deployment, confirm:
- homepage loads and map renders
- filters work on desktop and mobile
- station popups open
- metadata modal opens
- station detail page loads
- charts render for IoT, meteo, buoy, and Fidas stations
- CSV/JSON export works
- printable report opens
- glossary and alerts pages load
- `/health` responds successfully

---

## 14. Notes

This package is designed so you can deploy the redesigned product immediately against the current MongoDB, then migrate to PostgreSQL without rebuilding the frontend or the service boundaries.
