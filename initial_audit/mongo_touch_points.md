# MongoDB Dependency Points — Current Dashboard

## 1. app.py
- Starts dashboard app process
- Starts background station monitor thread inside the same process

## 2. station_map.py
- Creates a MongoClient in StationMap.__init__
- Reads `stations_info`
- Reads individual station collections like `station{station_num}`
- Builds map markers directly from Mongo-backed station data

## 3. pages/map_view.py
- Reads Mongo configuration
- Creates StationMap with Mongo URI and database name
- Depends on StationMap data fetches for map rendering and filtering
- Uses metadata files alongside Mongo-backed station content

## 4. pages/iot_meteo_visualization.py
- Creates MongoClient directly
- Reads `stations_info`
- Adds location info by querying Mongo during station-page logic
- Ties station rendering to direct database access

## 5. pages/live_data_view.py
- Depends on IoTGraphs, which is part of the Mongo-backed graph layer
- Live page is route-based and refresh-oriented
- Current implementation is tightly coupled to data-fetch logic

## 6. Maintenance / stale-data logic
- Maintenance modal checks recent data directly from Mongo
- Uses a six-hour freshness check on page load / route changes

## 7. station_status_monitor.py
- Opens MongoClient directly
- Reads `stations_info`
- Reads latest records from station collections
- Updates station status in Mongo
- Runs continuously in a loop

## 8. Why this matters
- Mongo access is repeated in multiple modules
- Query logic is not centralized
- Presentation logic and database logic are mixed
- This makes performance tuning and API-first redesign harder