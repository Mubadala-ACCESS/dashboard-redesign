# Query Inventory — Current Dashboard

## 1. Station info
Sources:
- `station_map.py` -> `fetch_station_data()` reads `stations_info`
- `station_map.py` -> `fetch_station_location_data()` reads `stations_info`
- station page logic reads station info for headers, coordinates, and station labels

Purpose:
- populate markers
- populate station labels
- populate device type and status
- populate location summaries

## 2. Recent data
Sources:
- live-data page fetch path
- station freshness checks
- station data pages for latest values
- monitor loop for latest record inspection

Purpose:
- last reading
- live cards
- current values
- freshness / staleness logic

## 3. Metadata lookup
Sources:
- metadata modal
- metadata JSON files
- station details / instrumentation summaries

Purpose:
- variable definitions
- units
- instruments
- date coverage

## 4. Maintenance checks
Sources:
- `station_status_monitor.py`
- station-page maintenance / stale-data alerts

Purpose:
- mark station as active or maintenance
- display stale-data warnings

## 5. Graph data fetches
Sources:
- graph modules in `graphs/*`
- station time-series data fetches
- parameter-driven graph callbacks

Purpose:
- time-series charts
- aggregation
- parameter overlays
- sensor toggles

## Consolidation targets
Highest priority reads to centralize:
1. station summary lookup
2. latest reading lookup
3. metadata payload lookup
4. map marker payload
5. live-card payload
