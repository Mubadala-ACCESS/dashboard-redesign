#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from psycopg import connect
from psycopg.rows import dict_row
from pymongo import MongoClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'all_stations_db')
MONGO_STATIONS_INFO_COLLECTION = os.getenv('MONGO_STATIONS_INFO_COLLECTION', 'stations_info')
MONGO_BUOY_COLLECTION = os.getenv('MONGO_BUOY_COLLECTION', 'buoy_01')
MONGO_METEO_COLLECTION = os.getenv('MONGO_METEO_COLLECTION', 'f1_meteostation')
MONGO_FIDAS_COLLECTION = os.getenv('MONGO_FIDAS_COLLECTION', 'fidas_nyuad')
POSTGRES_DSN = os.getenv('POSTGRES_DSN', 'postgresql://postgres:postgres@localhost:5432/ecomonitor')

SPECIAL_STATIONS = {
    5463: (MONGO_METEO_COLLECTION, 'Timestamp'),
    100: (MONGO_FIDAS_COLLECTION, 'datetime'),
    8394: (MONGO_BUOY_COLLECTION, 'datetime'),
}

IOT_META_KEYS = {'sensor', 'index', 'type', 'sensor_T', 'sensor_RH', 'diagnostics'}


def utcify(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return None


def sanitize_device_type(value: Any) -> str:
    allowed = {
        'IoTBox', 'Meteorological', 'Buoy', 'Fidas_Palas',
        'SBNTransect', 'JWCruise', 'underwater_probe', 'coral_reef'
    }
    return value if value in allowed else 'Unknown'


def sanitize_status(value: Any) -> str:
    allowed = {'Active', 'Maintenance', 'Decommissioned', 'Unknown'}
    return value if value in allowed else 'Unknown'


def sanitize_privacy(value: Any) -> str:
    return 'public' if bool(value) else 'private'


def upsert_station(pg, station_doc: Dict[str, Any]) -> int:
    latitude = station_doc.get('lat')
    longitude = station_doc.get('long')
    station_id = str(station_doc.get('id') or station_doc.get('_id'))
    sensors = station_doc.get('sensors', {}) if isinstance(station_doc.get('sensors'), dict) else {}
    with pg.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO ecomonitor.stations (
              station_id, station_num, name, device_type, status, privacy,
              latitude, longitude, geom, location_text, model, sensors_json,
              last_calibration, metadata_json
            )
            VALUES (
              %(station_id)s, %(station_num)s, %(name)s, %(device_type)s::ecomonitor.device_type,
              %(status)s::ecomonitor.station_status, %(privacy)s::ecomonitor.station_privacy,
              %(latitude)s, %(longitude)s,
              CASE WHEN %(longitude)s IS NOT NULL AND %(latitude)s IS NOT NULL
                   THEN ST_SetSRID(ST_MakePoint(%(longitude)s, %(latitude)s), 4326)
                   ELSE NULL END,
              %(location_text)s, %(model)s, %(sensors_json)s::jsonb,
              %(last_calibration)s, %(metadata_json)s::jsonb
            )
            ON CONFLICT (station_id) DO UPDATE SET
              station_num = EXCLUDED.station_num,
              name = EXCLUDED.name,
              device_type = EXCLUDED.device_type,
              status = EXCLUDED.status,
              privacy = EXCLUDED.privacy,
              latitude = EXCLUDED.latitude,
              longitude = EXCLUDED.longitude,
              geom = EXCLUDED.geom,
              location_text = EXCLUDED.location_text,
              model = EXCLUDED.model,
              sensors_json = EXCLUDED.sensors_json,
              last_calibration = EXCLUDED.last_calibration,
              metadata_json = EXCLUDED.metadata_json,
              updated_at = now()
            RETURNING station_pk
            """,
            {
                'station_id': station_id,
                'station_num': station_doc.get('station_num'),
                'name': station_doc.get('name') or f"Station {station_doc.get('station_num', 'Unknown')}",
                'device_type': sanitize_device_type(station_doc.get('type')),
                'status': sanitize_status(station_doc.get('status')),
                'privacy': sanitize_privacy(station_doc.get('public', True)),
                'latitude': float(latitude) if latitude is not None else None,
                'longitude': float(longitude) if longitude is not None else None,
                'location_text': station_doc.get('location') or 'Abu Dhabi',
                'model': station_doc.get('model'),
                'sensors_json': json.dumps(sensors),
                'last_calibration': utcify(station_doc.get('last_calibration')),
                'metadata_json': json.dumps({
                    'source': 'mongo_stations_info',
                    'raw_id': str(station_doc.get('_id')),
                }),
            },
        )
        return int(cur.fetchone()['station_pk'])


def ensure_metric(pg, metric_key: str, display_label: str, canonical_label: str, unit: str, category: str, description: str = '') -> None:
    with pg.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ecomonitor.metric_catalog (metric_key, display_label, canonical_label, unit, category, description)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (metric_key) DO UPDATE SET
              display_label = EXCLUDED.display_label,
              canonical_label = EXCLUDED.canonical_label,
              unit = EXCLUDED.unit,
              category = EXCLUDED.category,
              description = EXCLUDED.description
            """,
            (metric_key, display_label, canonical_label, unit, category, description),
        )


