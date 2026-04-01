# Current State — ACCESS Monitoring Dashboard
**Folder:** `current_views_and_code`  
**Date:** 2026-04-01  
**Audit phase:** Initial dashboard baseline / forensic current-state capture

---

## 1. Purpose of this document

This file records the current baseline state of the ACCESS monitoring dashboard before redesign and replatforming work begins.

It captures:

- the current visible interface
- the main user-facing views
- the current architectural pattern
- the major UX, maintainability, and performance issues
- the code snapshot used for the audit

This is intended to serve as the baseline reference for the redesign effort.

---

## 2. Files included in this folder

This folder should contain:

- `01_homepage.jpg`
- `02_station_info.jpg`
- `03_station_metadata.jpg`
- `04_station_data.png`
- `dashboard-V1.txt`

Code snapshot link:

[Download the current dashboard code snapshot](./dashboard-V1.txt)

---

## 3. Current visible dashboard views

### 3.1 Homepage / map view

This is the current landing view of the dashboard. It presents the monitoring network on a map with a left-hand filter panel.

![Current homepage / map view](./01_homepage.jpg)

#### Observations
- The map is the dominant content area.
- Filters are available for:
  - privacy
  - device type
  - status
- Search is available at the top of the sidebar.
- The page is functional and information-rich, but it does not clearly explain:
  - what the user is looking at
  - how to use the dashboard
  - the difference between a quick public-facing path and a deeper scientific path
- The visual hierarchy is workable but flatter than ideal.
- The interface assumes some familiarity with the system.

---

### 3.2 Station info popup on map

This is the station popup shown when a user clicks a station marker on the map.

![Current station info popup](./02_station_info.jpg)

#### Observations
- The popup includes:
  - device type badge
  - station name
  - latitude
  - longitude
  - action links
- The popup already contains useful structure and branding.
- The popup is one of the stronger pieces of the current interface.
- However, it still lacks more user-friendly interpretation and next-step guidance.
- The action choices are useful, but the meaning of the station and the type of data available are not explained clearly enough for a first-time user.

---

### 3.3 Station metadata modal

This is the metadata modal opened from the station popup.

![Current station metadata modal](./03_station_metadata.jpg)

#### Observations
- The modal includes:
  - summary information
  - earliest and latest data
  - measurement frequency
  - instrument information
  - a parameter table with descriptor, units, and definitions
- This is a strong scientific support feature.
- It is one of the clearest parts of the current dashboard for users who need structured metadata.
- It could still be improved by:
  - better hierarchy
  - clearer glossary-style explanations
  - better grouping for non-specialists
  - more polished visual rhythm and spacing

---

### 3.4 Station data page

This is the detailed station data page.

![Current station data page](./04_station_data.png)

#### Observations
- The left sidebar includes:
  - display period
  - aggregation
  - parameter selection
  - download action
  - individual sensor readings toggle
- The main panel shows multiple time-series graphs.
- This page is powerful for scientific users.
- It is also visually dense and can feel overwhelming.
- The station summary does not lead strongly enough before the denser graph controls.
- The layout is more analysis-first than guidance-first.
- It would benefit from:
  - clearer station summary at the top
  - calmer grouping
  - better progressive disclosure
  - a clearer distinction between summary and advanced analysis

---

## 4. Current user experience state

### 4.1 What currently works well
- The dashboard already supports multiple meaningful views:
  - map exploration
  - station popup details
  - metadata modal
  - station data analysis
- The branding is already aligned with the ACCESS / NYU purple visual language.
- The station metadata modal is useful and relatively well structured.
- The dashboard already supports device-type exploration across a geographically distributed network.
- The station data page supports detailed scientific inspection.

### 4.2 Current experience gaps
- The dashboard does not yet clearly answer:
  - **What am I looking at?**
  - **Who is this for?**
  - **What should I do first?**
- There is no strong onboarding or “How to use this dashboard” guidance.
- The current reading order is more system-oriented than user-oriented.
- Non-specialists may find the experience harder to interpret.
- Scientific depth exists, but it is surfaced too early and too densely in some places.
- Search and filters need stronger hierarchy.
- The visual language is functional but not yet polished enough for a high-confidence public or leadership-facing experience.

---

## 5. Current architecture summary

The current dashboard is implemented as a **Dash multipage application**.

### Architectural characteristics
- The application is built around Dash pages rather than an API-first backend.
- Rendering and data access are tightly coupled.
- Multiple modules access MongoDB directly.
- A background monitoring thread is started from inside the application process.
- Page logic, database logic, and view logic are not as cleanly separated as they should be for long-term maintainability.

### Current code snapshot included
The current code snapshot is included in this folder as:

[dashboard-V1.txt](./dashboard-V1.txt)

---

## 6. Current code structure under audit

