# Functions to Pull Out of Dash Callbacks First

## First extraction wave
These should move behind backend services first.

### 1. Map marker payload builder
Reason:
- used by landing/map page
- currently tied to direct station fetch logic

Target backend service:
- `GET /api/map/stations`

### 2. Station summary payload
Reason:
- needed by station pages and live-data pages
- should not be rebuilt inside page callbacks

Target backend service:
- `GET /api/stations/{station_id}`

### 3. Latest readings payload
Reason:
- live-data page depends on recent values
- freshness logic depends on recent values

Target backend service:
- `GET /api/stations/{station_id}/latest`

### 4. Metadata payload
Reason:
- modal content should be centralized
- definitions and metadata should not be assembled ad hoc

Target backend service:
- `GET /api/stations/{station_id}/metadata`

### 5. Station status / freshness payload
Reason:
- maintenance logic and page alerts should share one backend truth

Target backend service:
- `GET /api/stations/{station_id}/status`
