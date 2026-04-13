from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter()

@router.get("/stations")
def get_map_stations(
    privacy: Optional[str] = Query(default=None),
    device_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
) -> dict:
    # Tuesday artifact purpose:
    # define the boundary that replaces direct map-page reads
    return {
        "filters": {
            "privacy": privacy,
            "device_type": device_type,
            "status": status,
            "search": search,
        },
        "stations": [],
        "note": "Replace StationMap + page-level filtering with backend service output."
    }

@router.get("/filters")
def get_map_filters() -> dict:
    return {
        "privacy": ["All", "Public", "Private"],
        "device_type": [
            "IoTBox",
            "Meteorological",
            "Buoy",
            "Fidas_Palas",
            "SBNTransect",
            "JWCruise",
            "underwater_probe",
            "coral_reef",
        ],
        "status": ["Active", "Maintenance", "Decommissioned"],
    }