The current code snapshot includes the following major components:

### App shell
- `app.py`

### Core map and monitoring logic
- `station_map.py`
- `station_status_monitor.py`

### Pages
- `pages/map_view.py`
- `pages/live_data_view.py`
- `pages/iot_meteo_visualization.py`
- `pages/buoy_visualization.py`
- `pages/fidas_vizualization.py`

### Graph modules
- `graphs/iot_graphs.py`
- `graphs/meteo_graphs.py`
- `graphs/buoy_graphs.py`
- `graphs/fidas_graphs.py`

### Styling and assets
- `assets/theme.css`
- map and device icons
- logo assets

### Metadata files
- `metadata/*.json`

---

## 7. Forensic architecture findings

### 7.1 Dash is currently acting as both UI shell and application runtime
The dashboard is currently using Dash not only for rendering, but also as the main operational shell for page behavior and dashboard execution.

### 7.2 Direct MongoDB access is spread across the codebase
The current architecture relies on direct MongoDB access in multiple places rather than a centralized service layer.

This means:
- data access logic is repeated
- query behavior is harder to optimize
- backend changes are harder to isolate
- frontend and backend concerns are mixed together

### 7.3 Background monitoring is coupled to the app process
The dashboard starts the station status monitor from the main application process.

This means:
- monitoring is tied to app execution
- operational concerns are coupled with page serving
- scaling and reliability become more fragile over time

### 7.4 Current design is stronger for internal scientific use than for mixed audiences
The existing interface contains real analytical power, but it is still oriented more toward technical users than toward a mixed audience of:
- non-specialists
- communications users
- leadership
- external visitors
- scientists

### 7.5 Visual system exists but is not fully mature
The dashboard already has a recognizable ACCESS / NYU visual identity, but the interface still feels flatter and more utilitarian than it should for a polished production system.

---

## 8. Current MongoDB dependence

The current dashboard appears to use MongoDB as the operational data source for:
- station information
- recent readings
- time-series data
- station status logic
- metadata-linked page behavior

### Why this matters
For a richer long-term dashboard architecture, direct page-level MongoDB reads will become a liability because they:
- increase coupling
- make performance tuning harder
- make refactoring harder
- reduce backend flexibility

---

## 9. Current redesign implications

Based on this baseline, the redesign should not be treated as cosmetic only.

The redesign needs to address:

### UX / interface
- better onboarding
- stronger hierarchy
- clearer summary-first flow
- clearer user pathways
- more interpretable data presentation
- reduced clutter
- improved mobile support

### Architecture
- move away from Dash as the long-term framework
- move away from direct MongoDB-heavy page rendering
- move toward:
  - FastAPI backend
  - PostgreSQL / PostGIS data layer
  - HTML / CSS / JavaScript frontend
- separate:
  - rendering
  - data access
  - monitoring
  - API logic

---

## 10. Key current-state issues

### Interface and UX
- Current dashboard is functional but visually flatter than desired.
- Search and filters need stronger hierarchy.
- Station summary should appear before dense scientific controls.
- Live-data and station-data layouts need calmer, more readable structure.
- The dashboard needs a clearer “What am I looking at?” purpose section.
- The dashboard needs onboarding or help for first-time users.
- The dashboard needs clearer pathways for:
  - quick public use
  - advanced scientific analysis

### Architecture
- Current architecture mixes page rendering and direct data access too tightly.
- Direct MongoDB access should be refactored behind backend services.
- Background monitoring should not remain embedded in the main dashboard runtime long term.
- Dash is no longer the best long-term framework for the dashboard’s future requirements.

---

## 11. Recommended direction after this baseline

The replacement direction should be:

- **FastAPI backend**
- **PostgreSQL / PostGIS data layer**
- **clean HTML / CSS / JavaScript frontend**

This would support:
- better maintainability
- better performance
- clearer separation of concerns
- easier UX redesign
- more scalable long-term evolution

---

## 12. Baseline conclusion

The current ACCESS monitoring dashboard is already functional and valuable, especially for internal exploration and scientific inspection. However, it has now reached the point where its limitations are architectural as well as visual.

This baseline confirms that the next phase should be a combined:

- UX redesign
- frontend redesign
- backend re-architecture
- migration away from Dash + direct MongoDB coupling

The redesign should preserve the scientific strength of the current dashboard while making it substantially clearer, calmer, more professional, and easier to maintain.

---

## 13. Audit evidence checklist

Included in this folder:

- [x] Homepage / map screenshot
- [x] Station popup screenshot
- [x] Station metadata modal screenshot
- [x] Station data page screenshot
- [x] Current dashboard code snapshot

Files:
- `01_homepage.jpg`
- `02_station_info.jpg`
- `03_station_metadata.jpg`
- `04_station_data.png`
- `dashboard-V1.txt`

---