# Dashboard Architecture Audit — Baseline

## 1. Current framework
The current dashboard is a Dash multipage application.
It uses `use_pages=True` and renders the app through `dash.page_container`.

## 2. Main modules reviewed
- app.py
- station_map.py
- station_status_monitor.py
- pages/map_view.py
- pages/live_data_view.py
- pages/iot_meteo_visualization.py
- graphs/iot_graphs.py
- graphs/meteo_graphs.py
- graphs/buoy_graphs.py
- graphs/fidas_graphs.py

## 3. Baseline page structure
- Landing / map page
- Station detail pages
- Live-data page
- Metadata modal
- Maintenance / stale-data state
- Fidas page embedded via iframe

## 4. Key architectural observations
- The app is page-driven inside Dash rather than API-first.
- Multiple modules connect directly to MongoDB.
- Data access is mixed with presentation logic.
- Background status monitoring is started inside the dashboard app process.
- Station health, stale-data checks, and live-data rendering are tightly coupled to page behavior.
- The architecture is workable for a prototype but harder to scale, test, and optimize.

## 5. Why this is now a redesign candidate
- Frontend and backend are too tightly coupled.
- Direct database access is repeated across page modules.
- The UX needs clearer pathways for non-specialists.
- The current structure makes long-term maintainability and performance optimization harder.