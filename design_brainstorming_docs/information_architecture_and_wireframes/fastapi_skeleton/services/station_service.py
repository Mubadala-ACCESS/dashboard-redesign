"""Station service boundary notes for Tuesday.

This file is intentionally lightweight.
It exists to prove the separation of concerns direction.

Current state:
- Dash pages and helpers read Mongo-backed payloads directly.

Target state:
- routers call service functions
- service functions call database/repository layer
- frontend consumes API responses rather than direct page-bound queries
"""

def build_station_summary_payload(station_id: str) -> dict:
    return {
        "station_id": station_id,
        "name": "Example Station",
        "status": "Active",
    }


def build_latest_cards_payload(station_id: str) -> dict:
    return {
        "station_id": station_id,
        "cards": [],
    }


def build_metadata_payload(station_id: str) -> dict:
    return {
        "station_id": station_id,
        "variables": [],
    }
