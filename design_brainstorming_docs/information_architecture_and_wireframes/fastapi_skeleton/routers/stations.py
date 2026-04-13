from fastapi import APIRouter
from schemas import StationMetadata

router = APIRouter()

@router.get("/{station_id}")
def get_station_summary(station_id: str) -> dict:
    return {
        "station_id": station_id,
        "name": "Example Station",
        "device_type": "IoTBox",
        "status": "Active",
        "summary": "Quick summary payload for station detail and live-data pages.",
    }

@router.get("/{station_id}/status")
def get_station_status(station_id: str) -> dict:
    return {
        "station_id": station_id,
        "status": "Active",
        "freshness": "fresh",
        "note": "Boundary for maintenance/stale-data logic."
    }

@router.get("/{station_id}/metadata", response_model=StationMetadata)
def get_station_metadata(station_id: str) -> StationMetadata:
    return StationMetadata(
        station_id=station_id,
        station_name="Example Station",
        earliest_data="2024-12-05T09:41:12",
        latest_data="2026-04-01T12:46:55",
        instruments=["IoT Box"],
        variables=[],
    )
