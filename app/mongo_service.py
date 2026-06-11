from __future__ import annotations

import csv
import io
import math
import re
import hashlib
import hmac
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient

from .cache import TTLCache
from .metadata_service import MetadataService
from .settings import Settings


class MongoDashboardRepository:
    LOOKBACK = 50
    MAX_CHART_POINTS = 2400
    MAX_TABLE_ROWS = 100
    HIDDEN_STATION_STATUSES = {'Decommissioned', 'Disabled'}
    DASHBOARD_STATUS_ORDER = ['Active', 'Maintenance']
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
    DEVICE_TYPE_ALIASES = {
        'iotbox': 'IoTBox',
        'iot_box': 'IoTBox',
        'iot_boxes': 'IoTBox',
        'meteorological': 'Meteorological',
        'meteorological_station': 'Meteorological',
        'meteostation': 'Meteorological',
        'meteo_station': 'Meteorological',
        'buoy': 'Buoy',
        'fidas_palas': 'Fidas_Palas',
        'fidas_palas_200s': 'Fidas_Palas',
        'sbntransect': 'SBNTransect',
        'sbn_transect': 'SBNTransect',
        'jwcruise': 'JWCruise',
        'jw_cruise': 'JWCruise',
        'jaywun_cruise': 'JWCruise',
        'underwater_probe': 'underwater_probe',
        'underwater_probes': 'underwater_probe',
        'coral_reef': 'coral_reef',
        'coral_reef_monitoring': 'coral_reef',
    }
    PERIOD_MAP = {
        '24H': timedelta(hours=24),
        '7D': timedelta(days=7),
        '30D': timedelta(days=30),
        '3M': timedelta(days=90),
        '6M': timedelta(days=180),
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
    TIME_SERIES_TYPES = SPECIAL_REALTIME_TYPES | {'underwater_probe'}
    DOCUMENT_METRIC_EXCLUDES = {'_id', 'datetime', 'Timestamp', 'ts', 'sizes', 'spectra', 'meta', 'profile_ID', 'CRC'}
    METEO_METRIC_PRIORITY = [
        'S2_TA[C]', 'S2_RH[%]', 'S2_PA', 'S2_WS[M/S]', 'S2_WD', 'S1_RAD', 'S2_PREC[MM]', 'S2_DP[C]',
    ]
    FIDAS_METRIC_PRIORITY = [
        'PM2.5', 'PM10', 'PM1', 'PM4', 'PMtot', 'Cn', 'T', 'rH', 'p', 'Wspeed', 'Wdir', 'dewT',
        'feelLike', 'hIdx_nws', 'wbgt', 'pT', 'prec', 'flowrate', 'velocity', 'IADS_T', 'LED_T',
    ]
    FIDAS_QUICK_METRIC_PRIORITY = [
        'PM2.5', 'PM10', 'PM1', 'PM4', 'PMtot', 'Cn', 'T', 'rH', 'p', 'dewT', 'feelLike',
        'hIdx_nws', 'wbgt', 'pT', 'Wspeed', 'Wdir',
    ]
    FIDAS_CALCULATED_KEYS = {'dewT', 'feelLike', 'hIdx_nws', 'wbgt', 'pT'}
    FIDAS_DO_NOT_CLEAN = {'errors', 'mode', 'ptype', 'cd', 'po', 'coincidence'}
    BUOY_SCALAR_PARAMS = ['wind_speed', 'wind_direction', 'air_temp', 'barometric_pressure', 'albedo']
    BUOY_PROFILE_PARAMS = ['CTD_tmp', 'conductivity', 'O2', 'chlorophyll', 'salinity_practical', 'density']
    BUOY_DEFAULT_SCALAR_PARAMS = ['wind_speed', 'air_temp', 'barometric_pressure']
    BUOY_DEFAULT_PROFILE_PARAMS = ['CTD_tmp', 'conductivity', 'O2']
    SPOTTER_BUOY_COLLECTION = 'buoy_samples'
    SPOTTER_BUOY_REGISTRY_COLLECTION = 'buoy_column_registry'
    SPOTTER_BUOY_METRIC_PRIORITY = [
        'significant_wave_height_m',
        'peak_period_s',
        'mean_period_s',
        'peak_direction_deg',
        'mean_direction_deg',
        'mean_directional_spread_deg',
        'wind_speed_m_s',
        'wind_direction_deg',
        'surface_temperature_c',
        'mean_barometric_pressure_hpa',
        'humidity_pct',
        'battery_voltage_v',
        'battery_power_w',
        'wind_speed',
        'wind_direction',
        'air_temp',
        'barometric_pressure',
        'albedo',
    ]
    SPOTTER_BUOY_ALIASES = {
        'significant_wave_height_m': [
            'significant_wave_height_m', 'Significant Wave Height (m)', 'significant_wave_height',
            'sig_wave_height', 'hs', 'hm0', 'Hsig',
        ],
        'peak_period_s': ['peak_period_s', 'Peak Period (s)', 'peak_period', 'tp'],
        'mean_period_s': ['mean_period_s', 'Mean Period (s)', 'mean_period', 'tm', 'tmean'],
        'peak_direction_deg': [
            'peak_direction_deg', 'Peak Wave Direction (deg)', 'peak_wave_direction_deg',
            'peak_wave_direction', 'dp', 'peak_dir',
        ],
        'mean_direction_deg': [
            'mean_direction_deg', 'Mean Wave Direction (deg)', 'mean_wave_direction_deg',
            'mean_wave_direction', 'mean_dir',
        ],
        'mean_directional_spread_deg': [
            'mean_directional_spread_deg', 'Mean Directional Spread (deg)', 'mean_directional_spread',
            'directional_spread_deg', 'spread_deg',
        ],
        'peak_directional_spread_deg': [
            'peak_directional_spread_deg', 'Peak Directional Spread (deg)', 'peak_directional_spread',
            'peak_spread_deg',
        ],
        'wind_speed_m_s': [
            'wind_speed_m_s', 'Wind Speed (m/s)', 'wind_speed_mps', 'wind_speed',
            'windspeed', 'wind_speed_ms',
        ],
        'wind_direction_deg': [
            'wind_direction_deg', 'Wind Direction (deg)', 'wind_direction', 'wind_dir',
            'wind_from_direction_deg',
        ],
        'surface_temperature_c': [
            'surface_temperature_c', 'Surface Temperature (C)', 'Surface Temperature (°C)',
            'sea_surface_temperature_c', 'water_temperature_c', 'sst_c',
        ],
        'mean_barometric_pressure_hpa': [
            'mean_barometric_pressure_hpa', 'Mean Barometric Pressure (hPa)', 'Pressure (hPa)',
            'Air Pressure (hPa)', 'air_pressure_hpa', 'pressure_hpa', 'barometric_pressure_hpa',
        ],
        'humidity_pct': [
            'humidity_pct', 'Humidity (%)', 'Relative Humidity (%)', 'relative_humidity_percent',
            'humidity_percent', 'humidity',
        ],
        'battery_voltage_v': ['battery_voltage_v', 'Battery Voltage (V)', 'battery_voltage', 'battery'],
        'battery_power_w': ['battery_power_w', 'Battery Power (W)', 'battery_power'],
        'latitude': ['latitude', 'lat'],
        'longitude': ['longitude', 'lon', 'lng', 'long'],
    }
    SPOTTER_BUOY_PARAMETER_EXCLUDES = {'latitude', 'longitude'}
    SPOTTER_BUOY_LABEL_OVERRIDES = {
        'significant_wave_height_m': 'Significant Wave Height (m)',
        'peak_period_s': 'Peak Period (s)',
        'mean_period_s': 'Mean Period (s)',
        'peak_direction_deg': 'Peak Wave Direction (deg)',
        'peak_directional_spread_deg': 'Peak Directional Spread (deg)',
        'mean_direction_deg': 'Mean Wave Direction (deg)',
        'mean_directional_spread_deg': 'Mean Directional Spread (deg)',
        'wind_speed_m_s': 'Wind Speed (m/s)',
        'wind_direction_deg': 'Wind Direction (deg)',
        'surface_temperature_c': 'Surface Temperature (C)',
        'mean_barometric_pressure_hpa': 'Mean Barometric Pressure (hPa)',
        'humidity_pct': 'Humidity (%)',
        'battery_voltage_v': 'Battery Voltage (V)',
        'battery_power_w': 'Battery Power (W)',
        'latitude': 'Latitude',
        'longitude': 'Longitude',
        'wind_speed': 'Wind Speed (m/s)',
        'wind_direction': 'Wind Direction (deg)',
        'air_temp': 'Air Temperature (C)',
        'barometric_pressure': 'Barometric Pressure (hPa)',
        'albedo': 'Albedo',
    }
    UNDERWATER_METRIC_PRIORITY = [
        'temp_c', 'c_field',
        'salinity_psu', 'sal_psu_field',
        'do_mg_l', 'do_mg_per_l_field',
        'do_pct_sat', 'do_pct_field',
        'ph',
        'turbidity_fnu', 'fnu_field',
        'chlorophyll_rfu', 'chl_ug_per_l_field',
        'phycoerythrin_rfu', 'tal_pe_ug_per_l_field',
        'fdom_rfu', 'fdom_qsu', 'fdom_qsu_field',
        'depth_m', 'dep_m_field',
        'sp_cond_ms_cm', 'spc_us_per_cm_field',
        'tds_mg_l', 'tds_mg_per_l_field',
        'battery_power_volt', 'batt_v_field',
    ]
    METEO_LABEL_OVERRIDES = {
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
    FIDAS_LABEL_OVERRIDES = {
        'Cn': 'Count Number (particles/cm³)',
        'IADS_T': 'IADS Temperature (°C)',
        'LED_T': 'LED Temperature (°C)',
        'PM1': 'PM1 (µg/m³)',
        'PM2.5': 'PM2.5 (µg/m³)',
        'PM2.5a': 'PM2.5 A (µg/m³)',
        'PM2.5c': 'PM2.5 C (µg/m³)',
        'PM4': 'PM4 (µg/m³)',
        'PM10': 'PM10 (µg/m³)',
        'PMtot': 'Total PM (µg/m³)',
        'T': 'Temperature (°C)',
        'Wdir': 'Wind Direction (°)',
        'Wspeed': 'Wind Speed',
        'dewT': 'Dew Point (°C)',
        'feelLike': 'Feels Like (°C)',
        'hIdx_nws': 'Heat Index NWS (°C)',
        'p': 'Pressure (hPa)',
        'prec': 'Precipitation',
        'rH': 'Relative Humidity (%)',
        'wbgt': 'Wet Bulb Globe Temperature (°C)',
    }

    UNDERWATER_LABEL_OVERRIDES = {
        'battery_power_volt': 'Battery Power (V)',
        'batt_v_field': 'Battery Power (V)',
        'c_field': 'Temperature (Â°C)',
        'chlorophyll_rfu': 'Chlorophyll (RFU)',
        'chl_ug_per_l_field': 'Chlorophyll (Âµg/L)',
        'depth_m': 'Depth (m)',
        'dep_m_field': 'Depth (m)',
        'dep_bar_a_field': 'Depth Pressure (bar)',
        'do_mg_l': 'Dissolved Oxygen (mg/L)',
        'do_mg_per_l_field': 'Dissolved Oxygen (mg/L)',
        'do_pct_sat': 'Dissolved Oxygen Saturation (%)',
        'do_pct_field': 'Dissolved Oxygen Saturation (%)',
        'fdom_qsu': 'fDOM (QSU)',
        'fdom_qsu_field': 'fDOM (QSU)',
        'fdom_rfu': 'fDOM (RFU)',
        'fnu_field': 'Turbidity (FNU)',
        'ph': 'pH',
        'phycoerythrin_rfu': 'Phycoerythrin (RFU)',
        'salinity_psu': 'Salinity (PSU)',
        'sal_psu_field': 'Salinity (PSU)',
        'sigma': 'Sigma',
        'sp_cond_ms_cm': 'Specific Conductivity (mS/cm)',
        'spc_us_per_cm_field': 'Specific Conductivity (ÂµS/cm)',
        'tal_pe_ug_per_l_field': 'Phycoerythrin (Âµg/L)',
        'tds_mg_l': 'Total Dissolved Solids (mg/L)',
        'tds_mg_per_l_field': 'Total Dissolved Solids (mg/L)',
        'temp_c': 'Temperature (Â°C)',
        'tss_mg_per_l_field': 'Total Suspended Solids (mg/L)',
        'turbidity_fnu': 'Turbidity (FNU)',
        'vpos_m_field': 'Vertical Position (m)',
    }
    UNDERWATER_LABEL_OVERRIDES.update({
        'c_field': 'Temperature (\u00b0C)',
        'chl_ug_per_l_field': 'Chlorophyll (\u00b5g/L)',
        'spc_us_per_cm_field': 'Specific Conductivity (\u00b5S/cm)',
        'tal_pe_ug_per_l_field': 'Phycoerythrin (\u00b5g/L)',
        'temp_c': 'Temperature (\u00b0C)',
    })
    UNDERWATER_ALIAS_GROUPS = {
        'temp_c': ['temp_c', 'c_field'],
        'salinity_psu': ['salinity_psu', 'sal_psu_field'],
        'do_mg_l': ['do_mg_l', 'do_mg_per_l_field'],
        'do_pct_sat': ['do_pct_sat', 'do_pct_field'],
        'turbidity_fnu': ['turbidity_fnu', 'fnu_field'],
        'fdom_qsu': ['fdom_qsu', 'fdom_qsu_field'],
        'depth_m': ['depth_m', 'dep_m_field'],
        'tds_mg_l': ['tds_mg_l', 'tds_mg_per_l_field'],
        'battery_power_volt': ['battery_power_volt', 'batt_v_field'],
    }
    SBN_COLLECTIONS = {
        'events': 'sbn_transect_events',
        'profiles': 'sbn_transect_profiles',
        'samples': 'sbn_transect_samples',
        'cells': 'sbn_transect_cells',
        'registry': 'sbn_transect_column_registry',
    }
    SBN_METRIC_LABELS = {
        'temp_c': 'Temperature',
        'temp2_c': 'Temperature 2',
        'salinity_psu': 'Salinity',
        'do_mg_l': 'Dissolved Oxygen',
        'do_pct_sat': 'Dissolved Oxygen Saturation',
        'chlorophyll_ug_l': 'Chlorophyll-A',
        'chlorophyll_rfu': 'Chlorophyll-A',
        'turbidity_fnu': 'Turbidity',
        'ph': 'pH',
        'par': 'PAR',
        'phycoerythrin_ug_l': 'Phycoerythrin',
        'phycoerythrin_rfu': 'Phycoerythrin',
        'cond_ms_cm': 'Conductivity',
        'sp_cond_ms_cm': 'Specific Conductivity',
        'pressure_dbar': 'Pressure',
        'pressure_psi_a': 'Pressure',
        'depth_m': 'Depth',
        'fdom_qsu': 'fDOM',
        'fdom_rfu': 'fDOM',
        'tds_mg_l': 'Total Dissolved Solids',
        'orp_mv': 'ORP',
    }
    SBN_METRIC_UNITS = {
        'temp_c': '°C',
        'temp2_c': '°C',
        'salinity_psu': 'PSU',
        'do_mg_l': 'mg/L',
        'do_pct_sat': '%',
        'chlorophyll_ug_l': 'µg/L',
        'chlorophyll_rfu': 'RFU',
        'turbidity_fnu': 'FNU',
        'ph': '',
        'par': 'rel.',
        'phycoerythrin_ug_l': 'µg/L',
        'phycoerythrin_rfu': 'RFU',
        'cond_ms_cm': 'mS/cm',
        'sp_cond_ms_cm': 'mS/cm',
        'pressure_dbar': 'dbar',
        'pressure_psi_a': 'psi',
        'depth_m': 'm',
        'fdom_qsu': 'QSU',
        'fdom_rfu': 'RFU',
        'tds_mg_l': 'mg/L',
        'orp_mv': 'mV',
    }
    SBN_METRIC_PRIORITY = [
        'temp_c',
        'salinity_psu',
        'do_mg_l',
        'do_pct_sat',
        'chlorophyll_ug_l',
        'chlorophyll_rfu',
        'turbidity_fnu',
        'ph',
        'par',
        'phycoerythrin_ug_l',
        'phycoerythrin_rfu',
        'cond_ms_cm',
        'sp_cond_ms_cm',
        'pressure_dbar',
    ]
    SBN_INSTRUMENT_ORDER = ['exo', 'idronaut', 'rbr']
    JW_COLLECTIONS = {
        'events': 'jw_cruise_events',
        'profiles': 'jw_cruise_profiles',
        'samples': 'jw_cruise_samples',
        'cells': 'jw_cruise_cells',
        'registry': 'jw_cruise_column_registry',
    }
    JW_METRIC_LABELS = {
        'temp_c': 'Temperature',
        'salinity_psu': 'Salinity',
        'do_mg_l': 'Dissolved Oxygen',
        'do_pct_sat': 'Dissolved Oxygen Saturation',
        'oxygen_ml_l': 'Dissolved Oxygen',
        'chlorophyll_ug_l': 'Chlorophyll-A',
        'turbidity_fnu': 'Turbidity',
        'ph': 'pH',
        'cond_ms_cm': 'Conductivity',
        'pressure_dbar': 'Pressure',
        'density': 'Density',
        'density_anomaly': 'Density Anomaly',
        'speed_of_sound': 'Speed of Sound',
        'par': 'PAR',
    }
    JW_METRIC_UNITS = {
        'temp_c': 'deg C',
        'salinity_psu': 'PSU',
        'do_mg_l': 'mg/L',
        'do_pct_sat': '%',
        'oxygen_ml_l': 'mL/L',
        'chlorophyll_ug_l': 'ug/L',
        'turbidity_fnu': 'FNU',
        'ph': '',
        'cond_ms_cm': 'mS/cm',
        'pressure_dbar': 'dbar',
        'density': 'kg/m3',
        'density_anomaly': 'kg/m3',
        'speed_of_sound': 'm/s',
        'par': 'rel.',
    }
    JW_METRIC_PRIORITY = [
        'temp_c',
        'salinity_psu',
        'do_mg_l',
        'do_pct_sat',
        'oxygen_ml_l',
        'chlorophyll_ug_l',
        'turbidity_fnu',
        'ph',
        'cond_ms_cm',
        'pressure_dbar',
        'density',
        'density_anomaly',
        'speed_of_sound',
        'par',
    ]
    JW_INSTRUMENT_ORDER = ['ead_ctd', 'rbr']

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
            'provider': 1,
            'hull_type': 1,
            'spotter_id': 1,
            'sampling': 1,
        }
        self._start_background_maintenance()

    def _start_background_maintenance(self) -> None:
        def run() -> None:
            self._ensure_station_indexes()
            self._ensure_sbn_indexes()
            self._ensure_jw_indexes()
            self._repair_station_type_aliases()

        threading.Thread(target=run, name='dashboard-mongo-maintenance', daemon=True).start()

    # ------------------------------------------------------------------
    # Basic helpers
    # ------------------------------------------------------------------
    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _collection_names(self) -> set[str]:
        cached = self.cache.get('collection_names')
        if cached is not None:
            return cached
        names = set(self.db.list_collection_names())
        self.cache.set('collection_names', names, ttl_seconds=300)
        return names

    def _collection_exists(self, collection_name: str | None) -> bool:
        return bool(collection_name and collection_name in self._collection_names())

    def _ensure_station_indexes(self) -> None:
        try:
            collection = self.db[self.settings.mongo_stations_info_collection]
            collection.create_index([('id', ASCENDING)], background=True)
            collection.create_index([('station_num', ASCENDING)], background=True)
            collection.create_index([('type', ASCENDING), ('status', ASCENDING), ('public', ASCENDING)], background=True)
            collection.create_index([('lat', ASCENDING), ('long', ASCENDING)], background=True)
            collection.create_index([('name', ASCENDING)], background=True)
        except Exception:
            return

    def _ensure_sbn_indexes(self) -> None:
        try:
            self.db[self.SBN_COLLECTIONS['events']].create_index([('campaign_month', ASCENDING)], background=True)
            self.db[self.SBN_COLLECTIONS['profiles']].create_index(
                [('campaign_month', ASCENDING), ('instrument', ASCENDING), ('waypoint_order', ASCENDING)],
                background=True,
            )
            self.db[self.SBN_COLLECTIONS['profiles']].create_index([('waypoint_id', ASCENDING), ('campaign_month', ASCENDING)], background=True)
            self.db[self.SBN_COLLECTIONS['cells']].create_index(
                [('campaign_month', ASCENDING), ('instrument', ASCENDING), ('depth_bin_m', ASCENDING), ('waypoint_order', ASCENDING)],
                background=True,
            )
            self.db[self.SBN_COLLECTIONS['cells']].create_index(
                [('waypoint_id', ASCENDING), ('instrument', ASCENDING), ('depth_bin_m', ASCENDING), ('campaign_month', ASCENDING)],
                background=True,
            )
        except Exception:
            return

    def _ensure_jw_indexes(self) -> None:
        try:
            self.db[self.JW_COLLECTIONS['events']].create_index([('campaign_month', ASCENDING)], background=True)
            self.db[self.JW_COLLECTIONS['profiles']].create_index(
                [('campaign_month', ASCENDING), ('instrument', ASCENDING), ('waypoint_order', ASCENDING)],
                background=True,
            )
            self.db[self.JW_COLLECTIONS['profiles']].create_index([('waypoint_id', ASCENDING), ('campaign_month', ASCENDING)], background=True)
            self.db[self.JW_COLLECTIONS['cells']].create_index(
                [('campaign_month', ASCENDING), ('instrument', ASCENDING), ('depth_bin_m', ASCENDING), ('waypoint_order', ASCENDING)],
                background=True,
            )
            self.db[self.JW_COLLECTIONS['cells']].create_index(
                [('waypoint_id', ASCENDING), ('instrument', ASCENDING), ('depth_bin_m', ASCENDING), ('campaign_month', ASCENDING)],
                background=True,
            )
            self.db[self.JW_COLLECTIONS['samples']].create_index(
                [('meta.campaign_month', ASCENDING), ('meta.instrument', ASCENDING), ('meta.waypoint_order', ASCENDING), ('depth_m', ASCENDING)],
                background=True,
            )
            self.db[self.JW_COLLECTIONS['samples']].create_index(
                [('meta.waypoint_id', ASCENDING), ('meta.instrument', ASCENDING), ('depth_m', ASCENDING), ('meta.campaign_month', ASCENDING)],
                background=True,
            )
        except Exception:
            return

    def _ensure_time_index(self, collection_name: str | None, time_field: str | None) -> None:
        if not collection_name or not time_field:
            return
        cache_key = f'index_ready:{collection_name}:{time_field}'
        if self.cache.get(cache_key) is not None:
            return
        if not self._collection_exists(collection_name):
            self.cache.set(cache_key, False, ttl_seconds=60)
            return
        self.cache.set(cache_key, 'pending', ttl_seconds=3600)
        threading.Thread(
            target=self._ensure_time_index_worker,
            args=(collection_name, time_field, cache_key),
            name=f'dashboard-index-{collection_name}-{time_field}',
            daemon=True,
        ).start()

    def _ensure_time_index_worker(self, collection_name: str, time_field: str, cache_key: str) -> None:
        try:
            self.db[collection_name].create_index([(time_field, ASCENDING)], background=True)
            if collection_name == self.settings.mongo_fidas_collection:
                self.db[collection_name].create_index([('errors', ASCENDING), (time_field, ASCENDING)], background=True)
                self.db[collection_name].create_index([('errors', ASCENDING), ('PM2.5', ASCENDING), (time_field, ASCENDING)], background=True, name='errors_pm25_datetime_1')
                self.db[collection_name].create_index([('errors', ASCENDING), ('PM10', ASCENDING), (time_field, ASCENDING)], background=True, name='errors_pm10_datetime_1')
                self.db[collection_name].create_index([('errors', ASCENDING), ('PM1', ASCENDING), (time_field, ASCENDING)], background=True, name='errors_pm1_datetime_1')
            if collection_name == self.settings.mongo_buoy_collection:
                self.db[collection_name].create_index([(time_field, ASCENDING), ('depth', ASCENDING)], background=True)
            if collection_name == self._spotter_samples_collection():
                self.db[collection_name].create_index([('meta.station_id', ASCENDING), (time_field, ASCENDING)], background=True)
                self.db[collection_name].create_index([('meta.spotter_id', ASCENDING), (time_field, ASCENDING)], background=True)
                self.db[collection_name].create_index([('meta.provider', ASCENDING), (time_field, ASCENDING)], background=True)
            self.cache.set(cache_key, True, ttl_seconds=3600)
        except Exception:
            self.cache.set(cache_key, False, ttl_seconds=60)

    def _coerce_datetime(self, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime()
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return datetime.fromisoformat(text.replace('Z', '+00:00'))
            except ValueError:
                parsed = pd.to_datetime(text, errors='coerce')
                if pd.isna(parsed):
                    return None
                return parsed.to_pydatetime()
        return None

    def _localize(self, value: datetime | None) -> datetime | None:
        value = self._coerce_datetime(value)
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

    def _local_tz_offset(self) -> timedelta:
        return self._now().astimezone(self.local_tz).utcoffset() or timedelta()

    def _station_actual_datetime(self, station: Dict[str, Any], value: datetime | None) -> datetime | None:
        value = self._coerce_datetime(value)
        if value is None:
            return None
        if station.get('device_type') in {'Fidas_Palas', 'Meteorological'}:
            base = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return base - self._local_tz_offset()
        return value

    def _localize_station_datetime(self, station: Dict[str, Any], value: datetime | None) -> datetime | None:
        return self._localize(self._station_actual_datetime(station, value))

    def _dt_string_for_station(self, station: Dict[str, Any], value: datetime | None) -> str | None:
        return self._dt_string(self._station_actual_datetime(station, value))

    def _human_dt_for_station(self, station: Dict[str, Any], value: datetime | None) -> str:
        return self._human_dt(self._station_actual_datetime(station, value))

    def _station_cache_key(self, station_id: str) -> str:
        return f'station:{station_id}'

    def _device_type_alias_key(self, value: Any) -> str:
        text = str(value or '').strip()
        text = re.sub(r'[\s-]+', '_', text)
        return text.casefold()

    def _canonical_device_type(self, value: Any) -> str:
        raw = str(value or '').strip()
        if not raw:
            return 'Unknown'
        if raw in self.DEVICE_LABELS:
            return raw
        return self.DEVICE_TYPE_ALIASES.get(self._device_type_alias_key(raw), raw)

    def _device_type_query_values(self, device_type: str) -> List[str]:
        canonical = self._canonical_device_type(device_type)
        values = {canonical, canonical.lower(), device_type}
        for alias_key, alias_target in self.DEVICE_TYPE_ALIASES.items():
            if alias_target == canonical:
                values.add(alias_key)
                values.add(alias_key.replace('_', ' '))
        return sorted({item for item in values if item})

    def _canonical_station_status(self, value: Any) -> str:
        raw = str(value or '').strip()
        if not raw:
            return 'Unknown'
        normalized = raw.casefold()
        if normalized in {'active', 'online', 'healthy'}:
            return 'Active'
        if normalized in {'maintenance', 'offline', 'issue', 'issues'}:
            return 'Maintenance'
        return raw

    def _status_query_values(self, status: str) -> List[str]:
        canonical = self._canonical_station_status(status)
        aliases = {canonical, canonical.lower(), status}
        if canonical == 'Active':
            aliases.update({'online', 'healthy'})
        elif canonical == 'Maintenance':
            aliases.update({'offline', 'issue', 'issues'})
        return sorted({item for item in aliases if item})

    def _repair_station_type_aliases(self) -> None:
        cache_key = 'station_type_alias_repair:v1'
        if self.cache.get(cache_key) is not None:
            return
        try:
            collection = self.db[self.settings.mongo_stations_info_collection]
            repaired = False
            for raw_type in collection.distinct('type'):
                canonical = self._canonical_device_type(raw_type)
                if canonical != raw_type:
                    result = collection.update_many({'type': raw_type}, {'$set': {'type': canonical}})
                    repaired = repaired or result.modified_count > 0
            if repaired:
                self.cache.delete('filters:v3')
                self.cache.delete('public_station_lookup:v3')
            self.cache.set(cache_key, True, ttl_seconds=3600)
        except Exception:
            self.cache.set(cache_key, False, ttl_seconds=300)

    def _slugify(self, value: str | None) -> str:
        text = (value or 'station').strip().lower()
        text = re.sub(r'[^a-z0-9]+', '-', text)
        return text.strip('-') or 'station'

    def _public_station_id(self, raw_station_id: str, name: str | None) -> str:
        key = self.settings.public_id_secret.encode('utf-8')
        digest = hmac.new(key, raw_station_id.encode('utf-8'), hashlib.sha256).hexdigest()[:8]
        return f'{self._slugify(name)}-{digest}'

    def _public_station_payload(self, station: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(station)
        public_id = payload.get('public_id') or self._public_station_id(str(payload.get('station_id', 'station')), payload.get('name'))
        payload['station_id'] = public_id
        payload['public_id'] = public_id
        for key in ('mongo_id', 'collection_name', 'sensors', 'station_num', 'spotter_id'):
            payload.pop(key, None)
        return payload

    def public_payload(self, value: Any) -> Any:
        passthrough_keys = {
            'cards', 'charts', 'events', 'metrics', 'available_metrics', 'table', 'latest_table',
            'trends', 'sensor_trends', 'series', 'profiles', 'frames', 'sizes', 'depth', 'values',
            'thresholds', 'sampling',
        }
        if isinstance(value, list):
            return [self.public_payload(item) for item in value]
        if not isinstance(value, dict):
            return value

        if 'station_id' in value and 'public_id' in value:
            value = self._public_station_payload(value)
        output: Dict[str, Any] = {}
        for key, item in value.items():
            if key in {'mongo_id', 'collection_name', 'sensors', 'station_num', 'spotter_id'}:
                continue
            if key == 'station' and isinstance(item, dict):
                output[key] = self._public_station_payload(item)
                continue
            if key in passthrough_keys:
                output[key] = item
                continue
            if key == 'station_id' and value.get('public_id'):
                output[key] = value['public_id']
                continue
            output[key] = self.public_payload(item)
        return output

    def _normalize_station(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        station_id = str(doc.get('id') or doc.get('_id'))
        device_type = self._canonical_device_type(doc.get('type', 'Unknown'))
        name = doc.get('name') or 'Monitoring station'
        return {
            'station_id': station_id,
            'public_id': self._public_station_id(station_id, name),
            'mongo_id': str(doc.get('_id')) if doc.get('_id') else None,
            'station_num': doc.get('station_num'),
            'name': name,
            'lat': float(doc.get('lat')) if doc.get('lat') is not None else None,
            'lon': float(doc.get('long')) if doc.get('long') is not None else None,
            'device_type': device_type,
            'device_label': self.DEVICE_LABELS.get(device_type, device_type),
            'status': self._canonical_station_status(doc.get('status')),
            'privacy': 'Public' if doc.get('public', True) else 'Private',
            'is_public': bool(doc.get('public', True)),
            'sensors': doc.get('sensors', {}),
            'location_text': doc.get('location') or 'Abu Dhabi',
            'model': doc.get('model'),
            'last_calibration': doc.get('last_calibration'),
            'provider': doc.get('provider'),
            'hull_type': doc.get('hull_type'),
            'spotter_id': doc.get('spotter_id'),
            'sampling': doc.get('sampling'),
        }

    def _is_spotter_buoy(self, station: Dict[str, Any]) -> bool:
        if station.get('device_type') != 'Buoy':
            return False
        provider = str(station.get('provider') or '').strip().lower()
        hull_type = str(station.get('hull_type') or '').strip().lower()
        station_id = str(station.get('station_id') or '').strip().upper()
        configured_station_id = str(getattr(self.settings, 'sofar_station_id', '') or '').strip().upper()
        name = str(station.get('name') or '').strip().lower()
        return (
            provider == 'sofar'
            or hull_type == 'spotter'
            or (configured_station_id and station_id == configured_station_id)
            or station_id.startswith('BUOY_NYUAD')
            or 'spotter' in name
        )

    def _spotter_samples_collection(self) -> str:
        return str(getattr(self.settings, 'sofar_samples_collection', '') or self.SPOTTER_BUOY_COLLECTION)

    def _spotter_registry_collection(self) -> str:
        return str(getattr(self.settings, 'sofar_column_registry_collection', '') or self.SPOTTER_BUOY_REGISTRY_COLLECTION)

    def _spotter_station_ids(self, station: Dict[str, Any]) -> List[str]:
        candidates = [
            station.get('station_id'),
            getattr(self.settings, 'sofar_station_id', None),
        ]
        station_ids: List[str] = []
        for value in candidates:
            station_id = str(value or '').strip().upper()
            if not station_id or '-' in station_id:
                continue
            if station_id not in station_ids:
                station_ids.append(station_id)
        return station_ids

    def _spotter_spotter_ids(self, station: Dict[str, Any]) -> List[str]:
        candidates = [
            station.get('spotter_id'),
            getattr(self.settings, 'sofar_spotter_id', None),
        ]
        spotter_ids: List[str] = []
        for value in candidates:
            spotter_id = str(value or '').strip().upper()
            if not spotter_id:
                continue
            if spotter_id not in spotter_ids:
                spotter_ids.append(spotter_id)
        return spotter_ids

    def _spotter_station_names(self, station: Dict[str, Any]) -> List[str]:
        names: List[str] = []
        for value in [station.get('name'), 'NYUAD Sofar Spotter Buoy']:
            name = str(value or '').strip()
            if name and name not in names:
                names.append(name)
        return names

    def _coordinate_match_clause(self, station: Dict[str, Any]) -> Dict[str, Any] | None:
        lat = station.get('lat')
        lon = station.get('lon')
        if lat is None or lon is None:
            return None
        try:
            lat_value = float(lat)
            lon_value = float(lon)
        except (TypeError, ValueError):
            return None
        tolerance = 0.0002
        return {
            'latitude': {'$gte': lat_value - tolerance, '$lte': lat_value + tolerance},
            'longitude': {'$gte': lon_value - tolerance, '$lte': lon_value + tolerance},
        }

    def _station_data_filter(self, station: Dict[str, Any]) -> Dict[str, Any]:
        if self._is_spotter_buoy(station):
            clauses: List[Dict[str, Any]] = []
            for station_id in self._spotter_station_ids(station):
                clauses.extend([
                    {'meta.station_id': station_id},
                    {'station_id': station_id},
                ])
            for spotter_id in self._spotter_spotter_ids(station):
                clauses.extend([
                    {'meta.spotter_id': spotter_id},
                    {'spotter_id': spotter_id},
                ])
            for station_name in self._spotter_station_names(station):
                clauses.extend([
                    {'station_name': station_name},
                    {'meta.station_name': station_name},
                    {'name': station_name},
                    {'meta.name': station_name},
                ])
            coordinate_clause = self._coordinate_match_clause(station)
            if coordinate_clause:
                clauses.append(coordinate_clause)
            if clauses:
                return {'$or': clauses}
            return {'$or': [{'meta.provider': 'sofar'}, {'provider': 'sofar'}]}
        return {}

    def _with_station_data_filter(self, station: Dict[str, Any], query: Dict[str, Any]) -> Dict[str, Any]:
        station_filter = self._station_data_filter(station)
        if not station_filter:
            return dict(query)
        merged = dict(query)
        if any(key in merged for key in station_filter):
            return {'$and': [merged, station_filter]}
        merged.update(station_filter)
        return merged

    def _is_hidden_station_doc(self, doc: Optional[Dict[str, Any]]) -> bool:
        hidden = {item.lower() for item in self.HIDDEN_STATION_STATUSES}
        return str((doc or {}).get('status') or '').strip().lower() in hidden

    def _visible_station_filter(self) -> Dict[str, Any]:
        return {'status': {'$nin': sorted(self.HIDDEN_STATION_STATUSES)}}

    def _station_query(self, station_id: str) -> Dict[str, Any]:
        queries: List[Dict[str, Any]] = [{'id': station_id}]
        if station_id.isdigit():
            queries.append({'station_num': int(station_id)})
        if ObjectId.is_valid(station_id):
            queries.append({'_id': ObjectId(station_id)})
        return {'$or': queries}

    def _public_station_lookup(self) -> Dict[str, Dict[str, Any]]:
        cached = self.cache.get('public_station_lookup:v3')
        if cached is not None:
            return cached
        lookup: Dict[str, Dict[str, Any]] = {}
        cursor = self.db[self.settings.mongo_stations_info_collection].find(
            self._visible_station_filter(),
            self.station_projection,
        )
        for doc in cursor:
            raw_id = str(doc.get('id') or doc.get('_id'))
            public_id = self._public_station_id(raw_id, doc.get('name') or 'Monitoring station')
            lookup[public_id] = doc
        self.cache.set('public_station_lookup:v3', lookup, ttl_seconds=300)
        return lookup

    def _find_station_by_public_id(self, public_id: str) -> Optional[Dict[str, Any]]:
        cache_key = f'public_station_doc:{public_id}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            if self._is_hidden_station_doc(cached):
                return None
            return cached
        doc = self._public_station_lookup().get(public_id)
        if doc:
            self.cache.set(cache_key, doc, ttl_seconds=300)
            return doc
        self.cache.set(cache_key, None, ttl_seconds=60)
        return None

    def _find_station_by_public_id_fresh(self, public_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.db[self.settings.mongo_stations_info_collection].find(
            self._visible_station_filter(),
            self.station_projection,
        )
        for doc in cursor:
            if self._is_hidden_station_doc(doc):
                continue
            raw_id = str(doc.get('id') or doc.get('_id'))
            if self._public_station_id(raw_id, doc.get('name') or 'Monitoring station') == public_id:
                return doc
        return None

    def resolve_station(self, station_id: str) -> Dict[str, Any]:
        cached = self.cache.get(self._station_cache_key(station_id))
        if cached:
            if self._is_hidden_station_doc(cached):
                raise KeyError(f'Station not found: {station_id}')
            return cached
        looks_public = '-' in station_id and not station_id.isdigit() and not ObjectId.is_valid(station_id)
        doc = self._find_station_by_public_id(station_id) if looks_public else None
        if not doc:
            doc = self.db[self.settings.mongo_stations_info_collection].find_one(self._station_query(station_id), self.station_projection)
        if not doc and not looks_public:
            doc = self._find_station_by_public_id(station_id)
        if not doc or self._is_hidden_station_doc(doc):
            raise KeyError(f'Station not found: {station_id}')
        station = self._normalize_station(doc)
        self.cache.set(self._station_cache_key(station_id), station, ttl_seconds=300)
        self.cache.set(self._station_cache_key(station['station_id']), station, ttl_seconds=300)
        self.cache.set(self._station_cache_key(station['public_id']), station, ttl_seconds=300)
        return station

    def resolve_station_fresh(self, station_id: str) -> Dict[str, Any]:
        cached = self.cache.get(self._station_cache_key(station_id))
        if cached:
            if self._is_hidden_station_doc(cached):
                raise KeyError(f'Station not found: {station_id}')
            return cached
        looks_public = '-' in station_id and not station_id.isdigit() and not ObjectId.is_valid(station_id)
        doc = self._find_station_by_public_id_fresh(station_id) if looks_public else None
        if not doc:
            doc = self.db[self.settings.mongo_stations_info_collection].find_one(self._station_query(station_id), self.station_projection)
        if not doc and not looks_public:
            doc = self._find_station_by_public_id_fresh(station_id)
        if not doc or self._is_hidden_station_doc(doc):
            raise KeyError(f'Station not found: {station_id}')
        station = self._normalize_station(doc)
        self.cache.set(self._station_cache_key(station_id), station, ttl_seconds=5)
        self.cache.set(self._station_cache_key(station['station_id']), station, ttl_seconds=5)
        self.cache.set(self._station_cache_key(station['public_id']), station, ttl_seconds=5)
        return station

    def get_filters(self) -> Dict[str, Any]:
        cache_key = 'filters:v3'
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        docs = [
            doc for doc in
            self.db[self.settings.mongo_stations_info_collection].find(
                self._visible_station_filter(),
                {'type': 1, 'status': 1, 'public': 1},
            )
            if not self._is_hidden_station_doc(doc)
        ]
        filters = {
            'privacy': [
                {'value': 'all', 'label': 'All'},
                {'value': 'public', 'label': 'Public'},
                {'value': 'private', 'label': 'Private'},
            ],
            'device_types': [{'value': 'all', 'label': 'All'}],
            'statuses': [{'value': 'all', 'label': 'All'}],
        }
        types = sorted({self._canonical_device_type(doc.get('type')) for doc in docs if doc.get('type')})
        statuses = {self._canonical_station_status(doc.get('status')) for doc in docs if doc.get('status') and not self._is_hidden_station_doc(doc)}
        filters['device_types'].extend([{'value': item, 'label': self.DEVICE_LABELS.get(item, item)} for item in types])
        ordered_statuses = [item for item in self.DASHBOARD_STATUS_ORDER if item in statuses]
        ordered_statuses.extend(sorted(statuses.difference(ordered_statuses)))
        filters['statuses'].extend([{'value': item, 'label': item} for item in ordered_statuses])
        self.cache.set(cache_key, filters, ttl_seconds=300)
        return filters

    def list_stations(
        self,
        privacy: str = 'all',
        device_type: str = 'all',
        status: str = 'all',
        search: str = '',
    ) -> Dict[str, Any]:
        normalized_search = (search or '').strip()
        normalized_device_type = 'all' if device_type == 'all' else self._canonical_device_type(device_type)
        cache_key = f'list_stations:v3:{privacy}:{normalized_device_type}:{status}:{normalized_search.lower()}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        hidden_statuses_lc = {item.lower() for item in self.HIDDEN_STATION_STATUSES}
        if status.lower() in hidden_statuses_lc:
            empty_summary = {
                'total_stations': 0,
                'active_stations': 0,
                'maintenance_stations': 0,
                'public_stations': 0,
                'device_breakdown': {},
                'status_breakdown': {},
            }
            payload = {'summary': empty_summary, 'stations': [], 'filters': self.get_filters()}
            self.cache.set(cache_key, payload, ttl_seconds=300)
            return payload

        query: Dict[str, Any] = {'lat': {'$ne': None}, 'long': {'$ne': None}, **self._visible_station_filter()}
        if privacy == 'public':
            query['public'] = True
        elif privacy == 'private':
            query['public'] = False
        if normalized_device_type != 'all':
            query['type'] = {'$in': self._device_type_query_values(normalized_device_type)}
        if status != 'all':
            query['status'] = {'$in': self._status_query_values(status)}
        if normalized_search:
            regex = {'$regex': re.escape(normalized_search), '$options': 'i'}
            query['$or'] = [{'name': regex}]

        docs = [
            doc for doc in self.db[self.settings.mongo_stations_info_collection].find(query, self.station_projection)
            if not self._is_hidden_station_doc(doc)
        ]
        stations = [self._normalize_station(doc) for doc in docs]
        for station in stations:
            self.cache.set(self._station_cache_key(station['station_id']), station, ttl_seconds=300)
            self.cache.set(self._station_cache_key(station['public_id']), station, ttl_seconds=300)
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
        payload = {'summary': summary, 'stations': [self._public_station_payload(station) for station in stations], 'filters': self.get_filters()}
        self.cache.set(cache_key, payload, ttl_seconds=300)
        return payload

    def get_status_summary(self) -> Dict[str, int]:
        cache_key = 'status_summary:v1'
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        docs = self.db[self.settings.mongo_stations_info_collection].find(
            self._visible_station_filter(),
            {'status': 1},
        )
        summary = {'total': 0, 'healthy': 0, 'maintenance': 0}
        for doc in docs:
            if self._is_hidden_station_doc(doc):
                continue
            summary['total'] += 1
            if doc.get('status') == 'Maintenance':
                summary['maintenance'] += 1
            else:
                summary['healthy'] += 1
        self.cache.set(cache_key, summary, ttl_seconds=120)
        return summary

    def _collection_for_station(self, station: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        station_num = station.get('station_num')
        device_type = station.get('device_type')
        if device_type == 'Meteorological' or station_num == 5463:
            return self.settings.mongo_meteo_collection, 'Timestamp'
        if self._is_spotter_buoy(station):
            return self._spotter_samples_collection(), self._spotter_time_field(station)
        if device_type == 'Buoy' or station_num == 8394:
            return self.settings.mongo_buoy_collection, 'datetime'
        if device_type == 'Fidas_Palas' or station_num == 100:
            return self.settings.mongo_fidas_collection, 'datetime'
        if device_type == 'underwater_probe':
            return str(station.get('station_id') or ''), 'ts'
        if station_num is not None:
            return f'station{station_num}', 'datetime'
        return None, None

    def _spotter_time_field(self, station: Dict[str, Any]) -> str:
        cache_key = f'spotter_time_field:{station["station_id"]}'
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        collection_name = self._spotter_samples_collection()
        if not self._collection_exists(collection_name):
            return 'ts'
        collection = self.db[collection_name]
        for field in ('ts', 'timestamp', 'datetime', 'time'):
            query = self._with_station_data_filter(station, {field: {'$exists': True}})
            if collection.find_one(query, projection={field: 1}):
                self.cache.set(cache_key, field, ttl_seconds=300)
                return field
        self.cache.set(cache_key, 'ts', ttl_seconds=60)
        return 'ts'

    def _spotter_time_uses_strings(self, station: Dict[str, Any], time_field: str) -> bool:
        if not self._is_spotter_buoy(station):
            return False
        cache_key = f'spotter_time_is_string:{station["station_id"]}:{time_field}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return bool(cached)
        collection_name = self._spotter_samples_collection()
        if not self._collection_exists(collection_name):
            self.cache.set(cache_key, False, ttl_seconds=60)
            return False
        query = self._with_station_data_filter(station, {time_field: {'$exists': True}})
        doc = self.db[collection_name].find_one(query, projection={time_field: 1})
        is_string = isinstance((doc or {}).get(time_field), str)
        self.cache.set(cache_key, is_string, ttl_seconds=300)
        return is_string

    def _datetime_string_like(self, sample: Any, value: datetime) -> str:
        sample_text = str(sample or '')
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        if 'T' not in sample_text and ' ' in sample_text:
            if re.search(r'[+-]\d{2}:?\d{2}$', sample_text):
                return value.isoformat(sep=' ', timespec='seconds')
            return value.replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S')
        if sample_text.endswith('Z'):
            return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        return value.isoformat(timespec='seconds')

    def _sbn_waypoint_order(self, value: str | None) -> Optional[int]:
        if not value:
            return None
        match = re.search(r'XT[_\s-]?(\d{1,2})', str(value), flags=re.IGNORECASE)
        if not match:
            return None
        order = int(match.group(1))
        return order if 1 <= order <= 99 else None

    def _sbn_canonical_waypoint(self, value: str | None) -> Optional[str]:
        order = self._sbn_waypoint_order(value)
        if order is None:
            return None
        return f'SBN_XT{order:02d}'

    def _sbn_public_waypoint(self, value: str | None) -> Optional[str]:
        order = self._sbn_waypoint_order(value)
        if order is None:
            return None
        return f'XT{order:02d}'

    def _sbn_metric_label(self, metric: str) -> str:
        return self.SBN_METRIC_LABELS.get(metric, self._pretty_metric_label(metric))

    def _sbn_metric_unit(self, metric: str) -> str:
        if metric in self.SBN_METRIC_UNITS:
            return self.SBN_METRIC_UNITS[metric]
        label = self._sbn_metric_label(metric).lower()
        if 'temperature' in label:
            return '°C'
        if 'salinity' in label:
            return 'PSU'
        if 'oxygen' in label and 'saturation' in label:
            return '%'
        if 'oxygen' in label:
            return 'mg/L'
        if 'turbidity' in label:
            return 'FNU'
        if 'chlorophyll' in label or 'phycoerythrin' in label:
            return 'µg/L'
        if 'conductivity' in label:
            return 'mS/cm'
        if 'pressure' in label:
            return 'dbar'
        return ''

    def _sbn_metric_stats_from_doc(self, doc: Dict[str, Any], metric: str) -> Optional[Dict[str, Any]]:
        metrics = doc.get('metrics')
        if not isinstance(metrics, dict):
            return None
        stats = metrics.get(metric)
        if not isinstance(stats, dict):
            return None
        avg = stats.get('avg')
        if not self._is_numeric_scalar(avg):
            return None
        return {
            'avg': float(avg),
            'min': float(stats['min']) if self._is_numeric_scalar(stats.get('min')) else None,
            'max': float(stats['max']) if self._is_numeric_scalar(stats.get('max')) else None,
            'n': int(stats.get('n') or 0),
        }

    def _sbn_time_extent(self, waypoint_id: Optional[str] = None) -> Dict[str, Optional[str]]:
        canonical = self._sbn_canonical_waypoint(waypoint_id) if waypoint_id else None
        cache_key = f'sbn_time_extent:{canonical or "all"}'
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        profiles = self.db[self.SBN_COLLECTIONS['profiles']]
        query: Dict[str, Any] = {}
        if canonical:
            query['waypoint_id'] = canonical
        projection = {'ts_min': 1, 'ts_max': 1}
        first = profiles.find_one({**query, 'ts_min': {'$exists': True}}, projection=projection, sort=[('ts_min', ASCENDING)])
        last = profiles.find_one({**query, 'ts_max': {'$exists': True}}, projection=projection, sort=[('ts_max', DESCENDING)])
        payload = {
            'earliest': self._human_dt(first.get('ts_min') if first else None) if first else None,
            'latest': self._human_dt(last.get('ts_max') if last else None) if last else None,
            'latest_iso': self._dt_string(last.get('ts_max') if last else None) if last else None,
        }
        self.cache.set(cache_key, payload, ttl_seconds=300)
        return payload

    def _jw_time_extent(self, waypoint_id: Optional[str] = None) -> Dict[str, Optional[str]]:
        canonical = self._jw_canonical_waypoint(waypoint_id) if waypoint_id else None
        cache_key = f'jw_time_extent:{canonical or "all"}'
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        query: Dict[str, Any] = {}
        if canonical:
            query['waypoint_id'] = canonical

        first_dt = None
        last_dt = None
        if self._collection_exists(self.JW_COLLECTIONS['profiles']):
            projection = {'ts_min': 1, 'ts_max': 1}
            profiles = self.db[self.JW_COLLECTIONS['profiles']]
            first = profiles.find_one({**query, 'ts_min': {'$exists': True}}, projection=projection, sort=[('ts_min', ASCENDING)])
            last = profiles.find_one({**query, 'ts_max': {'$exists': True}}, projection=projection, sort=[('ts_max', DESCENDING)])
            first_dt = first.get('ts_min') if first else None
            last_dt = last.get('ts_max') if last else None

        if (first_dt is None or last_dt is None) and self._collection_exists(self.JW_COLLECTIONS['samples']):
            sample_query: Dict[str, Any] = {}
            if canonical:
                sample_query['meta.waypoint_id'] = canonical
            samples = self.db[self.JW_COLLECTIONS['samples']]
            first_sample = samples.find_one({**sample_query, 'ts': {'$exists': True}}, projection={'ts': 1}, sort=[('ts', ASCENDING)])
            last_sample = samples.find_one({**sample_query, 'ts': {'$exists': True}}, projection={'ts': 1}, sort=[('ts', DESCENDING)])
            first_dt = first_dt or (first_sample.get('ts') if first_sample else None)
            last_dt = last_dt or (last_sample.get('ts') if last_sample else None)

        payload = {
            'earliest': self._human_dt(first_dt) if first_dt else None,
            'latest': self._human_dt(last_dt) if last_dt else None,
            'latest_iso': self._dt_string(last_dt) if last_dt else None,
        }
        self.cache.set(cache_key, payload, ttl_seconds=300)
        return payload

    def _station_has_collection(self, station: Dict[str, Any]) -> bool:
        collection_name, _ = self._collection_for_station(station)
        return self._collection_exists(collection_name)

    def get_time_extent(self, station: Dict[str, Any]) -> Dict[str, Optional[str]]:
        cache_key = f'time_extent:{station["station_id"]}'
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        if station.get('device_type') == 'SBNTransect':
            payload = self._sbn_time_extent(str(station.get('station_id') or ''))
            self.cache.set(cache_key, payload, ttl_seconds=300)
            return payload

        if station.get('device_type') == 'JWCruise':
            payload = self._jw_time_extent(str(station.get('station_id') or ''))
            self.cache.set(cache_key, payload, ttl_seconds=300)
            return payload

        collection_name, time_field = self._collection_for_station(station)
        if not self._collection_exists(collection_name):
            payload = {'earliest': None, 'latest': None}
            self.cache.set(cache_key, payload, ttl_seconds=60)
            return payload

        self._ensure_time_index(collection_name, time_field)
        collection = self.db[collection_name]
        query = self._with_station_data_filter(station, {time_field: {'$exists': True}})
        first = collection.find_one(query, sort=[(time_field, ASCENDING)], projection={time_field: 1})
        last = collection.find_one(query, sort=[(time_field, DESCENDING)], projection={time_field: 1})
        payload = {
            'earliest': self._human_dt_for_station(station, first.get(time_field) if first else None) if first else None,
            'latest': self._human_dt_for_station(station, last.get(time_field) if last else None) if last else None,
            'earliest_iso': self._dt_string_for_station(station, first.get(time_field) if first else None) if first else None,
            'latest_iso': self._dt_string_for_station(station, last.get(time_field) if last else None) if last else None,
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
        if not self._collection_exists(collection_name):
            self.cache.set(cache_key, None, ttl_seconds=30)
            return None
        self._ensure_time_index(collection_name, time_field)
        query = self._with_station_data_filter(station, {})
        document = self.db[collection_name].find_one(query, projection=projection, sort=[(time_field, DESCENDING)])
        self.cache.set(cache_key, document, ttl_seconds=30)
        return document

    def _freshness_payload(self, station: Dict[str, Any], latest_dt: datetime | None) -> Dict[str, Any]:
        now = self._now()
        latest_dt = self._station_actual_datetime(station, latest_dt)
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
            'advanced_analysis': station['device_type'] in self.TIME_SERIES_TYPES or station['device_type'] == 'SBNTransect',
            'metadata': True,
            'raw_export': station['device_type'] in self.TIME_SERIES_TYPES,
        }
        return {
            **station,
            'coordinates': {'lat': station['lat'], 'lon': station['lon']},
            'data_extent': extent,
            'freshness': freshness,
            'capabilities': capabilities,
            'collection_name': collection_name,
        }

    def get_metadata_payload(self, station_id: str, station: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        station = station or self.get_station_summary(station_id)
        measurement_frequency = (
            'Continuous real-time monitoring.'
            if station['device_type'] in self.SPECIAL_REALTIME_TYPES
            else 'Interval time-series sampling collected during the monitoring program.'
            if station['device_type'] == 'underwater_probe'
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
            'tabs': self.metadata_service.metadata_tabs_for_device(
                'SpotterBuoy' if self._is_spotter_buoy(station) else station['device_type']
            ),
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

    def _meteo_label_map(self) -> Dict[str, str]:
        return {
            'S2_TA[C]': 'Temperature (°C)',
            'S2_RH[%]': 'Relative Humidity (%)',
            'S2_PA': 'Atmospheric Pressure (hPa)',
            'S2_WS[M/S]': 'Wind Speed (m/s)',
            'S2_WD': 'Wind Direction (°)',
            'S1_RAD': 'Radiation (W/m²)',
            'S2_PREC[MM]': 'Precipitation (mm)',
            'S2_DP[C]': 'Dew Point (°C)',
            'I3_VPOWER': 'Voltage Power (V)',
            'I4_VOUT': 'Voltage Output (V)',
        }

    def _fidas_label_map(self) -> Dict[str, str]:
        return {
            'PM2.5': 'PM2.5 (µg/m³)',
            'PM10': 'PM10 (µg/m³)',
            'PM1': 'PM1 (µg/m³)',
            'T': 'Temperature (°C)',
            'rH': 'Relative Humidity (%)',
            'p': 'Pressure (hPa)',
            'PM4': 'PM4 (µg/m³)',
            'PMtot': 'Total PM (µg/m³)',
            'Cn': 'Count Number (particles/cm³)',
            'dewT': 'Dew Point (°C)',
            'Wspeed': 'Wind Speed (km/h)',
            'Wdir': 'Wind Direction (°)',
            'feelLike': 'Feels Like (°C)',
            'wbgt': 'WBGT (°C)',
        }

    def _is_numeric_scalar(self, value: Any) -> bool:
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float, np.integer, np.floating)):
            return math.isfinite(float(value))
        if isinstance(value, str):
            text = value.strip()
            if not text or text.upper() in {'NAN', 'NA', 'N/A', 'NULL', 'NONE'}:
                return False
            try:
                return math.isfinite(float(text))
            except ValueError:
                return False
        return False

    def _nested_metric_key(self, root: str, child: str) -> str:
        if root == 'PM2':
            return f'PM2.{child}'
        return f'{root}.{child}'

    def _numeric_metric_keys_from_doc(self, doc: Dict[str, Any], time_field: str) -> Iterable[str]:
        for key, value in doc.items():
            if key in self.DOCUMENT_METRIC_EXCLUDES or key == time_field:
                continue
            if self._is_numeric_scalar(value):
                yield key
            elif isinstance(value, dict):
                for child_key, child_value in value.items():
                    if self._is_numeric_scalar(child_value):
                        yield self._nested_metric_key(key, str(child_key))

    def _pretty_metric_label(self, key: str) -> str:
        spaced = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', key)
        spaced = spaced.replace('_', ' ').replace('.', ' ')
        return spaced.strip().title() or key

    def _document_metric_label(self, station: Dict[str, Any], key: str) -> str:
        if station['device_type'] == 'Meteorological':
            return self.METEO_LABEL_OVERRIDES.get(key, self._pretty_metric_label(key))
        if station['device_type'] == 'Fidas_Palas':
            if key in self.FIDAS_LABEL_OVERRIDES:
                return self.FIDAS_LABEL_OVERRIDES[key]
            if key.startswith('PM') and any(char.isdigit() for char in key):
                return f'{key} (µg/m³)'
            return self._pretty_metric_label(key)
        if self._is_spotter_buoy(station):
            return self.SPOTTER_BUOY_LABEL_OVERRIDES.get(key, self._pretty_metric_label(key))
        if station['device_type'] == 'underwater_probe':
            return self.UNDERWATER_LABEL_OVERRIDES.get(key, self._pretty_metric_label(key))
        return self._metric_key_to_label(station, key)

    def _ordered_document_metrics(self, station: Dict[str, Any], keys: Iterable[str]) -> List[str]:
        if station['device_type'] == 'Meteorological':
            priority = self.METEO_METRIC_PRIORITY
        elif station['device_type'] == 'Fidas_Palas':
            priority = self.FIDAS_METRIC_PRIORITY
        elif self._is_spotter_buoy(station):
            priority = self.SPOTTER_BUOY_METRIC_PRIORITY
        elif station['device_type'] == 'underwater_probe':
            priority = self.UNDERWATER_METRIC_PRIORITY
        else:
            priority = []
        rank = {key: index for index, key in enumerate(priority)}
        return sorted(
            keys,
            key=lambda item: (
                rank.get(item, len(priority)),
                self._document_metric_label(station, item).lower(),
                item,
            ),
        )

    def _document_metric_map(self, station: Dict[str, Any], collection_name: str, time_field: str) -> Dict[str, str]:
        cache_key = f'document_metrics:{station["station_id"]}:{station["device_type"]}:{collection_name}:{time_field}'
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        if not self._collection_exists(collection_name):
            return {}
        self._ensure_time_index(collection_name, time_field)
        collection = self.db[collection_name]
        query = self._with_station_data_filter(station, {time_field: {'$exists': True}})
        discovered: List[str] = []
        seen: set[str] = set()
        is_spotter = self._is_spotter_buoy(station)
        for doc in collection.find(query).sort(time_field, DESCENDING).limit(200):
            for key in self._numeric_metric_keys_from_doc(doc, time_field):
                metric_key = self._spotter_canonical_metric_key(key) if is_spotter else key
                if metric_key not in seen:
                    seen.add(metric_key)
                    discovered.append(metric_key)
        ordered = self._ordered_document_metrics(station, discovered)
        metric_map = {key: self._document_metric_label(station, key) for key in ordered}
        self.cache.set(cache_key, metric_map, ttl_seconds=300)
        return metric_map

    def _spotter_alias_key(self, value: str) -> str:
        text = str(value or '').lower().replace('°', 'deg')
        return re.sub(r'[^a-z0-9]+', '', text)

    def _spotter_canonical_metric_key(self, key: str) -> str:
        normalized = self._spotter_alias_key(key)
        for canonical, aliases in self.SPOTTER_BUOY_ALIASES.items():
            if normalized in {self._spotter_alias_key(alias) for alias in aliases}:
                return canonical
        return key

    def _spotter_metric_sources(self, metric: str) -> List[str]:
        aliases = self.SPOTTER_BUOY_ALIASES.get(metric, [metric])
        sources: List[str] = []
        for alias in [metric, *aliases]:
            if alias and alias not in sources:
                sources.append(alias)
        return sources

    def _spotter_buoy_metric_map(self, station: Dict[str, Any]) -> Dict[str, str]:
        cache_key = f'spotter_buoy_metrics:{station["station_id"]}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        metric_map = self._document_metric_map(station, self._spotter_samples_collection(), self._spotter_time_field(station))
        registry_collection = self._spotter_registry_collection()
        if self._collection_exists(registry_collection):
            discovered = [
                self._spotter_canonical_metric_key(doc.get('target_field'))
                for doc in self.db[registry_collection].find(
                    {'provider': 'sofar', 'target_field': {'$exists': True}},
                    {'_id': 0, 'target_field': 1},
                )
                if doc.get('target_field')
            ]
            merged = dict.fromkeys([*metric_map.keys(), *discovered])
            ordered = self._ordered_document_metrics(station, merged.keys())
            metric_map = {key: self._document_metric_label(station, key) for key in ordered}
        metric_map = {
            key: label
            for key, label in metric_map.items()
            if key not in self.SPOTTER_BUOY_PARAMETER_EXCLUDES
        }
        self.cache.set(cache_key, metric_map, ttl_seconds=300)
        return metric_map

    def _buoy_label_map(self, station: Dict[str, Any]) -> Dict[str, str]:
        if self._is_spotter_buoy(station):
            return self._spotter_buoy_metric_map(station)
        params = self.BUOY_SCALAR_PARAMS + self.BUOY_PROFILE_PARAMS
        return {metric: self._metric_key_to_label(station, metric) for metric in params}

    def _underwater_canonical_metric(self, metric: str) -> str:
        for canonical, aliases in self.UNDERWATER_ALIAS_GROUPS.items():
            if metric == canonical or metric in aliases:
                return canonical
        return metric

    def _underwater_metric_aliases(self, metric: str) -> List[str]:
        canonical = self._underwater_canonical_metric(metric)
        return self.UNDERWATER_ALIAS_GROUPS.get(canonical, [canonical])

    def _canonicalize_underwater_metrics(self, metrics: Iterable[str]) -> List[str]:
        selected: List[str] = []
        for metric in metrics:
            canonical = self._underwater_canonical_metric(metric)
            if canonical not in selected:
                selected.append(canonical)
        return selected

    def _available_metric_map(self, station: Dict[str, Any]) -> Dict[str, str]:
        if station['device_type'] == 'IoTBox':
            labels, _full_params = self._iot_discover(int(station['station_num']))
            return labels
        if station['device_type'] == 'Meteorological':
            return self._document_metric_map(station, self.settings.mongo_meteo_collection, 'Timestamp')
        if station['device_type'] == 'Fidas_Palas':
            return self._document_metric_map(station, self.settings.mongo_fidas_collection, 'datetime')
        if station['device_type'] == 'Buoy':
            return self._buoy_label_map(station)
        if station['device_type'] == 'underwater_probe':
            collection_name, time_field = self._collection_for_station(station)
            raw_map = self._document_metric_map(station, collection_name or '', time_field or 'ts')
            collapsed: Dict[str, str] = {}
            for key, label in raw_map.items():
                canonical = self._underwater_canonical_metric(key)
                if canonical not in collapsed:
                    collapsed[canonical] = self._document_metric_label(station, canonical) if canonical != key else label
            ordered = self._ordered_document_metrics(station, collapsed.keys())
            return {key: collapsed[key] for key in ordered}
        return {}

    def _metric_options(self, station: Dict[str, Any], label_map: Dict[str, str]) -> List[Dict[str, str]]:
        available = self._available_metric_map(station) or label_map
        return [{'key': key, 'label': available.get(key, key)} for key in available.keys()]

    def _iot_discover(self, station_num: int) -> Tuple[Dict[str, str], Dict[str, List[Tuple[str, str]]]]:
        cache_key = f'iot_discover:{station_num}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        station_info = self.db[self.settings.mongo_stations_info_collection].find_one({'station_num': station_num}, {'sensors': 1})
        if not station_info or 'sensors' not in station_info:
            return {}, {}
        self._ensure_time_index(f'station{station_num}', 'datetime')
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
        payload = (ordered, full_params)
        self.cache.set(cache_key, payload, ttl_seconds=300)
        return payload

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
            if self._is_spotter_buoy(station):
                return self.SPOTTER_BUOY_LABEL_OVERRIDES.get(key, self._pretty_metric_label(key))
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
        if station['device_type'] == 'underwater_probe':
            return self.UNDERWATER_LABEL_OVERRIDES.get(key, self._pretty_metric_label(key))
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
        if 'dissolved oxygen' in low:
            return 'Dissolved Oxygen'
        if 'salinity' in low:
            return 'Salinity'
        if 'turbidity' in low:
            return 'Turbidity'
        if 'chlorophyll' in low:
            return 'Chlorophyll'
        if low == 'ph' or label == 'pH':
            return 'pH'
        if 'depth' in low:
            return 'Depth'
        if 'wave height' in low:
            return 'Wave Height'
        if 'period' in low:
            return 'Wave Period'
        if 'wave direction' in low or 'directional' in low:
            return 'Wave Direction'
        if 'battery' in low:
            return 'Battery'
        return label

    def _default_metrics(self, available_map: Dict[str, str], limit: int = 6) -> List[str]:
        preferred: List[str] = []
        for desired in self.DEFAULT_METRIC_PRIORITY:
            for key, label in available_map.items():
                if self._label_to_canonical(label) == desired and key not in preferred:
                    preferred.append(key)
                    break
        if len(preferred) >= limit:
            return preferred[:limit]
        seen_canonical = {self._label_to_canonical(available_map[key]) for key in preferred}
        for key in available_map.keys():
            canonical = self._label_to_canonical(available_map[key])
            if key not in preferred and canonical not in seen_canonical:
                preferred.append(key)
                seen_canonical.add(canonical)
            if len(preferred) >= limit:
                return preferred[:limit]
        for key in available_map.keys():
            if key not in preferred:
                preferred.append(key)
            if len(preferred) >= limit:
                return preferred[:limit]
        return preferred[:limit]

    def _quick_metrics_for_station(self, station: Dict[str, Any]) -> List[str]:
        available = self._available_metric_map(station)
        if station['device_type'] == 'Meteorological':
            return list(available.keys())
        if station['device_type'] == 'Fidas_Palas':
            selected = [key for key in self.FIDAS_QUICK_METRIC_PRIORITY if key in available]
            for key in available:
                if key in self.FIDAS_CALCULATED_KEYS and key not in selected:
                    selected.append(key)
            return selected or self._default_metrics(available)
        if station['device_type'] == 'Buoy':
            if self._is_spotter_buoy(station):
                selected = [key for key in self.SPOTTER_BUOY_METRIC_PRIORITY if key in available]
                return (selected or self._default_metrics(available, limit=6))[:6]
            return [key for key in self.BUOY_SCALAR_PARAMS if key in available]
        if station['device_type'] == 'underwater_probe':
            selected: List[str] = []
            seen_labels: set[str] = set()
            for key in self.UNDERWATER_METRIC_PRIORITY:
                label = available.get(key)
                if label and label not in seen_labels:
                    selected.append(key)
                    seen_labels.add(label)
                if len(selected) >= 6:
                    break
            return selected or self._default_metrics(available, limit=6)
        return self._default_metrics(available, limit=6)

    # ------------------------------------------------------------------
    # Timeseries extraction
    # ------------------------------------------------------------------
    def _base_query_for_period(self, period: str, time_field: str) -> Dict[str, Any]:
        delta = self.PERIOD_MAP.get(period.upper())
        if delta is None:
            return {}
        return {time_field: {'$gte': self._now() - delta}}

    def _base_query_for_station_period(self, station: Dict[str, Any], period: str, time_field: str) -> Dict[str, Any]:
        delta = self.PERIOD_MAP.get(period.upper())
        if delta is None:
            return {}
        collection_name, _ = self._collection_for_station(station)
        latest_raw = None
        anchor = None
        if self._collection_exists(collection_name):
            self._ensure_time_index(collection_name, time_field)
            latest = self._latest_document(station, projection={time_field: 1})
            latest_raw = latest.get(time_field) if latest else None
            anchor = self._coerce_datetime(latest_raw)
        if anchor is None:
            anchor = self._now()
            if station.get('device_type') == 'Fidas_Palas':
                anchor = anchor + self._local_tz_offset()
        if self._is_spotter_buoy(station) and isinstance(latest_raw, str):
            return {
                time_field: {
                    '$gte': self._datetime_string_like(latest_raw, anchor - delta),
                    '$lte': latest_raw,
                }
            }
        return {time_field: {'$gte': anchor - delta, '$lte': anchor}}

    def _date_boundary_for_query(self, station: Dict[str, Any], value: Optional[str], end: bool = False) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.strptime(str(value)[:10], '%Y-%m-%d')
        except ValueError:
            return None
        localized = parsed.replace(tzinfo=self.local_tz)
        if end:
            localized = localized + timedelta(days=1)
        boundary = localized.astimezone(timezone.utc)
        if station.get('device_type') == 'Fidas_Palas':
            boundary = boundary + self._local_tz_offset()
        return boundary

    def _base_query_for_station_window(
        self,
        station: Dict[str, Any],
        period: str,
        time_field: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        start_dt = self._date_boundary_for_query(station, start_date, end=False)
        end_dt = self._date_boundary_for_query(station, end_date, end=True)
        if start_dt or end_dt:
            window: Dict[str, datetime] = {}
            if self._spotter_time_uses_strings(station, time_field):
                sample = None
                collection_name, _ = self._collection_for_station(station)
                if self._collection_exists(collection_name):
                    query = self._with_station_data_filter(station, {time_field: {'$exists': True}})
                    sample_doc = self.db[collection_name].find_one(query, projection={time_field: 1})
                    sample = (sample_doc or {}).get(time_field)
                if start_dt:
                    window['$gte'] = self._datetime_string_like(sample, start_dt)
                if end_dt:
                    window['$lt'] = self._datetime_string_like(sample, end_dt)
            else:
                if start_dt:
                    window['$gte'] = start_dt
                if end_dt:
                    window['$lt'] = end_dt
            return {time_field: window}
        return self._base_query_for_station_period(station, period, time_field)

    def _window_label(self, period: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
        if start_date or end_date:
            return f'{start_date or "start"} to {end_date or "latest"}'
        return period

    def get_available_dates(self, station_id: str, station: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        station = station or self.get_station_summary(station_id)
        cache_key = f'available_dates:{station["station_id"]}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        collection_name, time_field = self._collection_for_station(station)
        if not collection_name or not time_field or not self._collection_exists(collection_name):
            payload = {'station': station, 'dates': [], 'earliest_date': None, 'latest_date': None}
            self.cache.set(cache_key, payload, ttl_seconds=300)
            return payload

        self._ensure_time_index(collection_name, time_field)
        collection = self.db[collection_name]
        query = self._with_station_data_filter(station, {time_field: {'$exists': True}})
        first = collection.find_one(query, projection={time_field: 1}, sort=[(time_field, ASCENDING)])
        last = collection.find_one(query, projection={time_field: 1}, sort=[(time_field, DESCENDING)])
        first_dt = self._localize_station_datetime(station, first.get(time_field) if first else None)
        last_dt = self._localize_station_datetime(station, last.get(time_field) if last else None)
        dates: List[str] = []
        if first_dt and last_dt:
            current = first_dt.date()
            end = last_dt.date()
            while current <= end:
                dates.append(current.isoformat())
                current += timedelta(days=1)
        payload = {
            'station': station,
            'dates': dates,
            'earliest_date': dates[0] if dates else None,
            'latest_date': dates[-1] if dates else None,
        }
        self.cache.set(cache_key, payload, ttl_seconds=3600)
        return payload

    def _aggregate_df(self, df: pd.DataFrame, freq: str | None) -> pd.DataFrame:
        if df.empty or not freq:
            return df
        df = df.copy()
        df = df.set_index('timestamp')
        numeric_cols = df.select_dtypes(include=['number']).columns
        if numeric_cols.empty:
            return pd.DataFrame(columns=['timestamp'])
        grouped = df[numeric_cols].resample(freq).mean().dropna(how='all').reset_index()
        return grouped

    def _display_point_cap(self, point_cap: Optional[int]) -> Optional[int]:
        if point_cap is None:
            return None
        return max(120, min(int(point_cap), self.MAX_CHART_POINTS))

    def _time_sampled_documents(
        self,
        collection_name: str,
        time_field: str,
        query: Dict[str, Any],
        projection: Dict[str, int],
        point_cap: Optional[int],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        self._ensure_time_index(collection_name, time_field)
        collection = self.db[collection_name]
        cap = self._display_point_cap(point_cap)
        meta = {
            'source_points': None,
            'sampled': False,
            'display_cap': cap,
        }
        if cap is None:
            docs = list(collection.find(query, projection).sort(time_field, ASCENDING))
            meta['source_points'] = len(docs)
            meta['returned_points'] = len(docs)
            return docs, meta

        project_stage = dict(projection)
        project_stage[time_field] = 1
        if time_field not in query:
            pipeline = []
            if query:
                pipeline.extend([
                    {'$sample': {'size': min(cap * 6, 5000)}},
                    {'$match': query},
                    {'$limit': cap},
                ])
            else:
                pipeline.append({'$sample': {'size': cap}})
            pipeline.extend([
                {'$project': project_stage},
                {'$sort': {time_field: ASCENDING}},
            ])
            docs = list(collection.aggregate(pipeline, allowDiskUse=True))
            meta.update({'source_points': len(docs), 'returned_points': len(docs), 'sampled': True})
            return docs, meta

        first = collection.find_one(query, projection={time_field: 1}, sort=[(time_field, ASCENDING)])
        last = collection.find_one(query, projection={time_field: 1}, sort=[(time_field, DESCENDING)])
        start_raw = first.get(time_field) if first else None
        end_raw = last.get(time_field) if last else None
        start_dt = self._coerce_datetime(start_raw)
        end_dt = self._coerce_datetime(end_raw)
        if not isinstance(start_raw, datetime) or not isinstance(end_raw, datetime):
            docs = list(collection.find(query, projection).sort(time_field, ASCENDING).limit(cap))
            meta.update({'source_points': len(docs), 'returned_points': len(docs), 'sampled': bool(cap)})
            return docs, meta
        if not isinstance(start_dt, datetime) or not isinstance(end_dt, datetime) or start_dt >= end_dt:
            doc = collection.find_one(query, projection=projection, sort=[(time_field, DESCENDING)])
            docs = [doc] if doc else []
            meta.update({'source_points': len(docs), 'returned_points': len(docs), 'sampled': False})
            return docs, meta

        bucket_ms = max(1, int(math.ceil((end_dt - start_dt).total_seconds() * 1000 / cap)))
        pipeline = [
            {'$match': query},
            {'$sort': {time_field: ASCENDING}},
            {'$project': project_stage},
            {'$addFields': {
                '_sample_bucket': {
                    '$floor': {
                        '$divide': [
                            {'$subtract': [f'${time_field}', start_dt]},
                            bucket_ms,
                        ]
                    }
                }
            }},
            {'$group': {'_id': '$_sample_bucket', 'doc': {'$last': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$doc'}},
            {'$sort': {time_field: ASCENDING}},
            {'$limit': cap},
        ]
        docs = list(collection.aggregate(pipeline, allowDiskUse=True))
        meta.update({'returned_points': len(docs), 'sampled': True})
        return docs, meta

    def _limit_frame_points(self, df: pd.DataFrame, point_cap: Optional[int], meta: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        if df.empty:
            return df
        cap = self._display_point_cap(point_cap)
        source_value = (meta or {}).get('source_points')
        source_points = int(source_value) if source_value is not None else len(df)
        sampled = bool((meta or {}).get('sampled', False))
        if cap is not None and len(df) > cap:
            indexes = np.linspace(0, len(df) - 1, cap).round().astype(int)
            df = df.iloc[sorted(set(indexes.tolist()))].reset_index(drop=True)
            sampled = True
        df.attrs.update({
            'source_points': source_points,
            'returned_points': int(len(df)),
            'sampled': sampled,
            'display_cap': cap,
        })
        return df

    def _iot_dataframe(
        self,
        station: Dict[str, Any],
        metrics: List[str],
        split_sensors: bool,
        period: str,
        aggregation: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        display_points: Optional[int] = MAX_CHART_POINTS,
    ) -> Tuple[pd.DataFrame, Dict[str, str]]:
        labels, full_params = self._iot_discover(int(station['station_num']))
        if not metrics:
            metrics = self._default_metrics(labels, limit=3)
        selected_full = {metric: full_params[metric] for metric in metrics if metric in full_params}
        plot_labels = dict(labels)
        for sensor_list in selected_full.values():
            for full_key, sensor_label in sensor_list:
                plot_labels[full_key] = sensor_label

        projection: Dict[str, int] = {'_id': 0, 'datetime': 1}
        for sensor_list in selected_full.values():
            for full_key, _ in sensor_list:
                projection[full_key.split('.', 1)[0]] = 1

        query = self._base_query_for_station_window(station, period, 'datetime', start_date, end_date)
        collection_name = f'station{station["station_num"]}'
        docs, meta = self._time_sampled_documents(collection_name, 'datetime', query, projection, display_points)
        data: List[Dict[str, Any]] = []
        for record in docs:
            entry: Dict[str, Any] = {'timestamp': self._localize(record.get('datetime'))}
            for _base_param, sensor_list in selected_full.items():
                for full_key, _label in sensor_list:
                    sensor_key, sensor_param = full_key.split('.', 1)
                    sensor_doc = record.get(sensor_key, {})
                    if isinstance(sensor_doc, dict) and sensor_param in sensor_doc and isinstance(sensor_doc[sensor_param], (int, float)):
                        entry[full_key] = sensor_doc[sensor_param]
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
        df = self._limit_frame_points(df, display_points, meta)
        return df, plot_labels

    def _metric_projection_root(self, metric: str) -> str:
        if metric.startswith('PM2.'):
            return 'PM2'
        return metric.split('.', 1)[0]

    def _document_metric_value(self, doc: Dict[str, Any], metric: str) -> Any:
        if metric.startswith('PM2.'):
            pm2 = doc.get('PM2')
            if isinstance(pm2, dict):
                return pm2.get(metric.split('.', 1)[1])
            return None
        value: Any = doc
        for part in metric.split('.'):
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        return value

    def _coerce_document_number(self, value: Any) -> Optional[float]:
        if not self._is_numeric_scalar(value):
            return None
        return float(value)

    def _first_document_metric_number(self, doc: Dict[str, Any], metrics: Iterable[str]) -> Optional[float]:
        for metric in metrics:
            value = self._coerce_document_number(self._document_metric_value(doc, metric))
            if value is not None:
                return value
        return None

    def _document_dataframe(
        self,
        station: Dict[str, Any],
        collection_name: str,
        time_field: str,
        metrics: List[str],
        period: str,
        aggregation: str,
        clean: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        display_points: Optional[int] = MAX_CHART_POINTS,
    ) -> Tuple[pd.DataFrame, Dict[str, str]]:
        label_map = self._available_metric_map(station)
        if not metrics:
            metrics = self._default_metrics(label_map, limit=3)
        if station['device_type'] == 'underwater_probe':
            metrics = self._canonicalize_underwater_metrics(metrics)
        metrics = [metric for metric in metrics if metric in label_map]
        if not metrics:
            return pd.DataFrame(), label_map
        metric_sources = {}
        for metric in metrics:
            if station['device_type'] == 'underwater_probe':
                metric_sources[metric] = self._underwater_metric_aliases(metric)
            elif self._is_spotter_buoy(station):
                metric_sources[metric] = self._spotter_metric_sources(metric)
            else:
                metric_sources[metric] = [metric]

        query = self._with_station_data_filter(
            station,
            self._base_query_for_station_window(station, period, time_field, start_date, end_date),
        )
        projection = {'_id': 0, time_field: 1}
        for metric in metrics:
            for source_metric in metric_sources[metric]:
                projection[self._metric_projection_root(source_metric)] = 1
        clean_fidas = clean and station['device_type'] == 'Fidas_Palas'
        if clean_fidas:
            projection['errors'] = 1
            query['errors'] = {'$lte': 0}

        docs, meta = self._time_sampled_documents(collection_name, time_field, query, projection, display_points)
        present_fields: set[str] = set()
        for doc in docs:
            for metric in metrics:
                if self._first_document_metric_number(doc, metric_sources[metric]) is not None:
                    present_fields.add(metric)
        missing_fields = [metric for metric in metrics if metric not in present_fields]
        stable_document_station = station['device_type'] in {'Fidas_Palas', 'Meteorological'}
        if missing_fields and display_points and not stable_document_station:
            seen_stamps = {doc.get(time_field) for doc in docs}
            backfill_limit = max(24, min(180, self._display_point_cap(display_points) or 180))
            collection = self.db[collection_name]
            for metric in missing_fields:
                metric_query = dict(query)
                aliases = metric_sources[metric]
                if len(aliases) == 1:
                    metric_query[aliases[0]] = {'$exists': True}
                else:
                    alias_clause = {'$or': [{alias: {'$exists': True}} for alias in aliases]}
                    if '$or' in metric_query:
                        metric_query = {'$and': [metric_query, alias_clause]}
                    else:
                        metric_query['$or'] = alias_clause['$or']
                cursor = collection.find(metric_query, projection).limit(backfill_limit)
                hint_name = None
                if station.get('device_type') == 'Fidas_Palas':
                    if metric == 'PM2.5':
                        hint_name = 'errors_pm25_datetime_1'
                    elif metric == 'PM10':
                        hint_name = 'errors_pm10_datetime_1'
                    elif metric == 'PM1':
                        hint_name = 'errors_pm1_datetime_1'
                if hint_name:
                    try:
                        cursor = cursor.hint(hint_name)
                    except Exception:
                        pass
                for doc in cursor:
                    stamp = doc.get(time_field)
                    if stamp in seen_stamps:
                        continue
                    seen_stamps.add(stamp)
                    docs.append(doc)
            docs.sort(key=lambda item: item.get(time_field) or datetime.min.replace(tzinfo=timezone.utc))
        rows: List[Dict[str, Any]] = []
        for doc in docs:
            row: Dict[str, Any] = {'timestamp': self._localize_station_datetime(station, doc.get(time_field))}
            if clean_fidas:
                row['_fidas_errors'] = self._coerce_document_number(doc.get('errors')) or 0.0
            for metric in metrics:
                value = self._first_document_metric_number(doc, metric_sources[metric])
                if value is not None:
                    row[metric] = value
            rows.append(row)

        df = pd.DataFrame(rows)
        if df.empty:
            return df, label_map
        if clean_fidas and '_fidas_errors' in df.columns:
            errors = pd.to_numeric(df['_fidas_errors'], errors='coerce').fillna(0.0)
            averaged = errors.copy()
            if len(errors) > 2:
                averaged.iloc[1:-1] = (
                    errors.shift(-1).iloc[1:-1] + errors.iloc[1:-1] + errors.shift(1).iloc[1:-1]
                ) / 3
            cleanable = [metric for metric in metrics if metric in df.columns and metric not in self.FIDAS_DO_NOT_CLEAN]
            if cleanable:
                df.loc[averaged > 0, cleanable] = np.nan
                df = df.dropna(subset=cleanable, how='all')
            df = df.drop(columns=['_fidas_errors'])
        df = self._aggregate_df(df, self.AGG_MAP.get(aggregation.lower()))
        df = self._limit_frame_points(df, display_points, meta)
        return df, label_map

    def _meteo_dataframe(self, station: Dict[str, Any], metrics: List[str], period: str, aggregation: str, start_date: Optional[str] = None, end_date: Optional[str] = None, display_points: Optional[int] = MAX_CHART_POINTS) -> Tuple[pd.DataFrame, Dict[str, str]]:
        return self._document_dataframe(station, self.settings.mongo_meteo_collection, 'Timestamp', metrics, period, aggregation, start_date=start_date, end_date=end_date, display_points=display_points)
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
        for metric in metrics:
            if metric in df.columns:
                df[metric] = pd.to_numeric(df[metric], errors='coerce')
        df = self._aggregate_df(df, self.AGG_MAP.get(aggregation.lower()))
        return df, label_map

    def _fidas_dataframe(self, station: Dict[str, Any], metrics: List[str], period: str, aggregation: str, clean: bool = False, start_date: Optional[str] = None, end_date: Optional[str] = None, display_points: Optional[int] = MAX_CHART_POINTS) -> Tuple[pd.DataFrame, Dict[str, str]]:
        return self._document_dataframe(station, self.settings.mongo_fidas_collection, 'datetime', metrics, period, aggregation, clean=clean, start_date=start_date, end_date=end_date, display_points=display_points)
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

    def _underwater_dataframe(self, station: Dict[str, Any], metrics: List[str], period: str, aggregation: str, start_date: Optional[str] = None, end_date: Optional[str] = None, display_points: Optional[int] = MAX_CHART_POINTS) -> Tuple[pd.DataFrame, Dict[str, str]]:
        collection_name, time_field = self._collection_for_station(station)
        if not collection_name or not time_field:
            return pd.DataFrame(), {}
        return self._document_dataframe(station, collection_name, time_field, metrics, period, aggregation, start_date=start_date, end_date=end_date, display_points=display_points)

    def _buoy_dataframe(self, station: Dict[str, Any], metrics: List[str], period: str, aggregation: str, start_date: Optional[str] = None, end_date: Optional[str] = None, display_points: Optional[int] = MAX_CHART_POINTS) -> Tuple[pd.DataFrame, Dict[str, str], List[Dict[str, Any]]]:
        if self._is_spotter_buoy(station):
            collection_name, time_field = self._collection_for_station(station)
            if not collection_name or not time_field:
                return pd.DataFrame(), self._spotter_buoy_metric_map(station), []
            if not metrics:
                available = self._spotter_buoy_metric_map(station)
                metrics = [key for key in self.SPOTTER_BUOY_METRIC_PRIORITY if key in available][:3]
                if not metrics:
                    metrics = self._default_metrics(available, limit=3)
            df, label_map = self._document_dataframe(
                station,
                collection_name,
                time_field,
                metrics,
                period,
                aggregation,
                start_date=start_date,
                end_date=end_date,
                display_points=display_points,
            )
            return df, label_map, []

        scalar_params = self.BUOY_SCALAR_PARAMS
        profile_params = self.BUOY_PROFILE_PARAMS
        label_map = {metric: self._metric_key_to_label(station, metric) for metric in scalar_params + profile_params}
        if not metrics:
            metrics = [metric for metric in self.BUOY_DEFAULT_SCALAR_PARAMS if metric in scalar_params]
        query = self._base_query_for_station_window(station, period, 'datetime', start_date, end_date)
        projection = {'_id': 0, 'datetime': 1, 'depth': 1}
        for metric in metrics:
            projection[metric] = 1
        docs, meta = self._time_sampled_documents(self.settings.mongo_buoy_collection, 'datetime', query, projection, display_points)
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
        df = self._limit_frame_points(df, display_points, meta)
        return df, label_map, profiles[-5:]

    def get_buoy_profiles(
        self,
        station_id: str,
        period: str = '24H',
        metrics: Optional[List[str]] = None,
        station: Optional[Dict[str, Any]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        station = station or self.get_station_summary(station_id)
        metric_key = '|'.join(metrics or [])
        cache_key = f'buoy_profiles:{station["station_id"]}:{period.upper()}:{start_date or ""}:{end_date or ""}:{metric_key}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        if station['device_type'] != 'Buoy':
            return {
                'station': station,
                'period': self._window_label(period, start_date, end_date),
                'available_metrics': [],
                'charts': [],
                'message': 'Profile charts are only available for buoy stations.',
            }
        if self._is_spotter_buoy(station):
            payload = {
                'station': station,
                'period': self._window_label(period, start_date, end_date),
                'start_date': start_date,
                'end_date': end_date,
                'metrics': [],
                'available_metrics': [],
                'charts': [],
                'message': 'Spotter buoys report wave and surface telemetry; vertical profile charts are not available.',
            }
            self.cache.set(cache_key, payload, ttl_seconds=60)
            return payload

        label_map = {metric: self._metric_key_to_label(station, metric) for metric in self.BUOY_PROFILE_PARAMS}
        default_profile_metrics = [metric for metric in self.BUOY_DEFAULT_PROFILE_PARAMS if metric in label_map]
        selected = [metric for metric in (metrics or default_profile_metrics) if metric in label_map]
        self._ensure_time_index(self.settings.mongo_buoy_collection, 'datetime')
        query = self._base_query_for_station_window(station, period, 'datetime', start_date, end_date)
        query['depth'] = {'$elemMatch': {'$gt': 0}}
        projection = {'_id': 0, 'datetime': 1, 'depth': 1}
        for metric in selected:
            projection[metric] = 1

        docs = list(self.db[self.settings.mongo_buoy_collection].find(query, projection).sort('datetime', DESCENDING).limit(120))
        effective_period = self._window_label(period, start_date, end_date)
        if not docs:
            fallback_query = {'depth': {'$elemMatch': {'$gt': 0}}}
            docs = list(self.db[self.settings.mongo_buoy_collection].find(fallback_query, projection).sort('datetime', DESCENDING).limit(120))
            effective_period = 'Latest valid profiles'
        docs = list(reversed(docs))
        if len(docs) > 12:
            indexes = np.linspace(0, len(docs) - 1, 12).round().astype(int)
            docs = [docs[index] for index in sorted(set(indexes.tolist()))]

        charts: List[Dict[str, Any]] = []
        for metric in selected:
            profiles: List[Dict[str, Any]] = []
            for doc in docs:
                depths = self._numeric_list(doc.get('depth'))
                values = self._numeric_list(doc.get(metric))
                pairs = [
                    (depth, value)
                    for depth, value in zip(depths, values)
                    if depth is not None and depth > 0 and value is not None
                ]
                if not pairs:
                    continue
                timestamp = doc.get('datetime')
                profiles.append({
                    'timestamp': self._dt_string(timestamp),
                    'label': self._human_dt(timestamp),
                    'depth': [float(depth) for depth, _value in pairs],
                    'values': [float(value) for _depth, value in pairs],
                })
            if profiles:
                latest = profiles[-1]
                charts.append({
                    'metric': metric,
                    'label': label_map.get(metric, metric),
                    'unit': self._extract_unit(label_map.get(metric, metric)),
                    'profiles': profiles,
                    'latest_label': latest['label'],
                })

        payload = {
            'station': station,
            'period': self._window_label(period, start_date, end_date),
            'start_date': start_date,
            'end_date': end_date,
            'effective_period': effective_period,
            'metrics': [{'key': key, 'label': label_map[key]} for key in selected],
            'available_metrics': [{'key': key, 'label': label} for key, label in label_map.items()],
            'charts': charts,
            'message': None if charts else 'No profile data was available for the selected display period.',
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_timeseries(
        self,
        station_id: str,
        period: str = '24H',
        aggregation: str = '15m',
        metrics: Optional[List[str]] = None,
        split_sensors: bool = False,
        clean: bool = False,
        station: Optional[Dict[str, Any]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        display_points: Optional[int] = MAX_CHART_POINTS,
    ) -> Dict[str, Any]:
        station = station or self.get_station_summary(station_id)
        metrics = metrics or []
        period_label = self._window_label(period, start_date, end_date)
        cache_key = None
        if display_points is not None:
            metric_key = '|'.join(metrics)
            cache_key = f'timeseries:{station["station_id"]}:{period.upper()}:{start_date or ""}:{end_date or ""}:{aggregation.lower()}:{split_sensors}:{clean}:{metric_key}:{display_points}'
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        extra: Dict[str, Any] = {}
        if station['device_type'] == 'IoTBox':
            df, label_map = self._iot_dataframe(station, metrics, split_sensors, period, aggregation, start_date=start_date, end_date=end_date, display_points=display_points)
        elif station['device_type'] == 'Meteorological':
            df, label_map = self._meteo_dataframe(station, metrics, period, aggregation, start_date=start_date, end_date=end_date, display_points=display_points)
        elif station['device_type'] == 'Fidas_Palas':
            df, label_map = self._fidas_dataframe(station, metrics, period, aggregation, clean=clean, start_date=start_date, end_date=end_date, display_points=display_points)
        elif station['device_type'] == 'Buoy':
            df, label_map, profiles = self._buoy_dataframe(station, metrics, period, aggregation, start_date=start_date, end_date=end_date, display_points=display_points)
            extra['profiles'] = profiles
        elif station['device_type'] == 'underwater_probe':
            df, label_map = self._underwater_dataframe(station, metrics, period, aggregation, start_date=start_date, end_date=end_date, display_points=display_points)
        else:
            payload = {
                'station': station,
                'period': period_label,
                'start_date': start_date,
                'end_date': end_date,
                'aggregation': aggregation,
                'metrics': [],
                'available_metrics': self._metric_options(station, {}),
                'charts': [],
                'table': [],
                'events': [],
                'message': 'This station type is currently metadata-first in the Mongo adapter. Quick View and metadata remain available.',
            }
            if cache_key:
                self.cache.set(cache_key, payload, ttl_seconds=30)
            return payload

        if df.empty:
            message = 'No data was available for the selected time range.'
            if self._is_spotter_buoy(station):
                message = 'No Sofar Spotter buoy samples are currently loaded for this station.'
            payload = {
                'station': station,
                'period': period_label,
                'start_date': start_date,
                'end_date': end_date,
                'aggregation': aggregation,
                'clean': clean and station['device_type'] == 'Fidas_Palas',
                'metrics': [],
                'available_metrics': self._metric_options(station, label_map),
                'charts': [],
                'table': [],
                'events': [],
                'message': message,
                **extra,
            }
            if cache_key:
                self.cache.set(cache_key, payload, ttl_seconds=30)
            return payload

        metric_keys = [column for column in df.columns if column != 'timestamp' and not column.startswith('Lat') and not column.startswith('Long')]
        if not metric_keys:
            payload = {
                'station': station,
                'period': period_label,
                'start_date': start_date,
                'end_date': end_date,
                'aggregation': aggregation,
                'clean': clean and station['device_type'] == 'Fidas_Palas',
                'metrics': [],
                'available_metrics': self._metric_options(station, label_map),
                'charts': [],
                'table': [],
                'events': [],
                'message': 'No parameters are selected.',
                **extra,
            }
            if cache_key:
                self.cache.set(cache_key, payload, ttl_seconds=30)
            return payload
        charts = []
        events = self._detect_events(df, station, metric_keys)
        timestamps = [self._dt_string(value) for value in df['timestamp']]
        for metric in metric_keys:
            label = label_map.get(metric, self._metric_key_to_label(station, metric))
            canonical = self._label_to_canonical(label)
            numeric_series = pd.to_numeric(df[metric], errors='coerce')
            values = numeric_series.dropna()
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
                            'x': stamp,
                            'y': None if pd.isna(value) else float(value),
                        }
                        for stamp, value in zip(timestamps, numeric_series)
                    ],
                    'summary': {
                        'min': None if values.empty else round(float(values.min()), 2),
                        'max': None if values.empty else round(float(values.max()), 2),
                        'mean': None if values.empty else round(float(values.mean()), 2),
                        'latest': None if values.empty else round(float(values.iloc[-1]), 2),
                        'count': int(values.count()),
                    },
                }
            )
        payload = {
            'station': station,
            'period': period_label,
            'start_date': start_date,
            'end_date': end_date,
            'aggregation': aggregation,
            'clean': clean and station['device_type'] == 'Fidas_Palas',
            'metrics': [{'key': key, 'label': label_map.get(key, key)} for key in metric_keys],
            'available_metrics': self._metric_options(station, label_map),
            'charts': charts,
            'table': [],
            'events': events,
            'sampling': {
                'source_points': int(df.attrs.get('source_points', len(df))),
                'returned_points': int(df.attrs.get('returned_points', len(df))),
                'sampled': bool(df.attrs.get('sampled', False)),
                'display_cap': df.attrs.get('display_cap'),
            },
            **extra,
        }
        if cache_key:
            self.cache.set(cache_key, payload, ttl_seconds=30)
        return payload

    def _detect_events(self, df: pd.DataFrame, station: Dict[str, Any], metric_keys: List[str]) -> List[Dict[str, Any]]:
        return []

    # ------------------------------------------------------------------
    # SBN transect rollup API
    # ------------------------------------------------------------------
    def _sbn_waypoint_docs(self) -> List[Dict[str, Any]]:
        cache_key = 'sbn_waypoints'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        docs = list(
            self.db[self.settings.mongo_stations_info_collection].find(
                {'type': 'SBNTransect'},
                {'_id': 0, 'id': 1, 'name': 1, 'lat': 1, 'long': 1, 'status': 1, 'public': 1},
            )
        )
        waypoints: List[Dict[str, Any]] = []
        for doc in docs:
            canonical = self._sbn_canonical_waypoint(str(doc.get('id') or doc.get('name') or ''))
            label = self._sbn_public_waypoint(canonical)
            order = self._sbn_waypoint_order(canonical)
            if not canonical or not label or order is None:
                continue
            try:
                lat = float(doc.get('lat')) if doc.get('lat') is not None else None
                lon = float(doc.get('long')) if doc.get('long') is not None else None
            except Exception:
                lat = None
                lon = None
            waypoints.append(
                {
                    'id': label,
                    'label': label,
                    'name': doc.get('name') or f'SBN Transect Waypoint {order}',
                    'order': order,
                    'lat': lat,
                    'lon': lon,
                    'status': doc.get('status') or 'Active',
                    'privacy': 'Public' if doc.get('public', True) else 'Private',
                }
            )
        if not waypoints and self._collection_exists(self.SBN_COLLECTIONS['cells']):
            pipeline = [
                {'$group': {'_id': '$waypoint_id', 'order': {'$first': '$waypoint_order'}, 'lat': {'$first': '$lat'}, 'lon': {'$first': '$long'}}},
                {'$sort': {'order': ASCENDING}},
            ]
            for doc in self.db[self.SBN_COLLECTIONS['cells']].aggregate(pipeline):
                label = self._sbn_public_waypoint(doc.get('_id'))
                if not label:
                    continue
                waypoints.append(
                    {
                        'id': label,
                        'label': label,
                        'name': f'SBN Transect Waypoint {int(doc.get("order") or 0)}',
                        'order': int(doc.get('order') or self._sbn_waypoint_order(label) or 0),
                        'lat': doc.get('lat'),
                        'lon': doc.get('lon'),
                        'status': 'Active',
                        'privacy': 'Public',
                    }
                )
        waypoints.sort(key=lambda item: item['order'])
        self.cache.set(cache_key, waypoints, ttl_seconds=300)
        return waypoints

    def _sbn_available_metrics(self) -> List[Dict[str, Any]]:
        cache_key = 'sbn_available_metrics'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        if not self._collection_exists(self.SBN_COLLECTIONS['cells']):
            return []
        pipeline = [
            {'$match': {'depth_bin_m': {'$gte': 0}}},
            {'$project': {'pairs': {'$objectToArray': '$metrics'}}},
            {'$unwind': '$pairs'},
            {'$group': {'_id': '$pairs.k', 'cells': {'$sum': 1}, 'samples': {'$sum': {'$ifNull': ['$pairs.v.n', 0]}}}},
        ]
        metrics = []
        rank = {key: index for index, key in enumerate(self.SBN_METRIC_PRIORITY)}
        for doc in self.db[self.SBN_COLLECTIONS['cells']].aggregate(pipeline, allowDiskUse=True):
            key = doc.get('_id')
            if not key:
                continue
            metrics.append(
                {
                    'key': key,
                    'label': self._sbn_metric_label(key),
                    'unit': self._sbn_metric_unit(key),
                    'cells': int(doc.get('cells') or 0),
                    'samples': int(doc.get('samples') or 0),
                    'rank': rank.get(key, len(rank)),
                }
            )
        metrics.sort(key=lambda item: (item.pop('rank'), item['label'].lower(), item['key']))
        self.cache.set(cache_key, metrics, ttl_seconds=300)
        return metrics

    def _sbn_available_instruments(self) -> List[str]:
        cache_key = 'sbn_available_instruments_v2'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        seen = set(self.SBN_INSTRUMENT_ORDER)
        if self._collection_exists(self.SBN_COLLECTIONS['cells']):
            seen.update(
                str(value).lower()
                for value in self.db[self.SBN_COLLECTIONS['cells']].distinct('instrument', {'depth_bin_m': {'$gte': 0}})
                if value
            )
        if self._collection_exists(self.SBN_COLLECTIONS['profiles']):
            seen.update(
                str(value).lower()
                for value in self.db[self.SBN_COLLECTIONS['profiles']].distinct('instrument')
                if value
            )
        if self._collection_exists(self.SBN_COLLECTIONS['events']):
            for value in self.db[self.SBN_COLLECTIONS['events']].distinct('instruments'):
                if isinstance(value, list):
                    seen.update(str(item).lower() for item in value if item)
                elif value:
                    seen.add(str(value).lower())
        rank = {name: index for index, name in enumerate(self.SBN_INSTRUMENT_ORDER)}
        instruments = sorted(seen, key=lambda name: (rank.get(name, len(rank)), name))
        self.cache.set(cache_key, instruments, ttl_seconds=300)
        return instruments

    def _sbn_normalized_depth(self, value: Any) -> Optional[int]:
        try:
            depth = int(round(float(value)))
        except (TypeError, ValueError):
            return None
        return depth if depth >= 0 else None

    def _sbn_valid_depths(self, values: Iterable[Any]) -> List[int]:
        depths = sorted({
            depth
            for depth in (self._sbn_normalized_depth(value) for value in values)
            if depth is not None
        })
        return depths

    def _sbn_surface_depth(self, depths: List[int]) -> int:
        return min(depths) if depths else 0

    def _sbn_cell_query(self, campaign_month: Optional[str], depth_bin_m: Optional[int], metric: str) -> Dict[str, Any]:
        query: Dict[str, Any] = {f'metrics.{metric}.avg': {'$exists': True}}
        if campaign_month:
            query['campaign_month'] = campaign_month
        normalized_depth = self._sbn_normalized_depth(depth_bin_m)
        if depth_bin_m is None:
            query['depth_bin_m'] = {'$gte': 0}
        else:
            query['depth_bin_m'] = normalized_depth if normalized_depth is not None else 0
        return query

    def _sbn_format_cell(self, doc: Dict[str, Any], metric: str, instrument: str | None = None) -> Dict[str, Any]:
        stats = self._sbn_metric_stats_from_doc(doc, metric)
        label = self._sbn_public_waypoint(doc.get('waypoint_id')) or str(doc.get('waypoint_id') or '')
        return {
            'campaign_month': doc.get('campaign_month'),
            'waypoint_id': label,
            'waypoint_label': label,
            'waypoint_order': int(doc.get('waypoint_order') or self._sbn_waypoint_order(label) or 0),
            'instrument': instrument or doc.get('instrument'),
            'source_instruments': doc.get('source_instruments'),
            'depth_bin_m': doc.get('depth_bin_m'),
            'lat': doc.get('lat'),
            'lon': doc.get('long'),
            'metric': metric,
            'value': stats.get('avg') if stats else None,
            'stats': stats,
            'metrics': {metric: stats} if stats else {},
        }

    def _sbn_missing_cell(self, waypoint: Dict[str, Any], campaign_month: Optional[str], instrument: str, depth_bin_m: Optional[int], metric: str) -> Dict[str, Any]:
        return {
            'campaign_month': campaign_month,
            'waypoint_id': waypoint['id'],
            'waypoint_label': waypoint['label'],
            'waypoint_order': waypoint['order'],
            'instrument': instrument,
            'source_instruments': [],
            'depth_bin_m': depth_bin_m,
            'lat': waypoint.get('lat'),
            'lon': waypoint.get('lon'),
            'metric': metric,
            'value': None,
            'stats': None,
            'metrics': {},
        }

    def _sbn_combine_docs(self, docs: List[Dict[str, Any]], metric: str, group_key: str) -> List[Dict[str, Any]]:
        grouped: Dict[Any, List[Dict[str, Any]]] = {}
        for doc in docs:
            grouped.setdefault(doc.get(group_key), []).append(doc)
        combined = []
        for key, group in grouped.items():
            doc = self._sbn_combined_doc(group, metric)
            if doc:
                combined.append(doc)
        return combined

    def _sbn_weighted_metric_stats(self, docs: List[Dict[str, Any]], metric: str) -> Optional[Dict[str, Any]]:
        weighted_sum = 0.0
        weight_total = 0
        sample_total = 0
        mins = []
        maxes = []
        for doc in docs:
            stats = self._sbn_metric_stats_from_doc(doc, metric)
            if not stats or not self._is_numeric_scalar(stats.get('avg')):
                continue
            n = max(0, int(stats.get('n') or 0))
            weight = max(1, n)
            weighted_sum += float(stats['avg']) * weight
            weight_total += weight
            sample_total += weight
            if self._is_numeric_scalar(stats.get('min')):
                mins.append(float(stats['min']))
            if self._is_numeric_scalar(stats.get('max')):
                maxes.append(float(stats['max']))
        if not weight_total:
            return None
        return {
            'avg': weighted_sum / weight_total,
            'min': min(mins) if mins else None,
            'max': max(maxes) if maxes else None,
            'n': sample_total,
        }

    def _sbn_combined_doc(self, docs: List[Dict[str, Any]], metric: str) -> Optional[Dict[str, Any]]:
        if not docs:
            return None
        stats = self._sbn_weighted_metric_stats(docs, metric)
        if not stats:
            return None
        base = dict(docs[0])
        base['instrument'] = 'combined'
        base['source_instruments'] = sorted({str(doc.get('instrument')) for doc in docs if doc.get('instrument')})
        base['metrics'] = {metric: stats}
        return base

    def get_sbn_options(self) -> Dict[str, Any]:
        cache_key = 'sbn_options_v3'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        events = []
        if self._collection_exists(self.SBN_COLLECTIONS['events']):
            events = list(
                self.db[self.SBN_COLLECTIONS['events']].find(
                    {},
                    {'_id': 0, 'campaign_id': 1, 'campaign_month': 1, 'transect_date': 1, 'status': 1, 'profile_count': 1, 'instruments': 1, 'complete_instruments': 1},
                ).sort('campaign_month', ASCENDING)
            )
        cell_months: List[str] = []
        if self._collection_exists(self.SBN_COLLECTIONS['cells']):
            cell_months = sorted(
                value
                for value in self.db[self.SBN_COLLECTIONS['cells']].distinct('campaign_month', {'depth_bin_m': {'$gte': 0}})
                if value
            )
        months = cell_months or [event['campaign_month'] for event in events if event.get('campaign_month')]
        instruments = self._sbn_available_instruments()
        months_by_instrument: Dict[str, List[str]] = {instrument: [] for instrument in instruments}
        if self._collection_exists(self.SBN_COLLECTIONS['cells']):
            for doc in self.db[self.SBN_COLLECTIONS['cells']].aggregate([
                {'$match': {'depth_bin_m': {'$gte': 0}}},
                {'$group': {'_id': '$instrument', 'months': {'$addToSet': '$campaign_month'}}},
            ]):
                if doc.get('_id'):
                    months_by_instrument[str(doc['_id']).lower()] = sorted(month for month in doc.get('months', []) if month)
        depths = self._sbn_valid_depths(
            self.db[self.SBN_COLLECTIONS['cells']].distinct('depth_bin_m') if self._collection_exists(self.SBN_COLLECTIONS['cells']) else []
        )
        payload = {
            'months': months,
            'events': [
                {
                    **event,
                    'transect_date': self._dt_string(event.get('transect_date')) if event.get('transect_date') else None,
                }
                for event in events
            ],
            'instruments': instruments,
            'months_by_instrument': months_by_instrument,
            'waypoints': self._sbn_waypoint_docs(),
            'depths': depths,
            'metrics': self._sbn_available_metrics(),
        }
        self.cache.set(cache_key, payload, ttl_seconds=300)
        return payload

    def _sbn_instrument_query(self, instrument: str) -> Dict[str, Any]:
        return {} if instrument == 'combined' else {'instrument': instrument}

    def _sbn_order_metric_docs(self, metric_keys: Iterable[str]) -> List[Dict[str, Any]]:
        available = {item['key']: item for item in self._sbn_available_metrics()}
        rank = {key: index for index, key in enumerate(self.SBN_METRIC_PRIORITY)}
        ordered = sorted(
            [key for key in metric_keys if key],
            key=lambda key: (rank.get(key, len(rank)), self._sbn_metric_label(key).lower(), key),
        )
        return [
            {
                'key': key,
                'label': available.get(key, {}).get('label') or self._sbn_metric_label(key),
                'unit': available.get(key, {}).get('unit') or self._sbn_metric_unit(key),
            }
            for key in ordered
        ]

    def _sbn_distinct_months(self, instrument: str) -> List[str]:
        query = {'depth_bin_m': {'$gte': 0}, **self._sbn_instrument_query(instrument)}
        return sorted(month for month in self.db[self.SBN_COLLECTIONS['cells']].distinct('campaign_month', query) if month)

    def _sbn_distinct_metrics(self, instrument: str, campaign_month: str) -> List[str]:
        query = {'campaign_month': campaign_month, 'depth_bin_m': {'$gte': 0}, **self._sbn_instrument_query(instrument)}
        cache_key = f'sbn_metric_keys:{instrument}:{campaign_month}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        pipeline = [
            {'$match': query},
            {'$project': {'pairs': {'$objectToArray': '$metrics'}}},
            {'$unwind': '$pairs'},
            {'$group': {'_id': '$pairs.k'}},
        ]
        metrics = [doc['_id'] for doc in self.db[self.SBN_COLLECTIONS['cells']].aggregate(pipeline, allowDiskUse=True) if doc.get('_id')]
        ordered = [item['key'] for item in self._sbn_order_metric_docs(metrics)]
        self.cache.set(cache_key, ordered, ttl_seconds=180)
        return ordered

    def _sbn_distinct_depths(self, instrument: str, campaign_month: str, metric: str) -> List[int]:
        query = {
            'campaign_month': campaign_month,
            'depth_bin_m': {'$gte': 0},
            f'metrics.{metric}.avg': {'$exists': True},
            **self._sbn_instrument_query(instrument),
        }
        return self._sbn_valid_depths(self.db[self.SBN_COLLECTIONS['cells']].distinct('depth_bin_m', query))

    def _sbn_closest_depth(self, requested: int, depths: List[int]) -> int:
        if not depths:
            return int(requested or 0)
        return min(depths, key=lambda depth: (abs(depth - int(requested or 0)), depth))

    def get_sbn_selection(
        self,
        instrument: str = 'combined',
        campaign_month: Optional[str] = None,
        metric: Optional[str] = None,
        depth_bin_m: int = 0,
    ) -> Dict[str, Any]:
        valid_instruments = ['combined'] + self.get_sbn_options().get('instruments', [])
        if instrument not in valid_instruments:
            instrument = 'combined'

        months = self._sbn_distinct_months(instrument)
        if not months and instrument != 'combined':
            all_options = self.get_sbn_options()
            all_months = all_options.get('months', [])
            if campaign_month not in all_months:
                campaign_month = all_months[-1] if all_months else campaign_month
            return {
                'instrument': instrument,
                'campaign_month': campaign_month,
                'metric': metric,
                'depth_bin_m': int(depth_bin_m or 0),
                'months': all_months,
                'metrics': all_options.get('metrics', []),
                'depths': all_options.get('depths', []),
                'compare_months': [],
                'has_data': False,
            }
        if not months:
            return {
                'instrument': instrument,
                'campaign_month': campaign_month,
                'metric': metric,
                'depth_bin_m': int(depth_bin_m or 0),
                'months': [],
                'metrics': [],
                'depths': [],
                'compare_months': [],
                'has_data': False,
            }

        if campaign_month not in months:
            campaign_month = months[-1]

        metric_keys = self._sbn_distinct_metrics(instrument, campaign_month)
        if not metric_keys and instrument != 'combined':
            instrument = 'combined'
            months = self._sbn_distinct_months(instrument)
            campaign_month = campaign_month if campaign_month in months else months[-1]
            metric_keys = self._sbn_distinct_metrics(instrument, campaign_month)
        if metric not in metric_keys:
            preferred = [key for key in self.SBN_METRIC_PRIORITY if key in metric_keys]
            metric = (preferred or metric_keys or [metric or ''])[0]

        depths = self._sbn_distinct_depths(instrument, campaign_month, metric)
        if not depths and metric_keys:
            # Some instruments/months have sparse parameter coverage. Pick the first
            # metric with depth cells so controls cannot land on an empty dashboard.
            for candidate in metric_keys:
                candidate_depths = self._sbn_distinct_depths(instrument, campaign_month, candidate)
                if candidate_depths:
                    metric = candidate
                    depths = candidate_depths
                    break
        requested_depth = self._sbn_normalized_depth(depth_bin_m)
        resolved_depth = self._sbn_closest_depth(requested_depth if requested_depth is not None else self._sbn_surface_depth(depths), depths)
        compare_months = sorted(
            month
            for month in self.db[self.SBN_COLLECTIONS['cells']].distinct(
                'campaign_month',
                {
                    f'metrics.{metric}.avg': {'$exists': True},
                    'depth_bin_m': resolved_depth,
                    **self._sbn_instrument_query(instrument),
                },
            )
            if month
        )
        payload = {
            'instrument': instrument,
            'campaign_month': campaign_month,
            'metric': metric,
            'depth_bin_m': resolved_depth,
            'months': months,
            'metrics': self._sbn_order_metric_docs(metric_keys),
            'depths': depths,
            'compare_months': compare_months,
            'has_data': bool(depths and metric),
        }
        return payload

    def get_sbn_cells(
        self,
        campaign_month: str,
        instrument: str,
        depth_bin_m: int,
        metric: str,
        include_missing: bool = True,
    ) -> Dict[str, Any]:
        cache_key = f'sbn_cells:{campaign_month}:{instrument}:{depth_bin_m}:{metric}:{include_missing}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        depth_bin_m = self._sbn_normalized_depth(depth_bin_m)
        if depth_bin_m is None:
            depth_bin_m = 0
        collection = self.db[self.SBN_COLLECTIONS['cells']]
        query = self._sbn_cell_query(campaign_month, depth_bin_m, metric)
        projection = {
            '_id': 0,
            'campaign_month': 1,
            'waypoint_id': 1,
            'waypoint_order': 1,
            'instrument': 1,
            'depth_bin_m': 1,
            'lat': 1,
            'long': 1,
            f'metrics.{metric}': 1,
        }
        if instrument != 'combined':
            query['instrument'] = instrument
        docs = list(collection.find(query, projection).sort([('waypoint_order', ASCENDING), ('instrument', ASCENDING)]))
        if instrument == 'combined':
            docs = self._sbn_combine_docs(docs, metric, 'waypoint_id')
        rows_by_label = {self._sbn_public_waypoint(doc.get('waypoint_id')): self._sbn_format_cell(doc, metric, instrument) for doc in docs}
        if include_missing:
            rows = [rows_by_label.get(waypoint['label']) or self._sbn_missing_cell(waypoint, campaign_month, instrument, depth_bin_m, metric) for waypoint in self._sbn_waypoint_docs()]
        else:
            rows = sorted(rows_by_label.values(), key=lambda item: item['waypoint_order'])
        payload = {
            'campaign_month': campaign_month,
            'instrument': instrument,
            'depth_bin_m': depth_bin_m,
            'metric': {'key': metric, 'label': self._sbn_metric_label(metric), 'unit': self._sbn_metric_unit(metric)},
            'data': rows,
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_sbn_trend(self, waypoint_id: str, instrument: str, depth_bin_m: int, metric: str) -> Dict[str, Any]:
        depth_bin_m = self._sbn_normalized_depth(depth_bin_m)
        if depth_bin_m is None:
            depth_bin_m = 0
        canonical = self._sbn_canonical_waypoint(waypoint_id)
        if not canonical:
            raise KeyError('Waypoint not found.')
        cache_key = f'sbn_trend:{canonical}:{instrument}:{depth_bin_m}:{metric}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        query = self._sbn_cell_query(None, depth_bin_m, metric)
        query['waypoint_id'] = canonical
        if instrument != 'combined':
            query['instrument'] = instrument
        projection = {'_id': 0, 'campaign_month': 1, 'waypoint_id': 1, 'waypoint_order': 1, 'instrument': 1, 'depth_bin_m': 1, f'metrics.{metric}': 1}
        docs = list(self.db[self.SBN_COLLECTIONS['cells']].find(query, projection).sort([('campaign_month', ASCENDING), ('instrument', ASCENDING)]))
        if instrument == 'combined':
            docs = self._sbn_combine_docs(docs, metric, 'campaign_month')
        rows = [self._sbn_format_cell(doc, metric, instrument) for doc in sorted(docs, key=lambda item: item.get('campaign_month') or '')]
        payload = {
            'waypoint_id': self._sbn_public_waypoint(canonical),
            'instrument': instrument,
            'depth_bin_m': depth_bin_m,
            'metric': {'key': metric, 'label': self._sbn_metric_label(metric), 'unit': self._sbn_metric_unit(metric)},
            'data': rows,
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_sbn_depth_waypoint_heatmap(self, campaign_month: str, instrument: str, metric: str) -> Dict[str, Any]:
        cache_key = f'sbn_depth_waypoint_heatmap:{campaign_month}:{instrument}:{metric}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        query = self._sbn_cell_query(campaign_month, None, metric)
        if instrument != 'combined':
            query['instrument'] = instrument
        projection = {'_id': 0, 'campaign_month': 1, 'waypoint_id': 1, 'waypoint_order': 1, 'instrument': 1, 'depth_bin_m': 1, f'metrics.{metric}': 1}
        docs = list(self.db[self.SBN_COLLECTIONS['cells']].find(query, projection))
        if instrument == 'combined':
            pair_groups: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
            for doc in docs:
                depth = self._sbn_normalized_depth(doc.get('depth_bin_m'))
                if depth is not None:
                    pair_groups.setdefault((doc.get('waypoint_id'), depth), []).append(doc)
            docs = []
            for group in pair_groups.values():
                combined_doc = self._sbn_combined_doc(group, metric)
                if combined_doc:
                    docs.append(combined_doc)
        depths = self._sbn_valid_depths(doc.get('depth_bin_m') for doc in docs)
        waypoints = self._sbn_waypoint_docs()
        values: Dict[Tuple[str, int], float] = {}
        for doc in docs:
            label = self._sbn_public_waypoint(doc.get('waypoint_id'))
            stats = self._sbn_metric_stats_from_doc(doc, metric)
            if label and stats:
                depth = self._sbn_normalized_depth(doc.get('depth_bin_m'))
                if depth is not None:
                    values[(label, depth)] = stats['avg']
        z = [[values.get((waypoint['label'], depth)) for waypoint in waypoints] for depth in depths]
        payload = {
            'campaign_month': campaign_month,
            'instrument': instrument,
            'metric': {'key': metric, 'label': self._sbn_metric_label(metric), 'unit': self._sbn_metric_unit(metric)},
            'x': [waypoint['label'] for waypoint in waypoints],
            'y': depths,
            'z': z,
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_sbn_month_depth_heatmap(self, waypoint_id: str, instrument: str, metric: str) -> Dict[str, Any]:
        canonical = self._sbn_canonical_waypoint(waypoint_id)
        if not canonical:
            raise KeyError('Waypoint not found.')
        cache_key = f'sbn_month_depth_heatmap:{canonical}:{instrument}:{metric}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        query = self._sbn_cell_query(None, None, metric)
        query['waypoint_id'] = canonical
        if instrument != 'combined':
            query['instrument'] = instrument
        projection = {'_id': 0, 'campaign_month': 1, 'waypoint_id': 1, 'instrument': 1, 'depth_bin_m': 1, f'metrics.{metric}': 1}
        raw_docs = list(self.db[self.SBN_COLLECTIONS['cells']].find(query, projection))
        if instrument == 'combined':
            pair_groups: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
            for doc in raw_docs:
                depth = self._sbn_normalized_depth(doc.get('depth_bin_m'))
                if depth is not None:
                    pair_groups.setdefault((doc.get('campaign_month'), depth), []).append(doc)
            docs = []
            for group in pair_groups.values():
                combined_doc = self._sbn_combined_doc(group, metric)
                if combined_doc:
                    docs.append(combined_doc)
        else:
            docs = raw_docs
        months = sorted({doc.get('campaign_month') for doc in docs if doc.get('campaign_month')})
        depths = self._sbn_valid_depths(doc.get('depth_bin_m') for doc in docs)
        values: Dict[Tuple[str, int], float] = {}
        for doc in docs:
            stats = self._sbn_metric_stats_from_doc(doc, metric)
            if stats:
                depth = self._sbn_normalized_depth(doc.get('depth_bin_m'))
                if depth is not None:
                    values[(doc.get('campaign_month'), depth)] = stats['avg']
        z = [[values.get((month, depth)) for month in months] for depth in depths]
        payload = {
            'waypoint_id': self._sbn_public_waypoint(canonical),
            'instrument': instrument,
            'metric': {'key': metric, 'label': self._sbn_metric_label(metric), 'unit': self._sbn_metric_unit(metric)},
            'x': months,
            'y': depths,
            'z': z,
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_sbn_month_waypoint_heatmap(self, instrument: str, depth_bin_m: int, metric: str) -> Dict[str, Any]:
        depth_bin_m = self._sbn_normalized_depth(depth_bin_m)
        if depth_bin_m is None:
            depth_bin_m = 0
        cache_key = f'sbn_month_waypoint_heatmap:{instrument}:{depth_bin_m}:{metric}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        query = self._sbn_cell_query(None, depth_bin_m, metric)
        if instrument != 'combined':
            query['instrument'] = instrument
        projection = {'_id': 0, 'campaign_month': 1, 'waypoint_id': 1, 'waypoint_order': 1, 'instrument': 1, 'depth_bin_m': 1, f'metrics.{metric}': 1}
        docs = list(self.db[self.SBN_COLLECTIONS['cells']].find(query, projection))
        if instrument == 'combined':
            pair_groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
            for doc in docs:
                pair_groups.setdefault((doc.get('campaign_month'), doc.get('waypoint_id')), []).append(doc)
            docs = []
            for group in pair_groups.values():
                combined_doc = self._sbn_combined_doc(group, metric)
                if combined_doc:
                    docs.append(combined_doc)
        months = sorted({doc.get('campaign_month') for doc in docs if doc.get('campaign_month')})
        waypoints = self._sbn_waypoint_docs()
        values: Dict[Tuple[str, str], float] = {}
        for doc in docs:
            label = self._sbn_public_waypoint(doc.get('waypoint_id'))
            stats = self._sbn_metric_stats_from_doc(doc, metric)
            if label and stats:
                values[(label, doc.get('campaign_month'))] = stats['avg']
        z = [[values.get((waypoint['label'], month)) for month in months] for waypoint in waypoints]
        payload = {
            'instrument': instrument,
            'depth_bin_m': depth_bin_m,
            'metric': {'key': metric, 'label': self._sbn_metric_label(metric), 'unit': self._sbn_metric_unit(metric)},
            'x': months,
            'y': [waypoint['label'] for waypoint in waypoints],
            'z': z,
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_sbn_crossplot(self, campaign_month: str, instrument: str, depth_bin_m: int, x_metric: str, y_metric: str) -> Dict[str, Any]:
        depth_bin_m = self._sbn_normalized_depth(depth_bin_m)
        if depth_bin_m is None:
            depth_bin_m = 0
        cache_key = f'sbn_crossplot:{campaign_month}:{instrument}:{depth_bin_m}:{x_metric}:{y_metric}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        query: Dict[str, Any] = {
            'campaign_month': campaign_month,
            'depth_bin_m': depth_bin_m,
            f'metrics.{x_metric}.avg': {'$exists': True},
            f'metrics.{y_metric}.avg': {'$exists': True},
        }
        if instrument != 'combined':
            query['instrument'] = instrument
        projection = {'_id': 0, 'campaign_month': 1, 'waypoint_id': 1, 'waypoint_order': 1, 'instrument': 1, 'depth_bin_m': 1, f'metrics.{x_metric}': 1, f'metrics.{y_metric}': 1}
        docs = list(self.db[self.SBN_COLLECTIONS['cells']].find(query, projection).sort([('waypoint_order', ASCENDING), ('instrument', ASCENDING)]))
        if instrument == 'combined':
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for doc in docs:
                grouped.setdefault(doc.get('waypoint_id'), []).append(doc)
            rows = []
            for waypoint, group in grouped.items():
                x_stats = self._sbn_weighted_metric_stats(group, x_metric)
                y_stats = self._sbn_weighted_metric_stats(group, y_metric)
                if not x_stats or not y_stats:
                    continue
                rows.append(
                    {
                        'waypoint_id': self._sbn_public_waypoint(waypoint),
                        'waypoint_order': int(group[0].get('waypoint_order') or 0),
                        'instrument': 'combined',
                        'x': x_stats['avg'],
                        'y': y_stats['avg'],
                    }
                )
        else:
            rows = []
            for doc in docs:
                x_stats = self._sbn_metric_stats_from_doc(doc, x_metric)
                y_stats = self._sbn_metric_stats_from_doc(doc, y_metric)
                if x_stats and y_stats:
                    rows.append(
                        {
                            'waypoint_id': self._sbn_public_waypoint(doc.get('waypoint_id')),
                            'waypoint_order': int(doc.get('waypoint_order') or 0),
                            'instrument': doc.get('instrument'),
                            'x': x_stats['avg'],
                            'y': y_stats['avg'],
                        }
                    )
        rows.sort(key=lambda item: item['waypoint_order'])
        payload = {
            'campaign_month': campaign_month,
            'instrument': instrument,
            'depth_bin_m': depth_bin_m,
            'x_metric': {'key': x_metric, 'label': self._sbn_metric_label(x_metric), 'unit': self._sbn_metric_unit(x_metric)},
            'y_metric': {'key': y_metric, 'label': self._sbn_metric_label(y_metric), 'unit': self._sbn_metric_unit(y_metric)},
            'data': rows,
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_sbn_availability(self, instrument: str, depth_bin_m: int, metric: str) -> Dict[str, Any]:
        depth_bin_m = self._sbn_normalized_depth(depth_bin_m)
        if depth_bin_m is None:
            depth_bin_m = 0
        cache_key = f'sbn_availability:{instrument}:{depth_bin_m}:{metric}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        query = self._sbn_cell_query(None, depth_bin_m, metric)
        if instrument != 'combined':
            query['instrument'] = instrument
        projection = {'_id': 0, 'campaign_month': 1, 'waypoint_id': 1, 'instrument': 1, f'metrics.{metric}': 1}
        docs = list(self.db[self.SBN_COLLECTIONS['cells']].find(query, projection))
        months = sorted({doc.get('campaign_month') for doc in docs if doc.get('campaign_month')})
        waypoints = self._sbn_waypoint_docs()
        if instrument == 'combined':
            event_instruments = {event.get('campaign_month'): event.get('instruments') or [] for event in self.get_sbn_options().get('events', [])}
            buckets: Dict[Tuple[str, str], set[str]] = {}
            for doc in docs:
                label = self._sbn_public_waypoint(doc.get('waypoint_id'))
                if label:
                    buckets.setdefault((label, doc.get('campaign_month')), set()).add(doc.get('instrument'))
            z = []
            for waypoint in waypoints:
                row = []
                for month in months:
                    expected = max(1, len(event_instruments.get(month) or []))
                    row.append(round(len(buckets.get((waypoint['label'], month), set())) / expected * 100, 1))
                z.append(row)
        else:
            present = {(self._sbn_public_waypoint(doc.get('waypoint_id')), doc.get('campaign_month')) for doc in docs}
            z = [[100 if (waypoint['label'], month) in present else 0 for month in months] for waypoint in waypoints]
        payload = {
            'instrument': instrument,
            'depth_bin_m': depth_bin_m,
            'metric': {'key': metric, 'label': self._sbn_metric_label(metric), 'unit': self._sbn_metric_unit(metric)},
            'x': months,
            'y': [waypoint['label'] for waypoint in waypoints],
            'z': z,
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_sbn_profiles(self, campaign_month: Optional[str] = None, instrument: Optional[str] = None, waypoint_id: Optional[str] = None) -> Dict[str, Any]:
        cache_key = f'sbn_profiles:{campaign_month or ""}:{instrument or ""}:{waypoint_id or ""}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        query: Dict[str, Any] = {}
        if campaign_month:
            query['campaign_month'] = campaign_month
        if instrument and instrument != 'combined':
            query['instrument'] = instrument
        canonical = self._sbn_canonical_waypoint(waypoint_id) if waypoint_id else None
        if canonical:
            query['waypoint_id'] = canonical
        cursor = self.db[self.SBN_COLLECTIONS['profiles']].find(
            query,
            {
                '_id': 0,
                'campaign_month': 1,
                'waypoint_id': 1,
                'waypoint_order': 1,
                'instrument': 1,
                'row_count': 1,
                'duplicate_rows': 1,
                'depth_min_m': 1,
                'depth_max_m': 1,
                'ts_min': 1,
                'ts_max': 1,
                'fields': 1,
                'status': 1,
            },
        ).sort([('campaign_month', ASCENDING), ('waypoint_order', ASCENDING), ('instrument', ASCENDING)])
        rows = []
        for doc in cursor.limit(1000):
            rows.append(
                {
                    **doc,
                    'waypoint_id': self._sbn_public_waypoint(doc.get('waypoint_id')),
                    'ts_min': self._dt_string(doc.get('ts_min')) if doc.get('ts_min') else None,
                    'ts_max': self._dt_string(doc.get('ts_max')) if doc.get('ts_max') else None,
                }
            )
        payload = {'data': rows}
        self.cache.set(cache_key, payload, ttl_seconds=120)
        return payload

    def export_sbn_csv_iter(
        self,
        campaign_month: Optional[str] = None,
        instrument: str = 'combined',
        depth_bin_m: Optional[int] = None,
        metrics: Optional[List[str]] = None,
        all_depths: bool = False,
        append_location: bool = False,
    ) -> Iterable[str]:
        metric_keys = [metric for metric in (metrics or []) if metric]
        if not metric_keys:
            metric_keys = [item['key'] for item in self._sbn_available_metrics()]
        metric_keys = [metric for metric in metric_keys if metric]
        header = [
            'campaign_month',
            'instrument',
            'source_instruments',
            'waypoint',
            'waypoint_order',
            'depth_bin_m',
            'metric',
            'metric_label',
            'unit',
            'avg',
            'min',
            'max',
            'n',
        ]
        if append_location:
            header.extend(['latitude', 'longitude'])
        if not metric_keys or not self._collection_exists(self.SBN_COLLECTIONS['cells']):
            return self._csv_chunk_writer([header])

        query: Dict[str, Any] = {}
        if campaign_month and str(campaign_month).lower() != 'all':
            query['campaign_month'] = campaign_month
        if not all_depths:
            normalized_depth = self._sbn_normalized_depth(depth_bin_m)
            query['depth_bin_m'] = normalized_depth if normalized_depth is not None else 0
        else:
            query['depth_bin_m'] = {'$gte': 0}
        if instrument != 'combined':
            query['instrument'] = instrument
        query['$or'] = [{f'metrics.{metric}.avg': {'$exists': True}} for metric in metric_keys]

        projection: Dict[str, int] = {
            '_id': 0,
            'campaign_month': 1,
            'waypoint_id': 1,
            'waypoint_order': 1,
            'instrument': 1,
            'depth_bin_m': 1,
            'lat': 1,
            'long': 1,
        }
        for metric in metric_keys:
            projection[f'metrics.{metric}'] = 1

        docs = list(
            self.db[self.SBN_COLLECTIONS['cells']]
            .find(query, projection)
            .sort([('campaign_month', ASCENDING), ('waypoint_order', ASCENDING), ('depth_bin_m', ASCENDING), ('instrument', ASCENDING)])
            .batch_size(5000)
        )

        def row_for_doc(doc: Dict[str, Any], metric: str, stats: Dict[str, Any], export_instrument: str) -> List[Any]:
            source_instruments = doc.get('source_instruments') or ([doc.get('instrument')] if doc.get('instrument') else [])
            row: List[Any] = [
                doc.get('campaign_month'),
                export_instrument,
                ';'.join(str(item) for item in source_instruments if item),
                self._sbn_public_waypoint(doc.get('waypoint_id')) or doc.get('waypoint_id'),
                int(doc.get('waypoint_order') or self._sbn_waypoint_order(doc.get('waypoint_id')) or 0),
                doc.get('depth_bin_m'),
                metric,
                self._sbn_metric_label(metric),
                self._sbn_metric_unit(metric),
                stats.get('avg'),
                stats.get('min'),
                stats.get('max'),
                stats.get('n'),
            ]
            if append_location:
                row.extend([doc.get('lat'), doc.get('long')])
            return row

        def rows() -> Iterable[List[Any]]:
            yield header
            if instrument == 'combined':
                grouped: Dict[Tuple[Any, Any, Any], List[Dict[str, Any]]] = {}
                for doc in docs:
                    grouped.setdefault((doc.get('campaign_month'), doc.get('waypoint_id'), doc.get('depth_bin_m')), []).append(doc)
                for key in sorted(grouped.keys(), key=lambda item: (item[0] or '', int(self._sbn_waypoint_order(item[1]) or 0), int(item[2] or 0))):
                    group = grouped[key]
                    for metric in metric_keys:
                        combined_doc = self._sbn_combined_doc(group, metric)
                        if not combined_doc:
                            continue
                        stats = self._sbn_metric_stats_from_doc(combined_doc, metric)
                        if stats:
                            yield row_for_doc(combined_doc, metric, stats, 'combined')
                return
            for doc in docs:
                for metric in metric_keys:
                    stats = self._sbn_metric_stats_from_doc(doc, metric)
                    if stats:
                        yield row_for_doc(doc, metric, stats, str(doc.get('instrument') or instrument))

        return self._csv_chunk_writer(rows())

    # ------------------------------------------------------------------
    # Jaywun cruise rollup API
    # ------------------------------------------------------------------
    def _jw_cells_ready(self) -> bool:
        cache_key = 'jw_cells_ready'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return bool(cached)
        ready = False
        if self._collection_exists(self.JW_COLLECTIONS['cells']):
            try:
                ready = self.db[self.JW_COLLECTIONS['cells']].count_documents({}, limit=1) > 0
            except Exception:
                ready = False
        self.cache.set(cache_key, ready, ttl_seconds=300)
        return ready

    def _jw_waypoint_order(self, value: str | None) -> Optional[int]:
        if not value:
            return None
        text = str(value)
        match = re.search(r'(?:JW[_\s-]*)?NYU[_\s-]?(\d{1,2})', text, flags=re.IGNORECASE)
        if not match:
            match = re.search(r'waypoint[_\s-]*(\d{1,2})', text, flags=re.IGNORECASE)
        if not match:
            return None
        order = int(match.group(1))
        return order if 1 <= order <= 99 else None

    def _jw_canonical_waypoint(self, value: str | None) -> Optional[str]:
        order = self._jw_waypoint_order(value)
        if order is None:
            return None
        return f'JW_NYU_{order:02d}'

    def _jw_public_waypoint(self, value: str | None) -> Optional[str]:
        order = self._jw_waypoint_order(value)
        if order is None:
            return None
        return f'NYU-{order:02d}'

    def _jw_metric_label(self, metric: str) -> str:
        return self.JW_METRIC_LABELS.get(metric, self._sbn_metric_label(metric))

    def _jw_metric_unit(self, metric: str) -> str:
        return self.JW_METRIC_UNITS.get(metric, self._sbn_metric_unit(metric))

    def _jw_source_metric_fields(self, metric: str) -> List[str]:
        aliases = {
            'do_mg_l': ['do_mg_l', 'sbeox0mg_per_l', 'sbeox0mg_l'],
            'density': ['density', 'density00'],
            'salinity_psu': ['salinity_psu', 'sal00'],
            'temp_c': ['temp_c', 't090c'],
            'pressure_dbar': ['pressure_dbar', 'prdm'],
            'oxygen_ml_l': ['oxygen_ml_l', 'sbeox0ml_l'],
            'par': ['par', 'par_per_sat_per_log'],
        }
        return aliases.get(metric, [metric])

    def _jw_depth_value_expr(self) -> Any:
        return {'$ifNull': ['$depth_m', {'$ifNull': ['$depsm', '$prdm']}]}

    def _jw_depth_match_clause(self, depth_bin_m: Optional[int] = None) -> Dict[str, Any]:
        fields = ['depth_m', 'depsm', 'prdm']
        if depth_bin_m is None:
            clauses = [{field: {'$gte': 0, '$lte': 250}} for field in fields]
        else:
            depth = self._sbn_normalized_depth(depth_bin_m)
            depth = depth if depth is not None else 0
            clauses = [{field: {'$gte': depth - 0.5, '$lt': depth + 0.5}} for field in fields]
        return {'$or': clauses}

    def _jw_valid_depths(self, values: Iterable[Any]) -> List[int]:
        return [
            depth
            for depth in self._sbn_valid_depths(values)
            if 0 <= depth <= 250
        ]

    def _jw_metric_value_expr(self, metric: str) -> Any:
        fields = self._jw_source_metric_fields(metric)
        if len(fields) == 1:
            return f'${fields[0]}'
        expr: Any = f'${fields[-1]}'
        for field in reversed(fields[:-1]):
            expr = {'$ifNull': [f'${field}', expr]}
        return expr

    def _jw_metric_match_clause(self, metric: str) -> Dict[str, Any]:
        fields = self._jw_source_metric_fields(metric)
        clauses = [{field: {'$type': 'number'}} for field in fields]
        return clauses[0] if len(clauses) == 1 else {'$or': clauses}

    def _jw_add_metric_match(self, match: Dict[str, Any], metric: str) -> None:
        clause = self._jw_metric_match_clause(metric)
        if '$or' in clause:
            match.setdefault('$and', []).append(clause)
        else:
            match.update(clause)

    def _jw_waypoint_docs(self) -> List[Dict[str, Any]]:
        cache_key = 'jw_waypoints'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        docs = list(
            self.db[self.settings.mongo_stations_info_collection].find(
                {'type': 'JWCruise'},
                {'_id': 0, 'id': 1, 'name': 1, 'lat': 1, 'long': 1, 'status': 1, 'public': 1},
            )
        )
        waypoints: List[Dict[str, Any]] = []
        for doc in docs:
            canonical = self._jw_canonical_waypoint(str(doc.get('id') or doc.get('name') or ''))
            label = self._jw_public_waypoint(canonical)
            order = self._jw_waypoint_order(canonical)
            if not canonical or not label or order is None:
                continue
            try:
                lat = float(doc.get('lat')) if doc.get('lat') is not None else None
                lon = float(doc.get('long')) if doc.get('long') is not None else None
            except Exception:
                lat = None
                lon = None
            waypoints.append(
                {
                    'id': label,
                    'label': label,
                    'name': doc.get('name') or f'Jaywun Cruise Waypoint NYU-{order:02d}',
                    'order': order,
                    'lat': lat,
                    'lon': lon,
                    'status': doc.get('status') or 'Active',
                    'privacy': 'Public' if doc.get('public', True) else 'Private',
                }
            )
        if not waypoints:
            source = self.JW_COLLECTIONS['cells'] if self._jw_cells_ready() else self.JW_COLLECTIONS['samples']
            pipeline = [
                {
                    '$group': {
                        '_id': '$waypoint_id' if source == self.JW_COLLECTIONS['cells'] else '$meta.waypoint_id',
                        'order': {'$first': '$waypoint_order' if source == self.JW_COLLECTIONS['cells'] else '$meta.waypoint_order'},
                        'lat': {'$first': '$lat'},
                        'lon': {'$first': '$long'},
                    }
                },
                {'$sort': {'order': ASCENDING}},
            ]
            for doc in self.db[source].aggregate(pipeline):
                label = self._jw_public_waypoint(doc.get('_id'))
                if not label:
                    continue
                order = int(doc.get('order') or self._jw_waypoint_order(label) or 0)
                waypoints.append(
                    {
                        'id': label,
                        'label': label,
                        'name': f'Jaywun Cruise Waypoint NYU-{order:02d}',
                        'order': order,
                        'lat': doc.get('lat'),
                        'lon': doc.get('lon'),
                        'status': 'Active',
                        'privacy': 'Public',
                    }
                )
        waypoints.sort(key=lambda item: item['order'])
        self.cache.set(cache_key, waypoints, ttl_seconds=300)
        return waypoints

    def _jw_metric_exists(self, metric: str, match: Optional[Dict[str, Any]] = None) -> bool:
        query = dict(match or {})
        self._jw_add_metric_match(query, metric)
        try:
            return self.db[self.JW_COLLECTIONS['samples']].find_one(query, {'_id': 1}) is not None
        except Exception:
            return False

    def _jw_available_metrics(self) -> List[Dict[str, Any]]:
        cache_key = 'jw_available_metrics'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        if self._jw_cells_ready():
            pipeline = [
                {'$match': {'depth_bin_m': {'$gte': 0}}},
                {'$project': {'pairs': {'$objectToArray': '$metrics'}}},
                {'$unwind': '$pairs'},
                {'$group': {'_id': '$pairs.k', 'cells': {'$sum': 1}, 'samples': {'$sum': {'$ifNull': ['$pairs.v.n', 0]}}}},
            ]
            raw_keys = {doc['_id'] for doc in self.db[self.JW_COLLECTIONS['cells']].aggregate(pipeline, allowDiskUse=True) if doc.get('_id')}
        else:
            raw_keys = set(self.JW_METRIC_PRIORITY)
            if self._collection_exists(self.JW_COLLECTIONS['profiles']):
                for fields in self.db[self.JW_COLLECTIONS['profiles']].distinct('fields'):
                    if isinstance(fields, list):
                        raw_keys.update(str(field) for field in fields if field)
            if self._collection_exists(self.JW_COLLECTIONS['registry']):
                for key_name in ('field', 'canonical_name', 'safe_field'):
                    raw_keys.update(str(value) for value in self.db[self.JW_COLLECTIONS['registry']].distinct(key_name) if value)
        mapped = {
            'sbeox0mg_per_l': 'do_mg_l',
            'sbeox0mg_l': 'do_mg_l',
            'sbeox0ml_l': 'oxygen_ml_l',
            'sal00': 'salinity_psu',
            't090c': 'temp_c',
            'prdm': 'pressure_dbar',
            'density00': 'density',
            'par_per_sat_per_log': 'par',
        }
        excluded = {'timestamp', 'time', 'times', 'ts', 'date', 'lat', 'long', 'depth_m', 'depsm', 'flag', 'scan', 'pumps', 'nbf', 'bct', 'sfdsm'}
        candidates = {mapped.get(key, key) for key in raw_keys if key and str(key).lower() not in excluded}
        metric_keys = []
        for key in candidates:
            if key in self.JW_METRIC_PRIORITY or key in self.JW_METRIC_LABELS:
                metric_keys.append(key)
        rank = {key: index for index, key in enumerate(self.JW_METRIC_PRIORITY)}
        metrics = [
            {
                'key': key,
                'label': self._jw_metric_label(key),
                'unit': self._jw_metric_unit(key),
                'cells': 0,
                'samples': 0,
            }
            for key in sorted(set(metric_keys), key=lambda item: (rank.get(item, len(rank)), self._jw_metric_label(item).lower(), item))
        ]
        self.cache.set(cache_key, metrics, ttl_seconds=300)
        return metrics

    def _jw_available_instruments(self) -> List[str]:
        cache_key = 'jw_available_instruments'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        allowed = set(self.JW_INSTRUMENT_ORDER)
        seen = set(self.JW_INSTRUMENT_ORDER)
        if self._jw_cells_ready():
            seen.update(str(value).lower() for value in self.db[self.JW_COLLECTIONS['cells']].distinct('instrument') if value)
        profile_has_rows = self._collection_exists(self.JW_COLLECTIONS['profiles']) and self.db[self.JW_COLLECTIONS['profiles']].count_documents({}, limit=1) > 0
        if profile_has_rows:
            seen.update(str(value).lower() for value in self.db[self.JW_COLLECTIONS['profiles']].distinct('instrument') if value)
        elif self._collection_exists(self.JW_COLLECTIONS['samples']):
            seen.update(str(value).lower() for value in self.db[self.JW_COLLECTIONS['samples']].distinct('meta.instrument') if value)
        if self._collection_exists(self.JW_COLLECTIONS['events']):
            for value in self.db[self.JW_COLLECTIONS['events']].distinct('instruments'):
                if isinstance(value, list):
                    seen.update(str(item).lower() for item in value if item)
                elif value:
                    seen.add(str(value).lower())
        seen = {instrument for instrument in seen if instrument in allowed}
        rank = {name: index for index, name in enumerate(self.JW_INSTRUMENT_ORDER)}
        instruments = sorted(seen, key=lambda name: (rank.get(name, len(rank)), name))
        self.cache.set(cache_key, instruments, ttl_seconds=300)
        return instruments

    def _jw_distinct_months(self, instrument: str = 'combined') -> List[str]:
        cache_key = f'jw_months:{instrument}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        if self._jw_cells_ready():
            query: Dict[str, Any] = {'depth_bin_m': {'$gte': 0}}
            if instrument != 'combined':
                query['instrument'] = instrument
            months = sorted(month for month in self.db[self.JW_COLLECTIONS['cells']].distinct('campaign_month', query) if month)
        else:
            query = {}
            if instrument != 'combined':
                query['instrument'] = instrument
            if self._collection_exists(self.JW_COLLECTIONS['profiles']) and self.db[self.JW_COLLECTIONS['profiles']].count_documents({}, limit=1) > 0:
                months = sorted(month for month in self.db[self.JW_COLLECTIONS['profiles']].distinct('campaign_month', query) if month)
            else:
                sample_query = {}
                if instrument != 'combined':
                    sample_query['meta.instrument'] = instrument
                months = sorted(month for month in self.db[self.JW_COLLECTIONS['samples']].distinct('meta.campaign_month', sample_query) if month)
        self.cache.set(cache_key, months, ttl_seconds=300)
        return months

    def _jw_distinct_metrics(self, instrument: str, campaign_month: str) -> List[str]:
        cache_key = f'jw_metric_keys:{instrument}:{campaign_month}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        if self._jw_cells_ready():
            query: Dict[str, Any] = {'campaign_month': campaign_month, 'depth_bin_m': {'$gte': 0}}
            if instrument != 'combined':
                query['instrument'] = instrument
            pipeline = [
                {'$match': query},
                {'$project': {'pairs': {'$objectToArray': '$metrics'}}},
                {'$unwind': '$pairs'},
                {'$group': {'_id': '$pairs.k'}},
            ]
            metric_keys = [doc['_id'] for doc in self.db[self.JW_COLLECTIONS['cells']].aggregate(pipeline, allowDiskUse=True) if doc.get('_id')]
        else:
            field_map = {
                'sbeox0mg_per_l': 'do_mg_l',
                'sbeox0mg_l': 'do_mg_l',
                'sbeox0ml_l': 'oxygen_ml_l',
                'sal00': 'salinity_psu',
                't090c': 'temp_c',
                'prdm': 'pressure_dbar',
                'density00': 'density',
                'par_per_sat_per_log': 'par',
            }
            query: Dict[str, Any] = {'campaign_month': campaign_month}
            if instrument != 'combined':
                query['instrument'] = instrument
            profile_fields = set()
            for fields in self.db[self.JW_COLLECTIONS['profiles']].distinct('fields', query):
                if isinstance(fields, list):
                    profile_fields.update(field_map.get(str(field), str(field)) for field in fields if field)
            available = {metric['key'] for metric in self._jw_available_metrics()}
            metric_keys = [key for key in profile_fields if key in available]
        rank = {key: index for index, key in enumerate(self.JW_METRIC_PRIORITY)}
        ordered = sorted(set(metric_keys), key=lambda key: (rank.get(key, len(rank)), self._jw_metric_label(key).lower(), key))
        self.cache.set(cache_key, ordered, ttl_seconds=180)
        return ordered

    def _jw_distinct_depths(self, instrument: str, campaign_month: str, metric: str) -> List[int]:
        cache_key = f'jw_depths:{instrument}:{campaign_month}:{metric}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        if self._jw_cells_ready():
            query: Dict[str, Any] = {
                'campaign_month': campaign_month,
                'depth_bin_m': {'$gte': 0},
                f'metrics.{metric}.avg': {'$exists': True},
            }
            if instrument != 'combined':
                query['instrument'] = instrument
            depths = self._jw_valid_depths(self.db[self.JW_COLLECTIONS['cells']].distinct('depth_bin_m', query))
        else:
            profile_query: Dict[str, Any] = {'campaign_month': campaign_month}
            if instrument != 'combined':
                profile_query['instrument'] = instrument
            profile_maxes = []
            for doc in self.db[self.JW_COLLECTIONS['profiles']].find(profile_query, {'_id': 0, 'depth_min_m': 1, 'depth_max_m': 1}):
                max_depth = doc.get('depth_max_m')
                if self._is_numeric_scalar(max_depth) and 0 <= float(max_depth) <= 250:
                    profile_maxes.append(float(max_depth))
            if profile_maxes:
                max_depth = int(math.ceil(max(profile_maxes)))
                depths = list(range(0, max_depth + 1))
                self.cache.set(cache_key, depths, ttl_seconds=180)
                return depths
            match: Dict[str, Any] = {'meta.campaign_month': campaign_month}
            if instrument != 'combined':
                match['meta.instrument'] = instrument
            match.setdefault('$and', []).append(self._jw_depth_match_clause())
            self._jw_add_metric_match(match, metric)
            pipeline = [
                {'$match': match},
                {'$project': {'depth_bin_m': {'$toInt': {'$round': [self._jw_depth_value_expr(), 0]}}}},
                {'$match': {'depth_bin_m': {'$gte': 0, '$lte': 250}}},
                {'$group': {'_id': '$depth_bin_m'}},
                {'$sort': {'_id': ASCENDING}},
            ]
            depths = self._jw_valid_depths(doc.get('_id') for doc in self.db[self.JW_COLLECTIONS['samples']].aggregate(pipeline, allowDiskUse=True))
        self.cache.set(cache_key, depths, ttl_seconds=180)
        return depths

    def _jw_sample_rollup_docs(
        self,
        metric: str,
        instrument: str = 'combined',
        campaign_month: Optional[str] = None,
        waypoint_id: Optional[str] = None,
        depth_bin_m: Optional[int] = None,
        group_fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        group_fields = group_fields or ['campaign_month', 'waypoint_id', 'waypoint_order', 'depth_bin_m']
        match: Dict[str, Any] = {}
        if campaign_month and str(campaign_month).lower() != 'all':
            match['meta.campaign_month'] = campaign_month
        if instrument != 'combined':
            match['meta.instrument'] = instrument
        canonical = self._jw_canonical_waypoint(waypoint_id) if waypoint_id else None
        if canonical:
            match['meta.waypoint_id'] = canonical
        normalized_depth = self._sbn_normalized_depth(depth_bin_m)
        if depth_bin_m is None:
            match.setdefault('$and', []).append(self._jw_depth_match_clause())
        else:
            match.setdefault('$and', []).append(self._jw_depth_match_clause(normalized_depth if normalized_depth is not None else 0))
        self._jw_add_metric_match(match, metric)
        group_id = {field: f'${field}' for field in group_fields}
        pipeline = [
            {'$match': match},
            {
                '$project': {
                    'campaign_month': '$meta.campaign_month',
                    'waypoint_id': '$meta.waypoint_id',
                    'waypoint_order': '$meta.waypoint_order',
                    'instrument': '$meta.instrument',
                    'depth_bin_m': {'$toInt': {'$round': [self._jw_depth_value_expr(), 0]}},
                    'lat': 1,
                    'long': 1,
                    'value': self._jw_metric_value_expr(metric),
                }
            },
            {'$match': {'depth_bin_m': {'$gte': 0, '$lte': 250}, 'value': {'$type': 'number'}}},
        ]
        if depth_bin_m is not None:
            pipeline.append({'$match': {'depth_bin_m': normalized_depth if normalized_depth is not None else 0}})
        pipeline.extend(
            [
                {
                    '$group': {
                        '_id': group_id,
                        'campaign_month': {'$first': '$campaign_month'},
                        'waypoint_id': {'$first': '$waypoint_id'},
                        'waypoint_order': {'$first': '$waypoint_order'},
                        'instrument': {'$first': '$instrument'},
                        'source_instruments': {'$addToSet': '$instrument'},
                        'depth_bin_m': {'$first': '$depth_bin_m'},
                        'lat': {'$first': '$lat'},
                        'long': {'$first': '$long'},
                        'avg': {'$avg': '$value'},
                        'min': {'$min': '$value'},
                        'max': {'$max': '$value'},
                        'n': {'$sum': 1},
                    }
                },
                {'$sort': {'campaign_month': ASCENDING, 'waypoint_order': ASCENDING, 'depth_bin_m': ASCENDING, 'instrument': ASCENDING}},
            ]
        )
        docs = []
        for doc in self.db[self.JW_COLLECTIONS['samples']].aggregate(pipeline, allowDiskUse=True):
            stats = {'avg': doc.get('avg'), 'min': doc.get('min'), 'max': doc.get('max'), 'n': doc.get('n')}
            docs.append(
                {
                    'campaign_month': doc.get('campaign_month'),
                    'waypoint_id': doc.get('waypoint_id'),
                    'waypoint_order': int(doc.get('waypoint_order') or self._jw_waypoint_order(doc.get('waypoint_id')) or 0),
                    'instrument': 'combined' if instrument == 'combined' and 'instrument' not in group_fields else doc.get('instrument'),
                    'source_instruments': sorted({str(item) for item in doc.get('source_instruments', []) if item}),
                    'depth_bin_m': self._sbn_normalized_depth(doc.get('depth_bin_m')),
                    'lat': doc.get('lat'),
                    'long': doc.get('long'),
                    'metrics': {metric: stats},
                }
            )
        return docs

    def _jw_rollup_docs(
        self,
        metric: str,
        instrument: str = 'combined',
        campaign_month: Optional[str] = None,
        waypoint_id: Optional[str] = None,
        depth_bin_m: Optional[int] = None,
        group_fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        group_fields = group_fields or ['campaign_month', 'waypoint_id', 'waypoint_order', 'depth_bin_m']
        if not self._jw_cells_ready():
            return self._jw_sample_rollup_docs(metric, instrument, campaign_month, waypoint_id, depth_bin_m, group_fields)
        query: Dict[str, Any] = {f'metrics.{metric}.avg': {'$exists': True}}
        if campaign_month and str(campaign_month).lower() != 'all':
            query['campaign_month'] = campaign_month
        if instrument != 'combined':
            query['instrument'] = instrument
        canonical = self._jw_canonical_waypoint(waypoint_id) if waypoint_id else None
        if canonical:
            query['waypoint_id'] = canonical
        if depth_bin_m is None:
            query['depth_bin_m'] = {'$gte': 0}
        else:
            normalized_depth = self._sbn_normalized_depth(depth_bin_m)
            query['depth_bin_m'] = normalized_depth if normalized_depth is not None else 0
        projection = {
            '_id': 0,
            'campaign_month': 1,
            'waypoint_id': 1,
            'waypoint_order': 1,
            'instrument': 1,
            'depth_bin_m': 1,
            'lat': 1,
            'long': 1,
            f'metrics.{metric}': 1,
        }
        docs = list(self.db[self.JW_COLLECTIONS['cells']].find(query, projection))
        if instrument != 'combined':
            return docs
        grouped: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
        for doc in docs:
            key = tuple(doc.get(field) for field in group_fields)
            grouped.setdefault(key, []).append(doc)
        combined = []
        for group in grouped.values():
            combined_doc = self._sbn_combined_doc(group, metric)
            if combined_doc:
                combined.append(combined_doc)
        return combined

    def _jw_format_cell(self, doc: Dict[str, Any], metric: str, instrument: Optional[str] = None) -> Dict[str, Any]:
        stats = self._sbn_metric_stats_from_doc(doc, metric)
        label = self._jw_public_waypoint(doc.get('waypoint_id')) or str(doc.get('waypoint_id') or '')
        return {
            'campaign_month': doc.get('campaign_month'),
            'waypoint_id': label,
            'waypoint_label': label,
            'waypoint_order': int(doc.get('waypoint_order') or self._jw_waypoint_order(label) or 0),
            'instrument': instrument or doc.get('instrument'),
            'source_instruments': doc.get('source_instruments'),
            'depth_bin_m': doc.get('depth_bin_m'),
            'lat': doc.get('lat'),
            'lon': doc.get('long'),
            'metric': metric,
            'value': stats.get('avg') if stats else None,
            'stats': stats,
            'metrics': {metric: stats} if stats else {},
        }

    def _jw_missing_cell(self, waypoint: Dict[str, Any], campaign_month: Optional[str], instrument: str, depth_bin_m: Optional[int], metric: str) -> Dict[str, Any]:
        return {
            'campaign_month': campaign_month,
            'waypoint_id': waypoint['id'],
            'waypoint_label': waypoint['label'],
            'waypoint_order': waypoint['order'],
            'instrument': instrument,
            'source_instruments': [],
            'depth_bin_m': depth_bin_m,
            'lat': waypoint.get('lat'),
            'lon': waypoint.get('lon'),
            'metric': metric,
            'value': None,
            'stats': None,
            'metrics': {},
        }

    def get_jw_options(self) -> Dict[str, Any]:
        cache_key = 'jw_options'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        events = []
        if self._collection_exists(self.JW_COLLECTIONS['events']) and self.db[self.JW_COLLECTIONS['events']].count_documents({}, limit=1):
            events = list(
                self.db[self.JW_COLLECTIONS['events']].find(
                    {},
                    {'_id': 0, 'campaign_id': 1, 'campaign_month': 1, 'status': 1, 'profile_count': 1, 'row_count': 1, 'instruments': 1, 'complete_instruments': 1},
                ).sort('campaign_month', ASCENDING)
            )
        elif self._collection_exists(self.JW_COLLECTIONS['profiles']):
            pipeline = [
                {
                    '$group': {
                        '_id': '$campaign_month',
                        'campaign_id': {'$first': '$campaign_id'},
                        'instruments': {'$addToSet': '$instrument'},
                        'profile_count': {'$sum': 1},
                        'row_count': {'$sum': {'$ifNull': ['$row_count', 0]}},
                    }
                },
                {'$sort': {'_id': ASCENDING}},
            ]
            events = [
                {
                    'campaign_id': doc.get('campaign_id'),
                    'campaign_month': doc.get('_id'),
                    'status': 'loaded',
                    'profile_count': int(doc.get('profile_count') or 0),
                    'row_count': int(doc.get('row_count') or 0),
                    'instruments': sorted(str(item).lower() for item in doc.get('instruments', []) if item),
                    'complete_instruments': [],
                }
                for doc in self.db[self.JW_COLLECTIONS['profiles']].aggregate(pipeline)
                if doc.get('_id')
            ]
        instruments = self._jw_available_instruments()
        allowed_instruments = set(instruments)
        for event in events:
            event['instruments'] = [
                str(instrument).lower()
                for instrument in event.get('instruments', [])
                if str(instrument).lower() in allowed_instruments
            ]
            event['complete_instruments'] = [
                str(instrument).lower()
                for instrument in event.get('complete_instruments', [])
                if str(instrument).lower() in allowed_instruments
            ]
        months = self._jw_distinct_months('combined') or [event['campaign_month'] for event in events if event.get('campaign_month')]
        months_by_instrument = {instrument: self._jw_distinct_months(instrument) for instrument in instruments}
        depths = self._jw_valid_depths(
            self.db[self.JW_COLLECTIONS['cells']].distinct('depth_bin_m') if self._jw_cells_ready() else []
        )
        if not depths:
            profile_maxes = []
            for doc in self.db[self.JW_COLLECTIONS['profiles']].find({}, {'_id': 0, 'depth_max_m': 1}):
                max_depth = doc.get('depth_max_m')
                if self._is_numeric_scalar(max_depth) and 0 <= float(max_depth) <= 250:
                    profile_maxes.append(float(max_depth))
            if profile_maxes:
                depths = list(range(0, int(math.ceil(max(profile_maxes))) + 1))
            else:
                depths = [0]
        payload = {
            'months': months,
            'events': events,
            'instruments': instruments,
            'months_by_instrument': months_by_instrument,
            'waypoints': self._jw_waypoint_docs(),
            'depths': depths,
            'metrics': self._jw_available_metrics(),
        }
        self.cache.set(cache_key, payload, ttl_seconds=300)
        return payload

    def get_jw_selection(
        self,
        instrument: str = 'combined',
        campaign_month: Optional[str] = None,
        metric: Optional[str] = None,
        depth_bin_m: int = 0,
    ) -> Dict[str, Any]:
        valid_instruments = ['combined'] + self.get_jw_options().get('instruments', [])
        if instrument not in valid_instruments:
            instrument = 'combined'
        months = self._jw_distinct_months(instrument)
        all_months = self.get_jw_options().get('months', [])
        if not months and instrument != 'combined':
            campaign_month = campaign_month if campaign_month in all_months else (all_months[-1] if all_months else campaign_month)
            available_metrics = self._jw_available_metrics()
            available_depths = self.get_jw_options().get('depths', [])
            return {
                'instrument': instrument,
                'campaign_month': campaign_month,
                'metric': metric,
                'depth_bin_m': int(depth_bin_m or 0),
                'available_months': all_months,
                'available_metrics': available_metrics,
                'available_depths': available_depths,
                'months': all_months,
                'metrics': available_metrics,
                'depths': available_depths,
                'compare_months': [],
                'has_data': False,
            }
        if campaign_month not in months:
            campaign_month = months[-1] if months else (all_months[-1] if all_months else campaign_month)
        metrics = self._jw_distinct_metrics(instrument, campaign_month) if campaign_month else []
        if not metrics and instrument != 'combined':
            available_metrics = self._jw_available_metrics()
            available_depths = self.get_jw_options().get('depths', [])
            return {
                'instrument': instrument,
                'campaign_month': campaign_month,
                'metric': metric,
                'depth_bin_m': int(depth_bin_m or 0),
                'available_months': months,
                'available_metrics': available_metrics,
                'available_depths': available_depths,
                'months': months,
                'metrics': available_metrics,
                'depths': available_depths,
                'compare_months': [],
                'has_data': False,
            }
        if not metrics:
            metrics = [item['key'] for item in self._jw_available_metrics()]
        if metric not in metrics:
            metric = metrics[0] if metrics else metric
        depths = self._jw_distinct_depths(instrument, campaign_month, metric) if campaign_month and metric else []
        requested_depth = self._sbn_normalized_depth(depth_bin_m)
        resolved_depth = self._sbn_closest_depth(requested_depth if requested_depth is not None else self._sbn_surface_depth(depths), depths)
        compare_months = sorted(month for month in self._jw_distinct_months(instrument) if month and month != campaign_month)
        metric_docs = [
            {'key': key, 'label': self._jw_metric_label(key), 'unit': self._jw_metric_unit(key)} for key in metrics
        ]
        return {
            'instrument': instrument,
            'campaign_month': campaign_month,
            'metric': metric,
            'depth_bin_m': resolved_depth,
            'available_months': months,
            'available_metrics': metric_docs,
            'available_depths': depths,
            'months': months,
            'metrics': metric_docs,
            'depths': depths,
            'compare_months': compare_months,
            'has_data': bool(months and metrics and depths),
        }

    def get_jw_cells(self, campaign_month: str, instrument: str, depth_bin_m: int, metric: str) -> Dict[str, Any]:
        depth_bin_m = self._sbn_normalized_depth(depth_bin_m)
        if depth_bin_m is None:
            depth_bin_m = 0
        cache_key = f'jw_cells:{campaign_month}:{instrument}:{depth_bin_m}:{metric}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        docs = self._jw_rollup_docs(metric, instrument, campaign_month=campaign_month, depth_bin_m=depth_bin_m)
        by_waypoint = {self._jw_public_waypoint(doc.get('waypoint_id')): self._jw_format_cell(doc, metric, instrument) for doc in docs}
        rows = [
            by_waypoint.get(waypoint['label'])
            or self._jw_missing_cell(waypoint, campaign_month, instrument, depth_bin_m, metric)
            for waypoint in self._jw_waypoint_docs()
        ]
        payload = {
            'campaign_month': campaign_month,
            'instrument': instrument,
            'depth_bin_m': depth_bin_m,
            'metric': {'key': metric, 'label': self._jw_metric_label(metric), 'unit': self._jw_metric_unit(metric)},
            'data': rows,
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_jw_trend(self, waypoint_id: str, instrument: str, depth_bin_m: int, metric: str) -> Dict[str, Any]:
        canonical = self._jw_canonical_waypoint(waypoint_id)
        if not canonical:
            raise KeyError('Waypoint not found.')
        depth_bin_m = self._sbn_normalized_depth(depth_bin_m)
        if depth_bin_m is None:
            depth_bin_m = 0
        cache_key = f'jw_trend:{canonical}:{instrument}:{depth_bin_m}:{metric}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        docs = self._jw_rollup_docs(metric, instrument, waypoint_id=canonical, depth_bin_m=depth_bin_m, group_fields=['campaign_month', 'waypoint_id', 'depth_bin_m'])
        rows = [self._jw_format_cell(doc, metric, instrument) for doc in sorted(docs, key=lambda item: item.get('campaign_month') or '')]
        payload = {
            'waypoint_id': self._jw_public_waypoint(canonical),
            'instrument': instrument,
            'depth_bin_m': depth_bin_m,
            'metric': {'key': metric, 'label': self._jw_metric_label(metric), 'unit': self._jw_metric_unit(metric)},
            'data': rows,
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_jw_depth_waypoint_heatmap(self, campaign_month: str, instrument: str, metric: str) -> Dict[str, Any]:
        cache_key = f'jw_depth_waypoint_heatmap:{campaign_month}:{instrument}:{metric}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        docs = self._jw_rollup_docs(metric, instrument, campaign_month=campaign_month, depth_bin_m=None)
        depths = self._sbn_valid_depths(doc.get('depth_bin_m') for doc in docs)
        waypoints = self._jw_waypoint_docs()
        values = {}
        for doc in docs:
            label = self._jw_public_waypoint(doc.get('waypoint_id'))
            stats = self._sbn_metric_stats_from_doc(doc, metric)
            depth = self._sbn_normalized_depth(doc.get('depth_bin_m'))
            if label and stats and depth is not None:
                values[(label, depth)] = stats['avg']
        payload = {
            'campaign_month': campaign_month,
            'instrument': instrument,
            'metric': {'key': metric, 'label': self._jw_metric_label(metric), 'unit': self._jw_metric_unit(metric)},
            'x': [waypoint['label'] for waypoint in waypoints],
            'y': depths,
            'z': [[values.get((waypoint['label'], depth)) for waypoint in waypoints] for depth in depths],
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_jw_month_depth_heatmap(self, waypoint_id: str, instrument: str, metric: str) -> Dict[str, Any]:
        canonical = self._jw_canonical_waypoint(waypoint_id)
        if not canonical:
            raise KeyError('Waypoint not found.')
        cache_key = f'jw_month_depth_heatmap:{canonical}:{instrument}:{metric}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        docs = self._jw_rollup_docs(metric, instrument, waypoint_id=canonical, depth_bin_m=None, group_fields=['campaign_month', 'waypoint_id', 'depth_bin_m'])
        months = sorted({doc.get('campaign_month') for doc in docs if doc.get('campaign_month')})
        depths = self._sbn_valid_depths(doc.get('depth_bin_m') for doc in docs)
        values = {}
        for doc in docs:
            stats = self._sbn_metric_stats_from_doc(doc, metric)
            depth = self._sbn_normalized_depth(doc.get('depth_bin_m'))
            if stats and depth is not None:
                values[(doc.get('campaign_month'), depth)] = stats['avg']
        payload = {
            'waypoint_id': self._jw_public_waypoint(canonical),
            'instrument': instrument,
            'metric': {'key': metric, 'label': self._jw_metric_label(metric), 'unit': self._jw_metric_unit(metric)},
            'x': months,
            'y': depths,
            'z': [[values.get((month, depth)) for month in months] for depth in depths],
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_jw_month_waypoint_heatmap(self, instrument: str, depth_bin_m: int, metric: str) -> Dict[str, Any]:
        depth_bin_m = self._sbn_normalized_depth(depth_bin_m)
        if depth_bin_m is None:
            depth_bin_m = 0
        cache_key = f'jw_month_waypoint_heatmap:{instrument}:{depth_bin_m}:{metric}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        docs = self._jw_rollup_docs(metric, instrument, depth_bin_m=depth_bin_m, group_fields=['campaign_month', 'waypoint_id', 'waypoint_order', 'depth_bin_m'])
        months = sorted({doc.get('campaign_month') for doc in docs if doc.get('campaign_month')})
        waypoints = self._jw_waypoint_docs()
        values = {}
        for doc in docs:
            label = self._jw_public_waypoint(doc.get('waypoint_id'))
            stats = self._sbn_metric_stats_from_doc(doc, metric)
            if label and stats:
                values[(label, doc.get('campaign_month'))] = stats['avg']
        payload = {
            'instrument': instrument,
            'depth_bin_m': depth_bin_m,
            'metric': {'key': metric, 'label': self._jw_metric_label(metric), 'unit': self._jw_metric_unit(metric)},
            'x': months,
            'y': [waypoint['label'] for waypoint in waypoints],
            'z': [[values.get((waypoint['label'], month)) for month in months] for waypoint in waypoints],
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_jw_crossplot(self, campaign_month: str, instrument: str, depth_bin_m: int, x_metric: str, y_metric: str) -> Dict[str, Any]:
        depth_bin_m = self._sbn_normalized_depth(depth_bin_m)
        if depth_bin_m is None:
            depth_bin_m = 0
        cache_key = f'jw_crossplot:{campaign_month}:{instrument}:{depth_bin_m}:{x_metric}:{y_metric}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        x_docs = self._jw_rollup_docs(x_metric, instrument, campaign_month=campaign_month, depth_bin_m=depth_bin_m)
        y_docs = self._jw_rollup_docs(y_metric, instrument, campaign_month=campaign_month, depth_bin_m=depth_bin_m)
        y_by_waypoint = {doc.get('waypoint_id'): doc for doc in y_docs}
        rows = []
        for x_doc in x_docs:
            y_doc = y_by_waypoint.get(x_doc.get('waypoint_id'))
            if not y_doc:
                continue
            x_stats = self._sbn_metric_stats_from_doc(x_doc, x_metric)
            y_stats = self._sbn_metric_stats_from_doc(y_doc, y_metric)
            if not x_stats or not y_stats:
                continue
            rows.append(
                {
                    'waypoint_id': self._jw_public_waypoint(x_doc.get('waypoint_id')),
                    'waypoint_order': int(x_doc.get('waypoint_order') or 0),
                    'instrument': instrument,
                    'x': x_stats['avg'],
                    'y': y_stats['avg'],
                }
            )
        rows.sort(key=lambda item: item['waypoint_order'])
        payload = {
            'campaign_month': campaign_month,
            'instrument': instrument,
            'depth_bin_m': depth_bin_m,
            'x_metric': {'key': x_metric, 'label': self._jw_metric_label(x_metric), 'unit': self._jw_metric_unit(x_metric)},
            'y_metric': {'key': y_metric, 'label': self._jw_metric_label(y_metric), 'unit': self._jw_metric_unit(y_metric)},
            'data': rows,
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_jw_profiles(self, campaign_month: Optional[str] = None, instrument: Optional[str] = None, waypoint_id: Optional[str] = None) -> Dict[str, Any]:
        cache_key = f'jw_profiles:{campaign_month or ""}:{instrument or ""}:{waypoint_id or ""}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        query: Dict[str, Any] = {}
        if campaign_month:
            query['campaign_month'] = campaign_month
        if instrument and instrument != 'combined':
            query['instrument'] = instrument
        canonical = self._jw_canonical_waypoint(waypoint_id) if waypoint_id else None
        if canonical:
            query['waypoint_id'] = canonical
        cursor = self.db[self.JW_COLLECTIONS['profiles']].find(
            query,
            {
                '_id': 0,
                'campaign_month': 1,
                'waypoint_id': 1,
                'waypoint_order': 1,
                'site': 1,
                'instrument': 1,
                'row_count': 1,
                'duplicate_rows': 1,
                'depth_min_m': 1,
                'depth_max_m': 1,
                'ts_min': 1,
                'ts_max': 1,
                'fields': 1,
                'status': 1,
            },
        ).sort([('campaign_month', ASCENDING), ('waypoint_order', ASCENDING), ('instrument', ASCENDING)])
        rows = []
        for doc in cursor.limit(1500):
            rows.append(
                {
                    **doc,
                    'waypoint_id': self._jw_public_waypoint(doc.get('waypoint_id')),
                    'ts_min': self._dt_string(doc.get('ts_min')) if doc.get('ts_min') else None,
                    'ts_max': self._dt_string(doc.get('ts_max')) if doc.get('ts_max') else None,
                }
            )
        payload = {'data': rows}
        self.cache.set(cache_key, payload, ttl_seconds=120)
        return payload

    def export_jw_csv_iter(
        self,
        campaign_month: Optional[str] = None,
        instrument: str = 'combined',
        depth_bin_m: Optional[int] = None,
        metrics: Optional[List[str]] = None,
        all_depths: bool = False,
        append_location: bool = False,
    ) -> Iterable[str]:
        metric_keys = [metric for metric in (metrics or []) if metric]
        if not metric_keys:
            metric_keys = [item['key'] for item in self._jw_available_metrics()]
        header = [
            'campaign_month',
            'instrument',
            'source_instruments',
            'waypoint',
            'waypoint_order',
            'depth_bin_m',
            'metric',
            'metric_label',
            'unit',
            'avg',
            'min',
            'max',
            'n',
        ]
        if append_location:
            header.extend(['latitude', 'longitude'])
        if not metric_keys:
            return self._csv_chunk_writer([header])

        def rows() -> Iterable[List[Any]]:
            yield header
            for metric in metric_keys:
                docs = self._jw_rollup_docs(
                    metric,
                    instrument,
                    campaign_month=campaign_month,
                    depth_bin_m=None if all_depths else depth_bin_m,
                    group_fields=['campaign_month', 'waypoint_id', 'waypoint_order', 'depth_bin_m'],
                )
                for doc in sorted(docs, key=lambda item: (item.get('campaign_month') or '', int(item.get('waypoint_order') or 0), int(item.get('depth_bin_m') or 0))):
                    stats = self._sbn_metric_stats_from_doc(doc, metric)
                    if not stats:
                        continue
                    source_instruments = doc.get('source_instruments') or ([doc.get('instrument')] if doc.get('instrument') else [])
                    row: List[Any] = [
                        doc.get('campaign_month'),
                        instrument if instrument == 'combined' else doc.get('instrument'),
                        ';'.join(str(item) for item in source_instruments if item),
                        self._jw_public_waypoint(doc.get('waypoint_id')) or doc.get('waypoint_id'),
                        int(doc.get('waypoint_order') or self._jw_waypoint_order(doc.get('waypoint_id')) or 0),
                        doc.get('depth_bin_m'),
                        metric,
                        self._jw_metric_label(metric),
                        self._jw_metric_unit(metric),
                        stats.get('avg'),
                        stats.get('min'),
                        stats.get('max'),
                        stats.get('n'),
                    ]
                    if append_location:
                        row.extend([doc.get('lat'), doc.get('long')])
                    yield row

        return self._csv_chunk_writer(rows())

    # ------------------------------------------------------------------
    # Latest cards and alerts
    # ------------------------------------------------------------------
    def _quick_aggregation_for_period(self, period: str) -> str:
        return {
            '24H': '15m',
            '7D': '1h',
            '30D': '6h',
            '3M': '1d',
            '6M': '1d',
            '1Y': '1d',
            'ALL': '1d',
        }.get(period.upper(), '15m')

    def get_latest_cards(
        self,
        station_id: str,
        period: str = '24H',
        include_trends: bool = False,
        include_sensor_trends: bool = False,
        clean: bool = False,
        station: Optional[Dict[str, Any]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        station = station or self.get_station_summary(station_id)
        period_label = self._window_label(period, start_date, end_date)
        cache_key = f'latest_cards:{station["station_id"]}:{period.upper()}:{start_date or ""}:{end_date or ""}:{include_trends}:{include_sensor_trends}:{clean}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        aggregation = 'raw' if station['device_type'] == 'underwater_probe' and (start_date or end_date) else self._quick_aggregation_for_period(period)
        quick_metrics = self._quick_metrics_for_station(station)
        if include_trends and station['device_type'] == 'Fidas_Palas':
            trend_points = 180
        else:
            trend_points = 360 if include_trends else 180
        timeseries = self.get_timeseries(
            station_id,
            period=period,
            aggregation=aggregation,
            metrics=quick_metrics,
            split_sensors=False,
            clean=clean,
            station=station,
            start_date=start_date,
            end_date=end_date,
            display_points=trend_points,
        )
        charts = timeseries.get('charts', [])
        cards = []
        trends = []
        sensor_trends_by_label: Dict[str, List[Dict[str, Any]]] = {}
        if include_trends and include_sensor_trends and station['device_type'] == 'IoTBox':
            sensor_timeseries = self.get_timeseries(
                station_id,
                period=period,
                aggregation=aggregation,
                metrics=quick_metrics,
                split_sensors=True,
                station=station,
                start_date=start_date,
                end_date=end_date,
                display_points=trend_points,
            )
            for sensor_chart in sensor_timeseries.get('charts', []):
                sensor_trends_by_label.setdefault(sensor_chart['canonical_label'], []).append({
                    'metric': sensor_chart['metric'],
                    'label': sensor_chart['label'],
                    'canonical_label': sensor_chart['canonical_label'],
                    'unit': self._extract_unit(sensor_chart['label']),
                    'summary': sensor_chart['summary'],
                    'series': sensor_chart['series'],
                })
        card_charts = charts if station['device_type'] in {'Fidas_Palas', 'Meteorological'} else charts[:6]
        for chart in card_charts:
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
                'count': chart['summary'].get('count'),
            }
            cards.append(card)
            if include_trends:
                trends.append({
                    'metric': chart['metric'],
                    'label': label,
                    'canonical_label': chart['canonical_label'],
                    'unit': self._extract_unit(label),
                    'summary': chart['summary'],
                    'series': chart['series'],
                    'sensor_trends': sensor_trends_by_label.get(chart['canonical_label'], []),
                })
        payload = {
            'station': station,
            'period': period_label,
            'start_date': start_date,
            'end_date': end_date,
            'clean': clean and station['device_type'] == 'Fidas_Palas',
            'trend_aggregation': aggregation,
            'supports_sensor_trends': station['device_type'] == 'IoTBox',
            'card_mode': 'statistics' if station['device_type'] == 'underwater_probe' else 'current',
            'available_metrics': timeseries.get('available_metrics') or self._metric_options(station, self._available_metric_map(station)),
            'cards': cards,
            'trends': trends,
            'events': timeseries.get('events', []),
            'latest_table': [],
            'message': timeseries.get('message'),
        }
        self.cache.set(cache_key, payload, ttl_seconds=30)
        return payload

    def _extract_unit(self, label: str) -> str:
        if '(' in label and ')' in label:
            return label.split('(')[-1].split(')')[0]
        return ''

    def _sample_spectra_documents(
        self,
        collection_name: str,
        time_field: str,
        query: Dict[str, Any],
        max_frames: int,
    ) -> List[Dict[str, Any]]:
        collection = self.db[collection_name]
        projection = {'_id': 0, time_field: 1, 'sizes': 1, 'spectra': 1}
        if time_field not in query:
            pipeline = []
            if query:
                pipeline.extend([
                    {'$sample': {'size': min(max_frames * 8, 2000)}},
                    {'$match': query},
                    {'$limit': max_frames},
                ])
            else:
                pipeline.append({'$sample': {'size': max_frames}})
            pipeline.extend([
                {'$project': projection},
                {'$sort': {time_field: ASCENDING}},
            ])
            return list(collection.aggregate(pipeline, allowDiskUse=True))

        first = collection.find_one(query, projection={time_field: 1}, sort=[(time_field, ASCENDING)])
        last = collection.find_one(query, projection={time_field: 1}, sort=[(time_field, DESCENDING)])
        if not first or not last or not first.get(time_field) or not last.get(time_field):
            return []

        start_dt = first[time_field]
        end_dt = last[time_field]
        total_seconds = max(0.0, (end_dt - start_dt).total_seconds())
        if total_seconds == 0:
            doc = collection.find_one(query, projection=projection, sort=[(time_field, DESCENDING)])
            return [doc] if doc else []

        bucket_ms = max(1, int(math.ceil(total_seconds * 1000 / max_frames)))
        pipeline = [
            {'$match': query},
            {'$sort': {time_field: ASCENDING}},
            {'$project': projection},
            {'$addFields': {
                '_sample_bucket': {
                    '$floor': {
                        '$divide': [
                            {'$subtract': [f'${time_field}', start_dt]},
                            bucket_ms,
                        ]
                    }
                }
            }},
            {'$group': {'_id': '$_sample_bucket', 'doc': {'$last': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$doc'}},
            {'$project': {'_sample_bucket': 0}},
            {'$sort': {time_field: ASCENDING}},
            {'$limit': max_frames},
        ]
        return list(collection.aggregate(pipeline, allowDiskUse=True))

    def _numeric_list(self, values: Any) -> List[Optional[float]]:
        if not isinstance(values, list):
            return []
        numeric: List[Optional[float]] = []
        for value in values:
            if self._is_numeric_scalar(value):
                numeric.append(float(value))
            else:
                numeric.append(None)
        return numeric

    def get_fidas_spectra(
        self,
        station_id: str,
        period: str = '24H',
        max_frames: int = 700,
        clean: bool = False,
        station: Optional[Dict[str, Any]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        station = station or self.get_station_summary(station_id)
        period_label = self._window_label(period, start_date, end_date)
        cache_key = f'fidas_spectra:{station["station_id"]}:{period.upper()}:{start_date or ""}:{end_date or ""}:{max_frames}:{clean}'
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        if station['device_type'] != 'Fidas_Palas':
            return {
                'station': station,
                'period': period_label,
                'start_date': start_date,
                'end_date': end_date,
                'clean': False,
                'sizes': [],
                'frames': [],
                'message': 'Spectra are only available for Fidas Palas stations.',
            }

        collection_name = self.settings.mongo_fidas_collection
        if not self._collection_exists(collection_name):
            return {'station': station, 'period': period_label, 'start_date': start_date, 'end_date': end_date, 'clean': clean, 'sizes': [], 'frames': [], 'message': 'Fidas collection was not found.'}
        self._ensure_time_index(collection_name, 'datetime')

        query = self._base_query_for_station_window(station, period, 'datetime', start_date, end_date)
        if clean:
            query['errors'] = {'$lte': 0}
        docs = self._sample_spectra_documents(collection_name, 'datetime', query, max(24, min(max_frames, 1000)))
        sizes: List[Optional[float]] = []
        frames: List[Dict[str, Any]] = []
        for doc in docs:
            values = self._numeric_list(doc.get('spectra'))
            if not values:
                continue
            if not sizes:
                sizes = self._numeric_list(doc.get('sizes'))
                if not sizes:
                    sizes = [float(index + 1) for index in range(len(values))]
            length = min(len(sizes), len(values))
            timestamp = self._station_actual_datetime(station, doc.get('datetime'))
            frames.append({
                'timestamp': self._dt_string(timestamp),
                'label': self._human_dt(timestamp),
                'values': values[:length],
            })

        sizes = sizes[: min((len(frame['values']) for frame in frames), default=len(sizes))]
        payload = {
            'station': station,
            'period': period_label,
            'start_date': start_date,
            'end_date': end_date,
            'clean': clean,
            'sizes': sizes,
            'size_unit': 'µm',
            'spectra_unit': 'Particle count',
            'frames': frames,
            'frame_count': len(frames),
            'latest_index': max(0, len(frames) - 1),
        }
        self.cache.set(cache_key, payload, ttl_seconds=60)
        return payload

    def get_network_summary(self) -> Dict[str, Any]:
        cache_key = 'network_summary:v3'
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        docs = [
            doc for doc in
            self.db[self.settings.mongo_stations_info_collection].find(
                {'lat': {'$ne': None}, 'long': {'$ne': None}, **self._visible_station_filter()},
                self.station_projection,
            )
            if not self._is_hidden_station_doc(doc)
        ]
        stations = [self._normalize_station(doc) for doc in docs]
        payload = {
            'station_count': len(stations),
            'alerts': [],
        }
        self.cache.set(cache_key, payload, ttl_seconds=max(60, self.settings.cache_ttl_seconds))
        return payload

    def get_alerts(self) -> List[Dict[str, Any]]:
        return []

    # ------------------------------------------------------------------
    # Raw export helpers
    # ------------------------------------------------------------------
    def _csv_chunk_writer(self, rows: Iterable[List[Any]]) -> Iterable[str]:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator='\n')
        for row in rows:
            writer.writerow(row)
            if buffer.tell() >= 65536:
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)
        if buffer.tell():
            yield buffer.getvalue()

    def _raw_document_csv_iter(
        self,
        station: Dict[str, Any],
        period: str,
        metrics: Optional[List[str]],
        clean: bool,
        append_location: bool,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[Iterable[str]]:
        device_type = station.get('device_type')
        if device_type not in {'Fidas_Palas', 'Meteorological', 'underwater_probe'} and not self._is_spotter_buoy(station):
            return None
        collection_name, time_field = self._collection_for_station(station)
        if not collection_name or not time_field or not self._collection_exists(collection_name):
            return None

        label_map = self._available_metric_map(station)
        requested = self._canonicalize_underwater_metrics(metrics or []) if device_type == 'underwater_probe' else (metrics or [])
        selected = [metric for metric in requested if metric in label_map]
        if not selected:
            selected = self._default_metrics(label_map, limit=3)
        if not selected:
            return None
        metric_sources = {
            metric: self._underwater_metric_aliases(metric) if device_type == 'underwater_probe' else [metric]
            for metric in selected
        }

        query = self._with_station_data_filter(
            station,
            self._base_query_for_station_window(station, period, time_field, start_date, end_date),
        )
        projection: Dict[str, int] = {'_id': 0, time_field: 1}
        for metric in selected:
            for source_metric in metric_sources[metric]:
                projection[self._metric_projection_root(source_metric)] = 1
        if clean and device_type == 'Fidas_Palas':
            projection['errors'] = 1
            query['errors'] = {'$lte': 0}

        collection = self.db[collection_name]
        cursor = collection.find(query, projection).sort(time_field, ASCENDING).batch_size(5000)
        first = next(cursor, None)
        if not first:
            return None

        header = ['timestamp']
        if append_location:
            header.extend(['station_name', 'latitude', 'longitude'])
        header.extend(label_map[metric] for metric in selected)

        def row_values(doc: Dict[str, Any]) -> List[Any]:
            row: List[Any] = [self._dt_string_for_station(station, doc.get(time_field))]
            if append_location:
                row.extend([station.get('name'), station.get('lat'), station.get('lon')])
            for metric in selected:
                value = self._first_document_metric_number(doc, metric_sources[metric])
                row.append(value if value is not None else '')
            return row

        def rows() -> Iterable[List[Any]]:
            yield header
            yield row_values(first)
            for doc in cursor:
                yield row_values(doc)

        return self._csv_chunk_writer(rows())

    def export_csv_iter(
        self,
        station_id: str,
        period: str,
        aggregation: str,
        metrics: Optional[List[str]],
        split_sensors: bool,
        clean: bool = False,
        append_location: bool = False,
        station: Optional[Dict[str, Any]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[Iterable[str]]:
        station = station or self.get_station_summary(station_id)
        if aggregation.lower() == 'raw' and not split_sensors:
            streamed = self._raw_document_csv_iter(station, period, metrics, clean, append_location, start_date=start_date, end_date=end_date)
            if streamed is not None:
                return streamed

        frame = self.export_frame(
            station_id,
            period=period,
            aggregation=aggregation,
            metrics=metrics,
            split_sensors=split_sensors,
            clean=clean,
            append_location=append_location,
            station=station,
            start_date=start_date,
            end_date=end_date,
        )
        if frame.empty:
            return None

        def rows() -> Iterable[str]:
            yield frame.head(0).to_csv(index=False)
            for start in range(0, len(frame), 5000):
                yield frame.iloc[start:start + 5000].to_csv(index=False, header=False)

        return rows()

    def export_frame(
        self,
        station_id: str,
        period: str,
        aggregation: str,
        metrics: Optional[List[str]],
        split_sensors: bool,
        clean: bool = False,
        append_location: bool = False,
        station: Optional[Dict[str, Any]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        payload = self.get_timeseries(
            station_id,
            period=period,
            aggregation=aggregation,
            metrics=metrics,
            split_sensors=split_sensors,
            clean=clean,
            station=station,
            start_date=start_date,
            end_date=end_date,
            display_points=None,
        )
        charts = payload.get('charts', [])
        if not charts:
            return pd.DataFrame()
        data = {'timestamp': [point['x'] for point in charts[0]['series']]}
        if append_location:
            data['station_name'] = [station.get('name')] * len(data['timestamp'])
            data['latitude'] = [station.get('lat')] * len(data['timestamp'])
            data['longitude'] = [station.get('lon')] * len(data['timestamp'])
        for chart in charts:
            data[chart['label']] = [point['y'] for point in chart['series']]
        return pd.DataFrame(data)

    def healthcheck(self) -> Dict[str, Any]:
        self.client.admin.command('ping')
        return {'status': 'ok', 'database': self.settings.mongo_db_name}
