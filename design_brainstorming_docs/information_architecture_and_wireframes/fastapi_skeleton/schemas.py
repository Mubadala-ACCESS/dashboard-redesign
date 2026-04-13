from typing import List, Optional
from pydantic import BaseModel


class StationSummary(BaseModel):
    station_id: str
    station_num: Optional[int] = None
    name: str
    device_type: str
    status: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    privacy: Optional[str] = None
    last_reading_at: Optional[str] = None


class MapStation(BaseModel):
    station_id: str
    name: str
    device_type: str
    status: str
    latitude: float
    longitude: float
    privacy: Optional[str] = None


class LatestReadingCard(BaseModel):
    parameter: str
    value: Optional[float] = None
    unit: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    interpretation: Optional[str] = None
    threshold_band: Optional[str] = None


class MetadataRow(BaseModel):
    column: str
    descriptor: str
    units: Optional[str] = None
    definition: Optional[str] = None


class StationMetadata(BaseModel):
    station_id: str
    station_name: str
    earliest_data: Optional[str] = None
    latest_data: Optional[str] = None
    instruments: List[str] = []
    variables: List[MetadataRow] = []