def ensure_station_metric_definition(pg, station_pk: int, metric_key: str, source_path: str, aggregation_mode: str = 'mean') -> None:
    with pg.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ecomonitor.station_metric_definitions (station_pk, metric_key, source_path, aggregation_mode)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (station_pk, metric_key) DO UPDATE SET
              source_path = EXCLUDED.source_path,
              aggregation_mode = EXCLUDED.aggregation_mode
            """,
            (station_pk, metric_key, source_path, aggregation_mode),
        )


def insert_observations(pg, rows: Iterable[Tuple]) -> None:
    with pg.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO ecomonitor.observations (
              station_pk, observed_at, metric_key, sensor_key, value_numeric, value_text,
              depth_m, latitude, longitude, quality_flag, source_record_id, payload_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )


def insert_buoy_profiles(pg, rows: Iterable[Tuple]) -> None:
    with pg.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO ecomonitor.buoy_profiles (
              station_pk, observed_at, metric_key, profile_index, depth_m, value_numeric, payload_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )


def migrate_iot_station(pg, mongo_db, station_pk: int, station_num: int, sensors: Dict[str, int]) -> int:
    collection = mongo_db[f'station{station_num}']
    count = 0
    for doc in collection.find({}, {'_id': 1, 'datetime': 1, 'gps': 1, 'date_time_position': 1, 'dateTimePosition': 1}):
        observed_at = utcify(doc.get('datetime'))
        if observed_at is None:
            continue
        lat = lon = None
        gps = doc.get('gps')
        if isinstance(gps, dict) and isinstance(gps.get('position'), list) and len(gps['position']) >= 2:
            lon, lat = gps['position'][0], gps['position'][1]
        else:
            fallback = doc.get('date_time_position') or doc.get('dateTimePosition')
            if isinstance(fallback, dict):
                lon = fallback.get('longitude')
                lat = fallback.get('latitude')
        rows = []
        expanded_doc = collection.find_one({'_id': doc['_id']})
        if not expanded_doc:
            continue
        for sensor_key, sensor_doc in expanded_doc.items():
            if '+' not in sensor_key or not isinstance(sensor_doc, dict):
                continue
            for field, value in sensor_doc.items():
                if field in IOT_META_KEYS or not isinstance(value, (int, float)):
                    continue
                metric_key = field.lower().replace('.', '_').replace(',', '_')
                label = field.replace('_', ' ').title()
                if field == 'temperature':
                    ensure_metric(pg, metric_key, 'Temperature (°C)', 'Temperature', '°C', 'weather')
                elif field == 'humidity':
                    ensure_metric(pg, metric_key, 'Relative Humidity (%)', 'Humidity', '%', 'weather')
                elif field == 'pressure':
                    ensure_metric(pg, metric_key, 'Atmospheric Pressure (hPa)', 'Atmospheric Pressure', 'hPa', 'weather')
                elif field == 'co2':
                    ensure_metric(pg, metric_key, 'CO2 (ppm)', 'CO2', 'ppm', 'air_quality')
                elif 'pm1mass' in field.lower():
                    ensure_metric(pg, metric_key, 'PM1 (µg/m³)', 'PM1', 'µg/m³', 'air_quality')
                elif 'pm2.5mass' in field.lower() or 'pm2,5mass' in field.lower():
                    ensure_metric(pg, metric_key, 'PM2.5 (µg/m³)', 'PM2.5', 'µg/m³', 'air_quality')
                elif 'pm10mass' in field.lower():
                    ensure_metric(pg, metric_key, 'PM10 (µg/m³)', 'PM10', 'µg/m³', 'air_quality')
                else:
                    ensure_metric(pg, metric_key, label, label, '', 'environment')
                ensure_station_metric_definition(pg, station_pk, metric_key, f'{sensor_key}.{field}')
                rows.append((station_pk, observed_at, metric_key, sensor_key, float(value), None, None, lat, lon, None, str(doc['_id']), json.dumps({})))
        if rows:
            insert_observations(pg, rows)
            count += len(rows)
    return count


def migrate_meteo_station(pg, mongo_db, station_pk: int, collection_name: str) -> int:
    label_map = {
        'I3_VPOWER': ('voltage_power', 'Voltage Power (V)', 'Voltage Power', 'V', 'weather'),
        'I4_VOUT': ('voltage_output', 'Voltage Output (V)', 'Voltage Output', 'V', 'weather'),
        'S1_RAD': ('radiation', 'Radiation (W/m²)', 'Radiation', 'W/m²', 'weather'),
        'S2_DP[C]': ('dew_point', 'Dew Point (°C)', 'Dew Point', '°C', 'weather'),
        'S2_PA': ('pressure', 'Atmospheric Pressure (hPa)', 'Atmospheric Pressure', 'hPa', 'weather'),
        'S2_PREC[MM]': ('precipitation', 'Precipitation (mm)', 'Precipitation', 'mm', 'weather'),
        'S2_RH[%]': ('humidity', 'Relative Humidity (%)', 'Humidity', '%', 'weather'),
        'S2_TA[C]': ('temperature', 'Temperature (°C)', 'Temperature', '°C', 'weather'),
        'S2_WD': ('wind_direction', 'Wind Direction (°)', 'Wind Direction', '°', 'weather'),
        'S2_WS[M/S]': ('wind_speed', 'Wind Speed (m/s)', 'Wind Speed', 'm/s', 'weather'),
    }
    count = 0
    for doc in mongo_db[collection_name].find({}, {'_id': 1, 'Timestamp': 1}):
        observed_at = utcify(doc.get('Timestamp'))
        if observed_at is None:
            continue
        expanded = mongo_db[collection_name].find_one({'_id': doc['_id']})
        rows = []
        for field, meta in label_map.items():
            value = expanded.get(field)
            if not isinstance(value, (int, float)):
                continue
            metric_key, display, canonical, unit, category = meta
            ensure_metric(pg, metric_key, display, canonical, unit, category)
            ensure_station_metric_definition(pg, station_pk, metric_key, field)
            rows.append((station_pk, observed_at, metric_key, None, float(value), None, None, None, None, None, str(doc['_id']), json.dumps({})))
        if rows:
            insert_observations(pg, rows)
            count += len(rows)
    return count


def migrate_fidas_station(pg, mongo_db, station_pk: int, collection_name: str) -> int:
    count = 0
    fields = {
        'PM1': ('pm1', 'PM1 (µg/m³)', 'PM1', 'µg/m³', 'air_quality'),
        'PM4': ('pm4', 'PM4 (µg/m³)', 'PM4', 'µg/m³', 'air_quality'),
        'PM10': ('pm10', 'PM10 (µg/m³)', 'PM10', 'µg/m³', 'air_quality'),
        'PMtot': ('pmtotal', 'Total PM (µg/m³)', 'Total PM', 'µg/m³', 'air_quality'),
        'Cn': ('particle_count', 'Count Number (particles/cm³)', 'Count Number', 'particles/cm³', 'air_quality'),
        'rH': ('humidity', 'Relative Humidity (%)', 'Humidity', '%', 'weather'),
        'T': ('temperature', 'Temperature (°C)', 'Temperature', '°C', 'weather'),
        'p': ('pressure', 'Pressure (hPa)', 'Atmospheric Pressure', 'hPa', 'weather'),
        'Wspeed': ('wind_speed', 'Wind Speed (km/h)', 'Wind Speed', 'km/h', 'weather'),
        'Wdir': ('wind_direction', 'Wind Direction (°)', 'Wind Direction', '°', 'weather'),
        'feelLike': ('feels_like', 'Feels Like (°C)', 'Feels Like', '°C', 'weather'),
        'wbgt': ('wbgt', 'WBGT (°C)', 'WBGT', '°C', 'weather'),
    }
    for doc in mongo_db[collection_name].find({}):
        observed_at = utcify(doc.get('datetime'))
        if observed_at is None:
            continue
        rows = []
        pm2 = doc.get('PM2')
        if isinstance(pm2, dict) and isinstance(pm2.get('5'), (int, float)):
            ensure_metric(pg, 'pm2_5', 'PM2.5 (µg/m³)', 'PM2.5', 'µg/m³', 'air_quality')
            ensure_station_metric_definition(pg, station_pk, 'pm2_5', "PM2['5']")
            rows.append((station_pk, observed_at, 'pm2_5', None, float(pm2['5']), None, None, None, None, None, str(doc['_id']), json.dumps({})))
        for field, meta in fields.items():
            value = doc.get(field)
            if not isinstance(value, (int, float)):
                continue
            metric_key, display, canonical, unit, category = meta
            ensure_metric(pg, metric_key, display, canonical, unit, category)
            ensure_station_metric_definition(pg, station_pk, metric_key, field)
            rows.append((station_pk, observed_at, metric_key, None, float(value), None, None, None, None, None, str(doc['_id']), json.dumps({})))
        if rows:
            insert_observations(pg, rows)
            count += len(rows)
    return count


def migrate_buoy_station(pg, mongo_db, station_pk: int, collection_name: str) -> int:
    scalar_fields = {
        'wind_speed': ('wind_speed', 'Wind Speed (m/s)', 'Wind Speed', 'm/s', 'weather'),
        'wind_direction': ('wind_direction', 'Wind Direction (°)', 'Wind Direction', '°', 'weather'),
        'air_temp': ('air_temperature', 'Air Temperature (°C)', 'Temperature', '°C', 'weather'),
        'barometric_pressure': ('barometric_pressure', 'Barometric Pressure (hPa)', 'Atmospheric Pressure', 'hPa', 'weather'),
        'albedo': ('albedo', 'Albedo', 'Albedo', '', 'marine'),
    }
    profile_fields = {
        'CTD_tmp': ('ctd_temperature', 'CTD Temperature (°C)', 'Temperature', '°C', 'marine'),
        'conductivity': ('conductivity', 'Conductivity (mmho/cm)', 'Conductivity', 'mmho/cm', 'marine'),
        'O2': ('oxygen', 'Oxygen (µM/L)', 'Oxygen', 'µM/L', 'marine'),
        'chlorophyll': ('chlorophyll', 'Chlorophyll (µg/L)', 'Chlorophyll', 'µg/L', 'marine'),
        'salinity_practical': ('salinity', 'Salinity (PSU)', 'Salinity', 'PSU', 'marine'),
        'density': ('density', 'Density (kg/m³)', 'Density', 'kg/m³', 'marine'),
    }
    count = 0
    for doc in mongo_db[collection_name].find({}):
        observed_at = utcify(doc.get('datetime'))
        if observed_at is None:
            continue
        obs_rows = []
        profile_rows = []
        for field, meta in scalar_fields.items():
            value = doc.get(field)
            if not isinstance(value, (int, float)):
                continue
            metric_key, display, canonical, unit, category = meta
            ensure_metric(pg, metric_key, display, canonical, unit, category)
            ensure_station_metric_definition(pg, station_pk, metric_key, field)
            obs_rows.append((station_pk, observed_at, metric_key, None, float(value), None, None, None, None, None, str(doc['_id']), json.dumps({})))
        depths = doc.get('depth') if isinstance(doc.get('depth'), list) else []
        for field, meta in profile_fields.items():
            values = doc.get(field)
            if not isinstance(values, list) or not values:
                continue
            metric_key, display, canonical, unit, category = meta
            ensure_metric(pg, metric_key, display, canonical, unit, category)
            ensure_station_metric_definition(pg, station_pk, metric_key, field)
            numeric_values = [float(v) for v in values if isinstance(v, (int, float))]
            if numeric_values:
                obs_rows.append((station_pk, observed_at, metric_key, None, sum(numeric_values) / len(numeric_values), None, None, None, None, None, str(doc['_id']), json.dumps({'aggregated_from_profile': True})))
            for idx, value in enumerate(values):
                if not isinstance(value, (int, float)):
                    continue
                depth = depths[idx] if idx < len(depths) and isinstance(depths[idx], (int, float)) else None
                profile_rows.append((station_pk, observed_at, metric_key, idx, depth, float(value), json.dumps({})))
        if obs_rows:
            insert_observations(pg, obs_rows)
            count += len(obs_rows)
        if profile_rows:
            insert_buoy_profiles(pg, profile_rows)
    return count


def refresh_materialized_views(pg) -> None:
    with pg.cursor() as cur:
        cur.execute('REFRESH MATERIALIZED VIEW ecomonitor.station_latest_metric_values;')
        cur.execute('REFRESH MATERIALIZED VIEW ecomonitor.station_latest_health;')
        cur.execute('REFRESH MATERIALIZED VIEW ecomonitor.station_map_summary;')


def main() -> None:
    mongo = MongoClient(MONGO_URI, tz_aware=True)
    mongo_db = mongo[MONGO_DB_NAME]
    pg = connect(POSTGRES_DSN, autocommit=False)

    try:
        stations = list(mongo_db[MONGO_STATIONS_INFO_COLLECTION].find({}))
        migrated = defaultdict(int)
        for station_doc in stations:
            station_pk = upsert_station(pg, station_doc)
            station_num = station_doc.get('station_num')
            if station_num is None:
                continue
            if station_num in SPECIAL_STATIONS:
                collection_name, _time_field = SPECIAL_STATIONS[station_num]
                if station_num == 5463:
                    migrated['observations'] += migrate_meteo_station(pg, mongo_db, station_pk, collection_name)
                elif station_num == 100:
                    migrated['observations'] += migrate_fidas_station(pg, mongo_db, station_pk, collection_name)
                elif station_num == 8394:
                    migrated['observations'] += migrate_buoy_station(pg, mongo_db, station_pk, collection_name)
            elif sanitize_device_type(station_doc.get('type')) == 'IoTBox':
                migrated['observations'] += migrate_iot_station(
                    pg,
                    mongo_db,
                    station_pk,
                    int(station_num),
                    station_doc.get('sensors', {}) if isinstance(station_doc.get('sensors'), dict) else {},
                )
        refresh_materialized_views(pg)
        pg.commit()
        print('Migration complete.')
        for key, value in migrated.items():
            print(f'  {key}: {value}')
    except Exception:
        pg.rollback()
        raise
    finally:
        pg.close()
        mongo.close()


if __name__ == '__main__':
    main()
