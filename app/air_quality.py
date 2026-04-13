from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Breakpoint:
    category: str
    low_aqi: int
    high_aqi: int
    low_bp: float
    high_bp: float
    health_message: str


PM25_BREAKPOINTS: List[Breakpoint] = [
    Breakpoint('Good', 0, 50, 0.0, 9.0, 'Air quality is considered good for most people.'),
    Breakpoint('Moderate', 51, 100, 9.1, 35.4, 'Acceptable for most people. Sensitive groups may wish to limit prolonged exertion.'),
    Breakpoint('Unhealthy for Sensitive Groups', 101, 150, 35.5, 55.4, 'Sensitive groups may experience symptoms. Reduce prolonged outdoor exertion.'),
    Breakpoint('Unhealthy', 151, 200, 55.5, 125.4, 'Everyone may begin to experience health effects. Limit exposure outdoors.'),
    Breakpoint('Very Unhealthy', 201, 300, 125.5, 225.4, 'Health alert conditions. Avoid extended outdoor activity.'),
    Breakpoint('Hazardous', 301, 500, 225.5, 325.4, 'Emergency conditions. Avoid outdoor exposure when possible.'),
]

PM10_BREAKPOINTS: List[Breakpoint] = [
    Breakpoint('Good', 0, 50, 0.0, 54.0, 'Air quality is considered good for most people.'),
    Breakpoint('Moderate', 51, 100, 55.0, 154.0, 'Acceptable for most people. Sensitive groups may wish to limit prolonged exertion.'),
    Breakpoint('Unhealthy for Sensitive Groups', 101, 150, 155.0, 254.0, 'Sensitive groups may experience symptoms. Reduce prolonged outdoor exertion.'),
    Breakpoint('Unhealthy', 151, 200, 255.0, 354.0, 'Everyone may begin to experience health effects. Limit exposure outdoors.'),
    Breakpoint('Very Unhealthy', 201, 300, 355.0, 424.0, 'Health alert conditions. Avoid extended outdoor activity.'),
    Breakpoint('Hazardous', 301, 500, 425.0, 604.0, 'Emergency conditions. Avoid outdoor exposure when possible.'),
]


def _interpolate(value: float, bp: Breakpoint) -> int:
    return round(((bp.high_aqi - bp.low_aqi) / (bp.high_bp - bp.low_bp)) * (value - bp.low_bp) + bp.low_aqi)


def calculate_aqi(value: Optional[float], pollutant: str) -> Optional[Dict[str, object]]:
    if value is None:
        return None

    pollutant_key = pollutant.lower().replace(' ', '')
    if pollutant_key in {'pm2.5', 'pm2_5', 'pm25'}:
        breakpoints = PM25_BREAKPOINTS
        label = 'PM2.5'
    elif pollutant_key in {'pm10'}:
        breakpoints = PM10_BREAKPOINTS
        label = 'PM10'
    else:
        return None

    for bp in breakpoints:
        if bp.low_bp <= float(value) <= bp.high_bp:
            return {
                'pollutant': label,
                'aqi': _interpolate(float(value), bp),
                'category': bp.category,
                'health_message': bp.health_message,
                'value': float(value),
            }

    if value > breakpoints[-1].high_bp:
        bp = breakpoints[-1]
        return {
            'pollutant': label,
            'aqi': 500,
            'category': bp.category,
            'health_message': bp.health_message,
            'value': float(value),
        }
    return None
