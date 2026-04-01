from fastapi import APIRouter

router = APIRouter()

@router.get("/{station_id}/latest")
def get_latest_readings(station_id: str) -> dict:
    return {
        "station_id": station_id,
        "last_update": None,
        "cards": [],
        "note": "Boundary for latest value cards and quick interpretation."
    }

@router.get("/{station_id}/timeseries")
def get_timeseries(
    station_id: str,
    parameter: str | None = None,
    time_range: str | None = None,
    aggregation: str | None = None,
    sensor_mode: str | None = None,
) -> dict:
    return {
        "station_id": station_id,
        "parameter": parameter,
        "time_range": time_range,
        "aggregation": aggregation,
        "sensor_mode": sensor_mode,
        "series": [],
        "note": "Boundary for advanced analysis chart data."
    }
