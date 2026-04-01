# Replacement Stack for the Dashboard

## Current problem
The current dashboard is implemented as a Dash multipage app with repeated direct MongoDB access across modules and callbacks.

## Target architecture
- FastAPI backend
- PostgreSQL + PostGIS data layer
- HTML/CSS/JavaScript frontend

## Why this replacement is better
1. Backend and frontend become cleanly separated
2. Data access can be centralized behind API endpoints
3. PostgreSQL/PostGIS is a better long-term fit for relational structure, filtering, and geospatial queries
4. The frontend can become cleaner, faster, and more maintainable
5. The dashboard can evolve beyond callback-heavy Dash patterns

## Expected backend service areas
- station summary API
- map station API
- latest readings API
- station metadata API
- maintenance / status API

## Expected frontend areas
- landing/map page
- station detail page
- live-data page
- metadata modal
- status / maintenance states