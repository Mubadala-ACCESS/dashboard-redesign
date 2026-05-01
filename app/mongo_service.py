from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient

from .air_quality import calculate_aqi
from .cache import TTLCache
from .metadata_service import MetadataService
from .settings import Settings


class MongoDashboardRepository:
    LOOKBACK = 50
    EXCLUDE_DISCOVERY_KEYS = {'index', 'sensor', 'type', 'sensor_T', 'sensor_RH', 'diagnostics'}
    PM_COUNT_RE = re.compile(r'^pm(?:\d+(?:[.,]\d+)?)?count$', re.IGNORECASE)
    DEFAULT_METRIC_PRIORITY = [
        'PM2.5', 'PM10', 'PM1', 'CO2', 'Temperature', 'Humidity', 'Atmospheric Pressure'
    ]
    DEVICE_LABELS = {
        'IoTBox': 'IoT Box',
        'Meteorological': 'Meteorological Station',
        'Buoy': 'Buoy',
        'Fidas_Palas': 'Fidas Palas 200S',
        'SBNTransect': 'SBN Transect',
        'JWCruise': 'Jaywun Cruise',
        'underwater_probe': 'Underwater Probes',
        'coral_reef': 'Coral Reef Monitoring',
    }
    PERIOD_MAP = {
        '24H': timedelta(hours=24),
        '7D': timedelta(days=7),
        '30D': timedelta(days=30),
        '1Y': timedelta(days=365),
        'ALL': None,
    }
    AGG_MAP = {
        'raw': None,
        '15m': '15min',
        '1h': '1h',
        '6h': '6h',
        '1d': '1d',
    }
    SPECIAL_REALTIME_TYPES = {'IoTBox', 'Meteorological', 'Buoy', 'Fidas_Palas'}

    def __init__(self, settings: Settings, metadata_service: MetadataService):
        self.settings = settings
        self.metadata_service = metadata_service
        self.client = MongoClient(
            settings.mongo_uri,
            maxPoolSize=settings.mongo_max_pool_size,
            minPoolSize=settings.mongo_min_pool_size,
            serverSelectionTimeoutMS=settings.mongo_server_selection_timeout_ms,
            connectTimeoutMS=settings.mongo_connect_timeout_ms,
            socketTimeoutMS=settings.mongo_socket_timeout_ms,
            tz_aware=True,
        )
        self.db = self.client[settings.mongo_db_name]
        self.local_tz = ZoneInfo(settings.default_timezone)
        self.cache = TTLCache(settings.cache_ttl_seconds)
        self.thresholds = self.metadata_service.thresholds()
        self.special_availability = self.metadata_service.special_availability()
        self.station_projection = {
            '_id': 1,
            'id': 1,
            'station_num': 1,
            'name': 1,
            'lat': 1,
            'long': 1,
            'type': 1,
            'status': 1,
            'public': 1,
            'sensors': 1,
            'location': 1,
            'model': 1,
            'last_calibration': 1,
        }

    # ------------------------------------------------------------------
    # Basic helpers
    # ------------------------------------------------------------------
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _localize(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(self.local_tz)

    def _dt_string(self, value: datetime | None) -> str | None:
        localized = self._localize(value)
        return localized.isoformat() if localized else None

    def _human_dt(self, value: datetime | None) -> str:
        localized = self._localize(value)
        if not localized:
            return 'N/A'
        return localized.strftime('%d %b %Y, %I:%M %p GST')

    def _station_cache_key(self, station_id: str) -> str:
        return f'station:{station_id}'

    def _normalize_station(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        station_id = str(doc.get('id') or doc.get('_id'))
        device_type = doc.get('type', 'Unknown')
        return {
            'station_id': station_id,
            'mongo_id': str(doc.get('_id')) if doc.get('_id') else None,
            'station_num': doc.get('station_num'),
            'name': doc.get('name') or f'Station {doc.get("station_num", "Unknown")}',
            'lat': float(doc.get('lat')) if doc.get('lat') is not None else None,
            'lon': float(doc.get('long')) if doc.get('long') is not None else None,
            'device_type': device_type,
            'device_label': self.DEVICE_LABELS.get(device_type, device_type),
            'status': doc.get('status', 'Unknown'),
            'privacy': 'Public' if doc.get('public', True) else 'Private',
            'is_public': bool(doc.get('public', True)),
            'sensors': doc.get('sensors', {}),
            'location_text': doc.get('location') or 'Abu Dhabi',
            'model': doc.get('model'),
            'last_calibration': doc.get('last_calibration'),
        }

    def _station_query(self, station_id: str) -> Dict[str, Any]:
        queries: List[Dict[str, Any]] = [{'id': station_id}]
        if station_id.isdigit():
            queries.append({'station_num': int(station_id)})
        if ObjectId.is_valid(station_id):
            queries.append({'_id': ObjectId(station_id)})
        return {'$or': queries}

    def resolve_station(self, station_id: str) -> Dict[str, Any]:
        cached = self.cache.get(self._station_cache_key(station_id))
        if cached:
            return cached
        doc = self.db[self.settings.mongo_stations_info_collection].find_one(self._station_query(station_id), self.station_projection)
        if not doc:
            raise KeyError(f'Station not found: {station_id}')
        station = self._normalize_station(doc)
        self.cache.set(self._station_cache_key(station_id), station, ttl_seconds=300)
        self.cache.set(self._station_cache_key(station['station_id']), station, ttl_seconds=300)
        return station

    def get_filters(self) -> Dict[str, Any]:
        cache_key = 'filters'
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        docs = list(self.db[self.settings.mongo_stations_info_collection].find({}, {'type': 1, 'status': 1, 'public': 1}))
        filters = {
            'privacy': [
                {'value': 'all', 'label': 'All'},
                {'value': 'public', 'label': 'Public'},
                {'value': 'private', 'label': 'Private'},
            ],
            'device_types': [{'value': 'all', 'label': 'All'}],
            'statuses': [{'value': 'all', 'label': 'All'}],
        }
        types = sorted({doc.get('type') for doc in docs if doc.get('type')})
        statuses = sorted({doc.get('status') for doc in docs if doc.get('status')})
        filters['device_types'].extend([{'value': item, 'label': self.DEVICE_LABELS.get(item, item)} for item in types])
        filters['statuses'].extend([{'value': item, 'label': item} for item in statuses])
        self.cache.set(cache_key, filters, ttl_seconds=300)
        return filters

    def list_stations(
        self,
        privacy: str = 'all',
        device_type: str = 'all',
        status: str = 'all',
        search: str = '',
    ) -> Dict[str, Any]:
        query: Dict[str, Any] = {'lat': {'$ne': None}, 'long': {'$ne': None}}
        if privacy == 'public':
            query['public'] = True
        elif privacy == 'private':
            query['public'] = False
        if device_type != 'all':
            query['type'] = device_type
        if status != 'all':
            query['status'] = status
        if search:
            regex = {'$regex': re.escape(search), '$options': 'i'}
            search_clauses: List[Dict[str, Any]] = [{'name': regex}, {'id': regex}]
            if search.isdigit():
                search_clauses.append({'station_num': int(search)})
            query['$or'] = search_clauses

        docs = list(self.db[self.settings.mongo_stations_info_collection].find(query, self.station_projection))
        stations = [self._normalize_station(doc) for doc in docs]
        stations.sort(key=lambda item: (item['status'] != 'Active', item['device_label'], item['name']))

        type_counter = Counter(item['device_label'] for item in stations)
        status_counter = Counter(item['status'] for item in stations)
        public_counter = Counter(item['privacy'] for item in stations)
        summary = {
            'total_stations': len(stations),
            'active_stations': status_counter.get('Active', 0),
            'maintenance_stations': status_counter.get('Maintenance', 0),
            'public_stations': public_counter.get('Public', 0),
            'device_breakdown': dict(type_counter),
            'status_breakdown': dict(status_counter),
        }
        network = self.get_network_summary()
        summary['regional_aqi'] = network.get('regional_aqi')
        summary['elevated_station_count'] = network.get('elevated_station_count', 0)
        return {'summary': summary, 'stations': stations, 'filters': self.get_filters()}

    def _collection_for_station(self, station: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        station_num = station.get('station_num')
        device_type = station.get('device_type')
        if device_type == 'Meteorological' or station_num == 5463:
            return self.settings.mongo_meteo_collection, 'Timestamp'
        if device_type == 'Buoy' or station_num == 8394:
            return self.settings.mongo_buoy_collection, 'datetime'
        if device_type == 'Fidas_Palas' or station_num == 100:
            return self.settings.mongo_fidas_collection, 'datetime'
        if station_num is not None:
            return f'station{station_num}', 'datetime'
        return None, None

    def _station_has_collection(self, station: Dict[str, Any]) -> bool:
        collection_name, _ = self._collection_for_station(station)
        return bool(collection_name and collection_name in self.db.list_collection_names())

    def get_time_extent(self, station: Dict[str, Any]) -> Dict[str, Optional[str]]:
        cache_key = f'time_extent:{station["station_id"]}'
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        device_type = station['device_type']
        if device_type in self.special_availability:
            special = self.special_availability[device_type]
            payload = {'earliest': special.get('earliest'), 'latest': special.get('latest')}
            self.cache.set(cache_key, payload, ttl_seconds=3600)
            return payload

        collection_name, time_field = self._collection_for_station(station)
        if not collection_name or collection_name not in self.db.list_collection_names():
            payload = {'earliest': None, 'latest': None}
            self.cache.set(cache_key, payload, ttl_seconds=60)
            return payload

        collection = self.db[collection_name]
        first = collection.find_one({time_field: {'$exists': True}}, sort=[(time_field, ASCENDING)], projection={time_field: 1})
        last = collection.find_one({time_field: {'$exists': True}}, sort=[(time_field, DESCENDING)], projection={time_field: 1})
        payload = {
            'earliest': self._human_dt(first.get(time_field) if first else None) if first else None,
            'latest': self._human_dt(last.get(time_field) if last else None) if last else None,
            'latest_iso': self._dt_string(last.get(time_field) if last else None) if last else None,
        }
        self.cache.set(cache_key, payload, ttl_seconds=300)
        return payload

    def _latest_document(self, station: Dict[str, Any], projection: Optional[Dict[str, int]] = None) -> Optional[Dict[str, Any]]:
        projection_key = ','.join(sorted(projection.keys())) if projection else 'default'
        cache_key = f'latest:{station["station_id"]}:{projection_key}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        collection_name, time_field = self._collection_for_station(station)
        if not collection_name or collection_name not in self.db.list_collection_names():
            self.cache.set(cache_key, None, ttl_seconds=30)
            return None
        document = self.db[collection_name].find_one({}, projection=projection, sort=[(time_field, DESCENDING)])
        self.cache.set(cache_key, document, ttl_seconds=30)
        return document

    def _freshness_payload(self, station: Dict[str, Any], latest_dt: datetime | None) -> Dict[str, Any]:
        now = self._now()
        localized = self._localize(latest_dt)
        freshness_minutes = None
        if latest_dt:
            base_dt = latest_dt if latest_dt.tzinfo else latest_dt.replace(tzinfo=timezone.utc)
            freshness_minutes = max(0, int((now - base_dt).total_seconds() // 60))
        stale = freshness_minutes is None or freshness_minutes > self.settings.stale_threshold_hours * 60
        return {
            'last_update': self._human_dt(latest_dt),
            'last_update_iso': self._dt_string(latest_dt),
            'freshness_minutes': freshness_minutes,
            'is_stale': stale,
            'freshness_label': 'Stale' if stale else 'Fresh',
            'status': station.get('status', 'Unknown'),
        }

    def get_station_summary(self, station_id: str) -> Dict[str, Any]:
        station = self.resolve_station(station_id)
        extent = self.get_time_extent(station)
        collection_name, time_field = self._collection_for_station(station)
        latest = self._latest_document(station, projection={time_field: 1} if time_field else None)
        freshness = self._freshness_payload(station, latest.get(time_field) if latest and time_field in latest else None)
        capabilities = {
            'quick_view': True,
            'advanced_analysis': station['device_type'] in self.SPECIAL_REALTIME_TYPES,
            'metadata': True,
            'raw_export': station['device_type'] in self.SPECIAL_REALTIME_TYPES,
        }
        return {
            **station,
            'coordinates': {'lat': station['lat'], 'lon': station['lon']},
            'data_extent': extent,
            'freshness': freshness,
            'capabilities': capabilities,
            'collection_name': collection_name,
        }

    def get_metadata_payload(self, station_id: str) -> Dict[str, Any]:
        station = self.get_station_summary(station_id)
        measurement_frequency = (
            'Continuous real-time monitoring.'
            if station['device_type'] in self.SPECIAL_REALTIME_TYPES
            else 'Campaign or interval sampling based on the monitoring program.'
        )
        return {
            'station': station,
            'summary': {
                'station_name': station['name'],
                'earliest_data': station['data_extent'].get('earliest') or 'N/A',
                'latest_data': station['data_extent'].get('latest') or 'N/A',
                'measurement_frequency': measurement_frequency,
            },
            'tabs': self.metadata_service.metadata_tabs_for_device(station['device_type']),
        }

    # ------------------------------------------------------------------
    # Parameter discovery and normalization
    # ------------------------------------------------------------------
    def _iot_include_param(self, param: str) -> bool:
        if param in self.EXCLUDE_DISCOVERY_KEYS:
            return False
        low = param.lower()
        if low in ('pm1count', 'pm10count', 'pm2,5count', 'pm2.5count'):
            return False
        if self.PM_COUNT_RE.match(low):
            return False
        return True

    def _iot_label(self, param: str) -> str:
        low = param.lower()
        if low == 'humidity':
            return 'Humidity (%)'
        if low == 'temperature':
            return 'Temperature (°C)'
        if low == 'pressure':
            return 'Atmospheric Pressure (hPa)'
        if low == 'co2':
            return 'CO2 (ppm)'
        if 'pm1mass' in low:
            return 'PM1 Mass (µg/m³)'
        if 'pm2,5mass' in low or 'pm2.5mass' in low:
            return 'PM2.5 Mass (µg/m³)'
        if 'pm10mass' in low:
            return 'PM10 Mass (µg/m³)'
        return param.replace('_', ' ').title()

    def _iot_discover(self, station_num: int) -> Tuple[Dict[str, str], Dict[str, List[Tuple[str, str]]]]:
        station_info = self.db[self.settings.mongo_stations_info_collection].find_one({'station_num': station_num}, {'sensors': 1})
        if not station_info or 'sensors' not in station_info:
            return {}, {}
        collection = self.db[f'station{station_num}']
        params_set: set[str] = set()
        full_params: Dict[str, List[Tuple[str, str]]] = {}
        for sensor_type, count in station_info['sensors'].items():
            for i in range(count):
                sensor_key = f'{sensor_type}+{i}'
                cursor = collection.find({}, {'_id': 0, sensor_key: 1}).sort('datetime', DESCENDING).limit(self.LOOKBACK)
                for doc in cursor:
                    sensor_data = doc.get(sensor_key)
                    if not isinstance(sensor_data, dict):
                        continue
                    found_for_this_sensor = False
                    for param in sensor_data.keys():
                        if not self._iot_include_param(param):
                            continue
                        params_set.add(param)
                        full_key = f'{sensor_key}.{param}'
                        sensor_label = f'{self._iot_label(param)} - {sensor_type.replace("_", " ").title()} {i + 1}'
                        full_params.setdefault(param, []).append((full_key, sensor_label))
                        found_for_this_sensor = True
                    if found_for_this_sensor:
                        break
        label_map = {param: self._iot_label(param) for param in params_set}
        ordered: Dict[str, str] = {}
        desired_labels = [
            'Temperature (°C)',
            'Humidity (%)',
            'Atmospheric Pressure (hPa)',
            'CO2 (ppm)',
            'PM1 Mass (µg/m³)',
            'PM2.5 Mass (µg/m³)',
            'PM10 Mass (µg/m³)',
        ]
        for desired in desired_labels:
            for key, label in label_map.items():
                if label == desired and key not in ordered:
                    ordered[key] = label
        for key, label in sorted(label_map.items(), key=lambda item: item[1]):
            if key not in ordered:
                ordered[key] = label
        return ordered, full_params

    def _metric_key_to_label(self, station: Dict[str, Any], key: str) -> str:
        if station['device_type'] == 'IoTBox':
            return self._iot_label(key)
        if station['device_type'] == 'Meteorological':
            meteo_map = {
                'I3_VPOWER': 'Voltage Power (V)',
                'I4_VOUT': 'Voltage Output (V)',
                'S1_RAD': 'Radiation (W/m²)',
                'S2_DP[C]': 'Dew Point (°C)',
                'S2_PA': 'Atmospheric Pressure (hPa)',
                'S2_PREC[MM]': 'Precipitation (mm)',
                'S2_RH[%]': 'Relative Humidity (%)',
                'S2_TA[C]': 'Temperature (°C)',
                'S2_WD': 'Wind Direction (°)',
                'S2_WS[M/S]': 'Wind Speed (m/s)',
            }
            return meteo_map.get(key, key)
        if station['device_type'] == 'Fidas_Palas':
            fidas_map = {
                'PM1': 'PM1 (µg/m³)',
                'PM2.5': 'PM2.5 (µg/m³)',
                'PM4': 'PM4 (µg/m³)',
                'PM10': 'PM10 (µg/m³)',
                'PMtot': 'Total PM (µg/m³)',
                'Cn': 'Count Number (particles/cm³)',
                'rH': 'Relative Humidity (%)',
                'dewT': 'Dew Point (°C)',
                'T': 'Temperature (°C)',
                'p': 'Pressure (hPa)',
                'Wspeed': 'Wind Speed (km/h)',
                'Wdir': 'Wind Direction (°)',
                'feelLike': 'Feels Like (°C)',
                'wbgt': 'WBGT (°C)',
            }
            return fidas_map.get(key, key)
        if station['device_type'] == 'Buoy':
            buoy_map = {
                'wind_speed': 'Wind Speed (m/s)',
                'wind_direction': 'Wind Direction (°)',
                'air_temp': 'Air Temperature (°C)',
                'barometric_pressure': 'Barometric Pressure (hPa)',
                'albedo': 'Albedo',
                'CTD_tmp': 'CTD Temperature (°C)',
                'conductivity': 'Conductivity (mmho/cm)',
                'O2': 'Oxygen (µM/L)',
                'chlorophyll': 'Chlorophyll (µg/L)',
                'salinity_practical': 'Salinity (PSU)',
                'density': 'Density (kg/m³)',
            }
            return buoy_map.get(key, key)
        return key

    def _label_to_canonical(self, label: str) -> str:
        low = label.lower()
        if 'pm2.5' in low:
            return 'PM2.5'
        if 'pm10' in low:
            return 'PM10'
        if 'pm1' in low:
            return 'PM1'
        if 'co2' in low:
            return 'CO2'
        if 'temperature' in low:
            return 'Temperature'
        if 'humidity' in low:
            return 'Humidity'
        if 'pressure' in low:
            return 'Atmospheric Pressure'
        if 'wind speed' in low:
            return 'Wind Speed'
        return label

    def _default_metrics(self, available_map: Dict[str, str]) -> List[str]:
        preferred: List[str] = []
        for desired in self.DEFAULT_METRIC_PRIORITY:
            for key, label in available_map.items():
                if self._label_to_canonical(label) == desired and key not in preferred:
                    preferred.append(key)
        if len(preferred) >= 6:
            return preferred[:6]
        for key in available_map.keys():
            if key not in preferred:
                preferred.append(key)
        return preferred[:6]

    # ------------------------------------------------------------------
    # Timeseries extraction
    # ------------------------------------------------------------------
    def _base_query_for_period(self, period: str, time_field: str) -> Dict[str, Any]:
        delta = self.PERIOD_MAP.get(period.upper())
        if delta is None:
            return {}
        return {time_field: {'$gte': self._now() - delta}}

    def _aggregate_df(self, df: pd.DataFrame, freq: str | None) -> pd.DataFrame:
        if df.empty or not freq:
            return df
        df = df.copy()
        df = df.set_index('timestamp')
        numeric_cols = df.select_dtypes(include=['number']).columns
        grouped = df[numeric_cols].resample(freq).mean().ffill().reset_index()
        return grouped

    def _iot_dataframe(self, station: Dict[str, Any], metrics: List[str], split_sensors: bool, period: str, aggregation: str) -> Tuple[pd.DataFrame, Dict[str, str]]:
        labels, full_params = self._iot_discover(int(station['station_num']))
        if not metrics:
            metrics = self._default_metrics(labels)
        selected_full = {metric: full_params[metric] for metric in metrics if metric in full_params}
        plot_labels = dict(labels)
        for sensor_list in selected_full.values():
            for full_key, sensor_label in sensor_list:
                plot_labels[full_key] = sensor_label

        projection: Dict[str, int] = {'_id': 0, 'datetime': 1, 'gps': 1, 'date_time_position': 1, 'dateTimePosition': 1}
        for sensor_list in selected_full.values():
            for full_key, _ in sensor_list:
                projection[full_key.split('.', 1)[0]] = 1

        query = self._base_query_for_period(period, 'datetime')
        cursor = self.db[f'station{station["station_num"]}'].find(query, projection).sort('datetime', ASCENDING)
        data: List[Dict[str, Any]] = []
        for record in cursor:
            entry: Dict[str, Any] = {'timestamp': self._localize(record.get('datetime'))}
            for _base_param, sensor_list in selected_full.items():
                for full_key, _label in sensor_list:
                    sensor_key, sensor_param = full_key.split('.', 1)
                    sensor_doc = record.get(sensor_key, {})
                    if isinstance(sensor_doc, dict) and sensor_param in sensor_doc and isinstance(sensor_doc[sensor_param], (int, float)):
                        entry[full_key] = sensor_doc[sensor_param]
            gps = record.get('gps', {})
            if isinstance(gps, dict) and isinstance(gps.get('position'), list) and len(gps['position']) >= 2:
                entry['Longitude'], entry['Latitude'] = gps['position'][0], gps['position'][1]
            else:
                fallback = record.get('date_time_position') or record.get('dateTimePosition')
                if isinstance(fallback, dict):
                    lon = fallback.get('longitude')
                    lat = fallback.get('latitude')
                    if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
                        entry['Longitude'], entry['Latitude'] = lon, lat
            data.append(entry)

        df = pd.DataFrame(data)
        if df.empty:
            return df, plot_labels

        if not split_sensors:
            combined = pd.DataFrame({'timestamp': df['timestamp']})
            for metric in metrics:
                sensor_columns = [full_key for full_key, _sensor_label in selected_full.get(metric, []) if full_key in df.columns]
                if sensor_columns:
                    combined[metric] = df[sensor_columns].mean(axis=1)
            for column in ('Longitude', 'Latitude'):
                if column in df.columns:
                    combined[column] = df[column]
            df = combined

        df = self._aggregate_df(df, self.AGG_MAP.get(aggregation.lower()))
        return df, plot_labels

    def _meteo_dataframe(self, station: Dict[str, Any], metrics: List[str], period: str, aggregation: str) -> Tuple[pd.DataFrame, Dict[str, str]]:
        label_map = {
            'I3_VPOWER': 'Voltage Power (V)',
            'I4_VOUT': 'Voltage Output (V)',
            'S1_RAD': 'Radiation (W/m²)',
            'S2_DP[C]': 'Dew Point (°C)',
            'S2_PA': 'Atmospheric Pressure (hPa)',
            'S2_PREC[MM]': 'Precipitation (mm)',
            'S2_RH[%]': 'Relative Humidity (%)',
            'S2_TA[C]': 'Temperature (°C)',
            'S2_WD': 'Wind Direction (°)',
            'S2_WS[M/S]': 'Wind Speed (m/s)',
        }
        if not metrics:
            metrics = ['S2_TA[C]', 'S2_RH[%]', 'S2_PA', 'S2_WS[M/S]', 'S1_RAD']
        query = self._base_query_for_period(period, 'Timestamp')
        projection = {'_id': 0, 'Timestamp': 1}
        projection.update({metric: 1 for metric in metrics})
        docs = list(self.db[self.settings.mongo_meteo_collection].find(query, projection).sort('Timestamp', ASCENDING))
        df = pd.DataFrame(docs)
        if df.empty:
            return df, label_map
        df = df.rename(columns={'Timestamp': 'timestamp'})
        df['timestamp'] = pd.to_datetime(df['timestamp']).apply(self._localize)
        df = self._aggregate_df(df, self.AGG_MAP.get(aggregation.lower()))
        return df, label_map

    def _fidas_dataframe(self, station: Dict[str, Any], metrics: List[str], period: str, aggregation: str) -> Tuple[pd.DataFrame, Dict[str, str]]:
        label_map = {
            'PM1': 'PM1 (µg/m³)',
            'PM2.5': 'PM2.5 (µg/m³)',
            'PM4': 'PM4 (µg/m³)',
            'PM10': 'PM10 (µg/m³)',
            'PMtot': 'Total PM (µg/m³)',
            'Cn': 'Count Number (particles/cm³)',
            'rH': 'Relative Humidity (%)',
            'T': 'Temperature (°C)',
            'p': 'Pressure (hPa)',
            'Wspeed': 'Wind Speed (km/h)',
            'Wdir': 'Wind Direction (°)',
            'feelLike': 'Feels Like (°C)',
            'wbgt': 'WBGT (°C)',
        }
        if not metrics:
            metrics = ['PM2.5', 'PM10', 'PM1', 'T', 'rH', 'p']
        query = self._base_query_for_period(period, 'datetime')
        projection = {'_id': 0, 'datetime': 1, 'PM2': 1}
        for metric in metrics:
            if metric != 'PM2.5':
                projection[metric] = 1
        docs = list(self.db[self.settings.mongo_fidas_collection].find(query, projection).sort('datetime', ASCENDING))
        rows: List[Dict[str, Any]] = []
        for doc in docs:
            row: Dict[str, Any] = {'timestamp': self._localize(doc.get('datetime'))}
            for metric in metrics:
                if metric == 'PM2.5':
                    pm2 = doc.get('PM2')
                    if isinstance(pm2, dict):
                        value = pm2.get('5')
                        if isinstance(value, (int, float)):
                            row['PM2.5'] = value
                else:
                    value = doc.get(metric)
                    if isinstance(value, (int, float)):
                        row[metric] = value
            rows.append(row)
        df = pd.DataFrame(rows)
        if df.empty:
            return df, label_map
        df = self._aggregate_df(df, self.AGG_MAP.get(aggregation.lower()))
        return df, label_map

    def _buoy_dataframe(self, station: Dict[str, Any], metrics: List[str], period: str, aggregation: str) -> Tuple[pd.DataFrame, Dict[str, str], List[Dict[str, Any]]]:
        scalar_params = ['wind_speed', 'wind_direction', 'air_temp', 'barometric_pressure', 'albedo']
        profile_params = ['CTD_tmp', 'conductivity', 'O2', 'chlorophyll', 'salinity_practical', 'density']
        label_map = {metric: self._metric_key_to_label(station, metric) for metric in scalar_params + profile_params}
        if not metrics:
            metrics = ['wind_speed', 'air_temp', 'barometric_pressure', 'CTD_tmp', 'O2']
        query = self._base_query_for_period(period, 'datetime')
        projection = {'_id': 0, 'datetime': 1, 'depth': 1}
        for metric in metrics:
            projection[metric] = 1
        docs = list(self.db[self.settings.mongo_buoy_collection].find(query, projection).sort('datetime', ASCENDING))
        rows: List[Dict[str, Any]] = []
        profiles: List[Dict[str, Any]] = []
        for doc in docs:
            row: Dict[str, Any] = {'timestamp': self._localize(doc.get('datetime'))}
            for metric in metrics:
                value = doc.get(metric)
                if metric in scalar_params and isinstance(value, (int, float)):
                    row[metric] = value
                elif metric in profile_params and isinstance(value, list) and value:
                    numeric = [v for v in value if isinstance(v, (int, float))]
                    if numeric:
                        row[metric] = float(np.mean(numeric))
                        profiles.append({
                            'metric': metric,
                            'timestamp': self._dt_string(doc.get('datetime')),
                            'depth': doc.get('depth', []),
                            'values': numeric,
                            'label': label_map.get(metric, metric),
                        })
            rows.append(row)
        df = pd.DataFrame(rows)
        if df.empty:
            return df, label_map, profiles[-5:]
        df = self._aggregate_df(df, self.AGG_MAP.get(aggregation.lower()))
        return df, label_map, profiles[-5:]

    def get_timeseries(
        self,
        station_id: str,
        period: str = '24H',
        aggregation: str = '15m',
        metrics: Optional[List[str]] = None,
        split_sensors: bool = False,
    ) -> Dict[str, Any]:
        station = self.get_station_summary(station_id)
        metrics = metrics or []
        extra: Dict[str, Any] = {}
        if station['device_type'] == 'IoTBox':
            df, label_map = self._iot_dataframe(station, metrics, split_sensors, period, aggregation)
        elif station['device_type'] == 'Meteorological':
            df, label_map = self._meteo_dataframe(station, metrics, period, aggregation)
        elif station['device_type'] == 'Fidas_Palas':
            df, label_map = self._fidas_dataframe(station, metrics, period, aggregation)
        elif station['device_type'] == 'Buoy':
            df, label_map, profiles = self._buoy_dataframe(station, metrics, period, aggregation)
            extra['profiles'] = profiles
        else:
            return {
                'station': station,
                'period': period,
                'aggregation': aggregation,
                'metrics': [],
                'charts': [],
                'table': [],
                'events': [],
                'message': 'This station type is currently metadata-first in the Mongo adapter. Quick View and metadata remain available.',
            }

        if df.empty:
            return {
                'station': station,
                'period': period,
                'aggregation': aggregation,
                'metrics': [],
                'charts': [],
                'table': [],
                'events': [],
                'message': 'No data was available for the selected time range.',
                **extra,
            }

        metric_keys = [column for column in df.columns if column != 'timestamp' and not column.startswith('Lat') and not column.startswith('Long')]
        charts = []
        events = self._detect_events(df, station, metric_keys)
        for metric in metric_keys:
            label = label_map.get(metric, self._metric_key_to_label(station, metric))
            canonical = self._label_to_canonical(label)
            values = df[metric].dropna()
            threshold_key = canonical if canonical in self.thresholds else label.split(' (')[0]
            thresholds = self.thresholds.get(threshold_key)
            charts.append(
                {
                    'metric': metric,
                    'label': label,
                    'canonical_label': canonical,
                    'thresholds': thresholds,
                    'series': [
                        {
                            'x': self._dt_string(row['timestamp']),
                            'y': None if pd.isna(row[metric]) else float(row[metric]),
                        }
                        for _, row in df[['timestamp', metric]].iterrows()
                    ],
                    'summary': {
                        'min': None if values.empty else round(float(values.min()), 2),
                        'max': None if values.empty else round(float(values.max()), 2),
                        'mean': None if values.empty else round(float(values.mean()), 2),
                        'latest': None if values.empty else round(float(values.iloc[-1]), 2),
                    },
                }
            )
        table_rows = []
        sample_df = df.tail(100).copy()
        sample_df = sample_df.sort_values('timestamp', ascending=False)
        for _, row in sample_df.iterrows():
            table_row = {'timestamp': self._human_dt(row['timestamp'])}
            for metric in metric_keys[:6]:
                value = row.get(metric)
                table_row[metric] = None if pd.isna(value) else round(float(value), 2)
            table_rows.append(table_row)

        return {
            'station': station,
            'period': period,
            'aggregation': aggregation,
            'metrics': [{'key': key, 'label': label_map.get(key, key)} for key in metric_keys],
            'charts': charts,
            'table': table_rows,
            'events': events,
            **extra,
        }

    def _detect_events(self, df: pd.DataFrame, station: Dict[str, Any], metric_keys: List[str]) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        if 'timestamp' not in df.columns:
            return events
        for metric in metric_keys:
            label = self._metric_key_to_label(station, metric)
            series = df[['timestamp', metric]].dropna()
            if series.empty:
                continue
            high = float(series[metric].quantile(0.95))
            if 'PM' in label and high > 0:
                point = series.loc[series[metric].idxmax()]
                events.append({
                    'type': 'Dust storm event',
                    'metric': metric,
                    'label': label,
                    'timestamp': self._dt_string(point['timestamp']),
                    'value': round(float(point[metric]), 2),
                })
            if 'Temperature' in label and high >= 35:
                point = series.loc[series[metric].idxmax()]
                events.append({
                    'type': 'Heatwave peak',
                    'metric': metric,
                    'label': label,
                    'timestamp': self._dt_string(point['timestamp']),
                    'value': round(float(point[metric]), 2),
                })
            if 'Precipitation' in label and series[metric].max() > 0:
                point = series.loc[series[metric].idxmax()]
                events.append({
                    'type': 'Rain event',
                    'metric': metric,
                    'label': label,
                    'timestamp': self._dt_string(point['timestamp']),
                    'value': round(float(point[metric]), 2),
                })
        deduped = []
        seen = set()
        for event in events:
            key = (event['type'], event['timestamp'])
            if key not in seen:
                deduped.append(event)
                seen.add(key)
        return deduped[:12]

    # ------------------------------------------------------------------
    # Latest cards and alerts
    # ------------------------------------------------------------------
    def _quick_aggregation_for_period(self, period: str) -> str:
        return {
            '24H': '15m',
            '7D': '1h',
            '30D': '6h',
            '1Y': '1d',
            'ALL': '1d',
        }.get(period.upper(), '15m')

    def get_latest_cards(self, station_id: str, period: str = '24H', include_trends: bool = False) -> Dict[str, Any]:
        station = self.get_station_summary(station_id)
        aggregation = self._quick_aggregation_for_period(period)
        timeseries = self.get_timeseries(station_id, period=period, aggregation=aggregation, metrics=[], split_sensors=False)
        charts = timeseries.get('charts', [])
        cards = []
        trends = []
        primary_aqi = None
        for chart in charts[:6]:
            label = chart['label']
            latest = chart['summary'].get('latest')
            card = {
                'metric': chart['metric'],
                'label': label,
                'canonical_label': chart['canonical_label'],
                'latest': latest,
                'mean': chart['summary'].get('mean'),
                'max': chart['summary'].get('max'),
                'min': chart['summary'].get('min'),
                'unit': self._extract_unit(label),
            }
            if chart['canonical_label'] in {'PM2.5', 'PM10'} and latest is not None and primary_aqi is None:
                primary_aqi = calculate_aqi(latest, chart['canonical_label'])
                card['aqi'] = primary_aqi
            cards.append(card)
            if include_trends:
                trends.append({
                    'metric': chart['metric'],
                    'label': label,
                    'canonical_label': chart['canonical_label'],
                    'unit': self._extract_unit(label),
                    'summary': chart['summary'],
                    'series': chart['series'],
                })
        return {
            'station': station,
            'period': period,
            'trend_aggregation': aggregation,
            'cards': cards,
            'trends': trends,
            'primary_aqi': primary_aqi,
            'events': timeseries.get('events', []),
            'latest_table': timeseries.get('table', [])[:8],
        }

    def _extract_unit(self, label: str) -> str:
        if '(' in label and ')' in label:
            return label.split('(')[-1].split(')')[0]
        return ''

    def get_network_summary(self) -> Dict[str, Any]:
        cache_key = 'network_summary'
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        docs = list(self.db[self.settings.mongo_stations_info_collection].find({'lat': {'$ne': None}, 'long': {'$ne': None}}, self.station_projection))
        stations = [self._normalize_station(doc) for doc in docs]
        aqi_values = []
        elevated = 0
        latest_alerts = []
        for station in stations:
            if station['device_type'] not in self.SPECIAL_REALTIME_TYPES:
                continue
            try:
                cards = self.get_latest_cards(station['station_id'])
                aqi = cards.get('primary_aqi')
                if aqi:
                    aqi_values.append(aqi['aqi'])
                    if aqi['aqi'] >= 101:
                        elevated += 1
                        latest_alerts.append(
                            {
                                'station_id': station['station_id'],
                                'station_name': station['name'],
                                'aqi': aqi,
                            }
                        )
            except Exception:
                continue
        regional_aqi = round(float(np.mean(aqi_values)), 0) if aqi_values else None
        payload = {
            'regional_aqi': regional_aqi,
            'elevated_station_count': elevated,
            'alerts': latest_alerts[:8],
        }
        self.cache.set(cache_key, payload, ttl_seconds=max(60, self.settings.cache_ttl_seconds))
        return payload

    def get_alerts(self) -> List[Dict[str, Any]]:
        network = self.get_network_summary()
        alerts = []
        for item in network.get('alerts', []):
            alerts.append(
                {
                    'station_id': item['station_id'],
                    'station_name': item['station_name'],
                    'headline': f"{item['aqi']['category']} particulate levels detected",
                    'message': item['aqi']['health_message'],
                    'aqi': item['aqi'],
                }
            )
        return alerts

    # ------------------------------------------------------------------
    # Raw export helpers
    # ------------------------------------------------------------------
    def export_frame(self, station_id: str, period: str, aggregation: str, metrics: Optional[List[str]], split_sensors: bool) -> pd.DataFrame:
        payload = self.get_timeseries(station_id, period=period, aggregation=aggregation, metrics=metrics, split_sensors=split_sensors)
        charts = payload.get('charts', [])
        if not charts:
            return pd.DataFrame()
        data = {'timestamp': [point['x'] for point in charts[0]['series']]}
        for chart in charts:
            data[chart['label']] = [point['y'] for point in chart['series']]
        return pd.DataFrame(data)

    def healthcheck(self) -> Dict[str, Any]:
        self.client.admin.command('ping')
        return {'status': 'ok', 'database': self.settings.mongo_db_name}
