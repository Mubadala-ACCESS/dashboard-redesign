from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .mongo_service import MongoDashboardRepository


class StatusService:
    TS_CANDIDATES = ['datetime', 'Timestamp', 'ts', 'time', 'created_at']
    TYPE_ORDER = [
        'SBNTransect',
        'underwater_probe',
        'Fidas_Palas',
        'Meteorological',
        'Buoy',
        'IoTBox',
        'JWCruise',
        'coral_reef',
    ]
    TYPE_LABELS = {
        'IoTBox': 'IoT Boxes',
        'Fidas_Palas': 'Fidas Palas 200S',
        'Meteorological': 'Meteorological Stations',
        'Buoy': 'Buoys',
        'SBNTransect': 'Transects',
        'underwater_probe': 'Underwater Probes',
        'coral_reef': 'Corals',
        'JWCruise': 'Jaywun Cruises',
    }
    LIVE_TYPES = {'IoTBox', 'Meteorological', 'Fidas_Palas', 'Buoy'}
    OPTIONAL_NULL_FIELDS = {
        'Meteorological': {'I3_VPOWER', 'I4_VOUT'},
    }
    IOT_EXPECTED_SENSORS = {'air_sensor': 2, 'co2_sensor': 2, 'particulate_matter': 2}
    AIR_FIELDS = ['humidity', 'temperature', 'pressure']
    CO2_FIELDS = ['co2']
    PM_FIELDS = ['PM1mass', 'PM2,5mass', 'PM10mass']
    AIR_RANGES = {
        'humidity': (0, 100, '%'),
        'temperature': (-40, 85, 'deg C'),
        'pressure': (300, 1100, 'hPa'),
    }

    def __init__(self, repo: MongoDashboardRepository):
        self.repo = repo
        self.db = repo.db
        self.settings = repo.settings

    def _now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def _to_aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _parse_ts(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return self._to_aware_utc(value)
        if isinstance(value, (int, float)):
            try:
                if value > 1e12:
                    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
                return datetime.fromtimestamp(value, tz=timezone.utc)
            except Exception:
                return None
        if isinstance(value, str):
            text = value.strip()
            if text.endswith('Z'):
                text = text[:-1] + '+00:00'
            try:
                return self._to_aware_utc(datetime.fromisoformat(text))
            except Exception:
                try:
                    number = float(text)
                    if number > 1e12:
                        return datetime.fromtimestamp(number / 1000.0, tz=timezone.utc)
                    return datetime.fromtimestamp(number, tz=timezone.utc)
                except Exception:
                    return None
        return None

    def _latest_record(self, collection_name: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        if not self.repo._collection_exists(collection_name):
            return None, None
        for ts_field in self.TS_CANDIDATES:
            try:
                doc = self.db[collection_name].find_one(sort=[(ts_field, -1)])
            except Exception:
                doc = None
            if doc and self._parse_ts(doc.get(ts_field)) is not None:
                return doc, ts_field
        try:
            return self.db[collection_name].find_one(sort=[('_id', -1)]), None
        except Exception:
            return None, None

    def _value_missing(self, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str) and not value.strip():
            return True
        if isinstance(value, str) and value.strip().upper() in {'NAN', 'NA', '-999', '-999.0', '-9999', '-9999.0'}:
            return True
        if isinstance(value, (int, float)) and value in (-999, -999.0, -9999, -9999.0):
            return True
        return False

    def _percent_diff(self, a: Any, b: Any) -> Optional[float]:
        try:
            if a is None or b is None:
                return None
            af = float(a)
            bf = float(b)
            denom = (abs(af) + abs(bf)) / 2.0
            if denom == 0:
                return 0.0
            return abs(af - bf) / denom * 100.0
        except Exception:
            return None

    def _format_list(self, values: List[str], connector: str = 'and') -> str:
        if not values:
            return ''
        if len(values) == 1:
            return values[0]
        if len(values) == 2:
            return f'{values[0]} {connector} {values[1]}'
        return f'{", ".join(values[:-1])}, {connector} {values[-1]}'

    def _field_label(self, key: str) -> str:
        return {
            'humidity': 'humidity',
            'temperature': 'temperature',
            'pressure': 'pressure',
            'co2': 'CO2',
            'PM1mass': 'PM1 mass',
            'PM2,5mass': 'PM2.5 mass',
            'PM10mass': 'PM10 mass',
        }.get(key, key)

    def _sensor_numbers(self, indices: List[int]) -> str:
        return self._format_list([str(index + 1) for index in sorted(indices)])

    def _sensor_value(self, record: Dict[str, Any], sensor_key: str, index: int, field: str) -> Any:
        node = record.get(f'{sensor_key}+{index}')
        if not isinstance(node, dict):
            return None
        return node.get(field)

    def _missing_sensor_fields(self, record: Dict[str, Any], sensor_key: str, fields: List[str], count: int) -> Dict[int, List[str]]:
        missing: Dict[int, List[str]] = {}
        for index in range(count):
            node = record.get(f'{sensor_key}+{index}')
            if not isinstance(node, dict):
                missing[index] = list(fields)
                continue
            fields_missing = [field for field in fields if self._value_missing(node.get(field))]
            if fields_missing:
                missing[index] = fields_missing
        return missing

    def _expected_sensor_count(self, station: Dict[str, Any], sensor_key: str) -> int:
        try:
            configured = int((station.get('sensors') or {}).get(sensor_key) or 0)
        except Exception:
            configured = 0
        return max(configured, self.IOT_EXPECTED_SENSORS.get(sensor_key, 0))

    def _co2_sensor_issues(self, record: Dict[str, Any], station: Dict[str, Any]) -> List[str]:
        count = self._expected_sensor_count(station, 'co2_sensor')
        if count <= 0:
            return []
        missing = self._missing_sensor_fields(record, 'co2_sensor', self.CO2_FIELDS, count)
        missing_indices = [index for index, fields in missing.items() if set(fields) == set(self.CO2_FIELDS)]
        if not missing_indices:
            return []
        plural = 's' if len(missing_indices) > 1 else ''
        verb = 'are' if len(missing_indices) > 1 else 'is'
        return [f'CO2 sensor{plural} {self._sensor_numbers(missing_indices)} {verb} not sending data.']

    def _air_sensor_issues(self, record: Dict[str, Any], station: Dict[str, Any]) -> List[str]:
        count = self._expected_sensor_count(station, 'air_sensor')
        if count <= 0:
            return []

        issues: List[str] = []
        missing = self._missing_sensor_fields(record, 'air_sensor', self.AIR_FIELDS, count)
        fully_missing = [index for index, fields in missing.items() if set(fields) == set(self.AIR_FIELDS)]
        partial_missing = {index: fields for index, fields in missing.items() if index not in fully_missing}
        if fully_missing:
            fields_text = self._format_list([self._field_label(field) for field in self.AIR_FIELDS], connector='or')
            if len(fully_missing) == count:
                issues.append(f'Air sensors {self._sensor_numbers(fully_missing)} are not sending {fields_text} data; both BME280 sensors are not reporting.')
            else:
                number_text = self._sensor_numbers(fully_missing)
                if len(fully_missing) > 1:
                    issues.append(f'Air sensors {number_text} are not sending {fields_text} data.')
                else:
                    issues.append(f'Air sensor {number_text} is not sending {fields_text} data.')
        for index, fields in sorted(partial_missing.items()):
            fields_text = self._format_list([self._field_label(field) for field in fields])
            issues.append(f'Air sensor {index + 1} is not sending {fields_text} data.')

        invalids: Dict[int, List[str]] = {}
        for index in range(count):
            if index in fully_missing:
                continue
            for field, (low, high, unit) in self.AIR_RANGES.items():
                value = self._sensor_value(record, 'air_sensor', index, field)
                if self._value_missing(value):
                    continue
                try:
                    numeric = float(value)
                except Exception:
                    invalids.setdefault(index, []).append(f'{self._field_label(field)} is not numeric')
                    continue
                if numeric < low or numeric > high:
                    invalids.setdefault(index, []).append(f'{self._field_label(field)} {numeric:g} {unit}')
        for index, values in sorted(invalids.items()):
            issues.append(f'Air sensor {index + 1} is reporting impossible values: {self._format_list(values)}.')
        return issues

    def _pm_sensor_issues(self, record: Dict[str, Any], station: Dict[str, Any]) -> List[str]:
        count = self._expected_sensor_count(station, 'particulate_matter')
        if count <= 0:
            return []
        missing = self._missing_sensor_fields(record, 'particulate_matter', self.PM_FIELDS, count)
        issues: List[str] = []
        for index, fields in sorted(missing.items()):
            fields_text = self._format_list([self._field_label(field) for field in fields])
            issues.append(f'Particulate matter sensor {index + 1} is not sending {fields_text} data.')
        return issues

    def _iot_sensor_issues(self, record: Dict[str, Any], station: Dict[str, Any]) -> List[str]:
        return [
            *self._co2_sensor_issues(record, station),
            *self._air_sensor_issues(record, station),
            *self._pm_sensor_issues(record, station),
        ]

    def _check_drift(self, record: Dict[str, Any], station: Dict[str, Any], issues: List[str]) -> None:
        if station['device_type'] != 'IoTBox':
            return
        threshold = 5.0
        air = [record.get('air_sensor+0'), record.get('air_sensor+1')]
        if isinstance(air[0], dict) and isinstance(air[1], dict):
            for key in ('humidity', 'temperature', 'pressure'):
                diff = self._percent_diff(air[0].get(key), air[1].get(key))
                if diff is not None and diff > threshold:
                    issues.append(f'Potential sensor drift: air sensor 1 and 2 {self._field_label(key)} readings differ by {diff:.1f}%.')
        co2 = [record.get('co2_sensor+0'), record.get('co2_sensor+1')]
        if isinstance(co2[0], dict) and isinstance(co2[1], dict):
            diff = self._percent_diff(co2[0].get('co2'), co2[1].get('co2'))
            if diff is not None and diff > threshold:
                issues.append(f'Potential sensor drift: CO2 sensor 1 and 2 readings differ by {diff:.1f}%.')

    def _null_fields(self, record: Dict[str, Any], station: Optional[Dict[str, Any]] = None) -> List[str]:
        ignore = set(self.TS_CANDIDATES + ['_id'])
        optional = self.OPTIONAL_NULL_FIELDS.get((station or {}).get('device_type'), set())
        found: List[str] = []

        def walk(node: Any, prefix: str = '') -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    name = f'{prefix}.{key}' if prefix else key
                    if key in ignore:
                        continue
                    if name in optional or key in optional:
                        continue
                    if key == 'gps' or name.startswith('gps.') or (prefix == '' and key in {'lat', 'long'}):
                        continue
                    walk(value, name)
            elif isinstance(node, list):
                for idx, value in enumerate(node):
                    walk(value, f'{prefix}[{idx}]')
            else:
                if node is None or node == 'null':
                    found.append(prefix)

        walk(record)
        return found

    def _issues_for_record(self, record: Optional[Dict[str, Any]], station: Dict[str, Any]) -> Tuple[Optional[datetime], List[str]]:
        issues: List[str] = []
        if not record:
            return None, ['No records were found in the station collection.']

        ts_value = None
        for field in self.TS_CANDIDATES:
            if field in record:
                ts_value = record.get(field)
                break
        record_ts = self._parse_ts(ts_value)
        if record_ts is None:
            issues.append('The latest record has no readable timestamp, so data freshness cannot be verified.')
        else:
            record_ts = self.repo._station_actual_datetime(station, record_ts)
            age = self._now_utc() - record_ts
            threshold = timedelta(hours=self.settings.stale_threshold_hours)
            if age > threshold:
                issues.append(f'Latest data: {self.repo._human_dt(record_ts)}. This station has not reported within the past {self.settings.stale_threshold_hours} hours.')

        if station['device_type'] == 'IoTBox':
            issues.extend(self._iot_sensor_issues(record, station))
        else:
            nulls = self._null_fields(record, station)
            if nulls:
                preview = ', '.join(nulls[:8])
                issues.append(f'Some latest-record fields are missing values: {preview}' + ('...' if len(nulls) > 8 else ''))

        self._check_drift(record, station, issues)
        return record_ts, issues

    def _type_rank(self, device_type: str) -> int:
        try:
            return self.TYPE_ORDER.index(device_type)
        except ValueError:
            return len(self.TYPE_ORDER)

    def _type_label(self, device_type: str) -> str:
        return self.TYPE_LABELS.get(device_type, self.repo.DEVICE_LABELS.get(device_type, device_type or 'Other Stations'))

    def _status_class(self, status: str) -> str:
        if status == 'Maintenance':
            return 'maintenance'
        return ''

    def _summary_status(self, row_status: str, issues: List[str]) -> str:
        if row_status == 'Maintenance' or issues:
            return 'maintenance'
        return 'healthy'

    def _campaign_row(self, station: Dict[str, Any]) -> Dict[str, Any]:
        extent = self.repo.get_time_extent(station)
        status = station.get('status') or 'Available'
        if status not in {'Active', 'Maintenance'}:
            status = 'Active'
        if status == 'Maintenance':
            issues = ['Station metadata marks this station as maintenance.']
        else:
            issues = []
        return {
            'station_id': station['public_id'],
            'public_id': station['public_id'],
            'name': station['name'],
            'device_type': station['device_type'],
            'device_label': station['device_label'],
            'group_order': self._type_rank(station['device_type']),
            'group_label': self._type_label(station['device_type']),
            'status': status,
            'status_class': self._status_class(status),
            'last_update': extent.get('latest') or 'N/A',
            'issues': issues,
            'issue_count': len(issues),
        }

    def _live_row(self, station: Dict[str, Any]) -> Dict[str, Any]:
        collection_name, _ = self.repo._collection_for_station(station)
        record, _ = self._latest_record(collection_name) if collection_name else (None, None)
        record_ts, issues = self._issues_for_record(record, station)
        computed_status = 'Maintenance' if issues else 'Active'
        return {
            'station_id': station['public_id'],
            'public_id': station['public_id'],
            'name': station['name'],
            'device_type': station['device_type'],
            'device_label': station['device_label'],
            'group_order': self._type_rank(station['device_type']),
            'group_label': self._type_label(station['device_type']),
            'status': computed_status,
            'status_class': self._status_class(computed_status),
            'last_update': self.repo._human_dt(record_ts),
            'issues': issues,
            'issue_count': len(issues),
        }

    def network_status(self) -> Dict[str, Any]:
        cache_key = 'network_status_all_types_v7'
        cached = self.repo.cache.get(cache_key)
        if cached:
            return cached

        docs = list(
            self.db[self.settings.mongo_stations_info_collection].find(
                self.repo._visible_station_filter(),
                self.repo.station_projection,
            )
        )
        stations = [self.repo._normalize_station(doc) for doc in docs if not self.repo._is_hidden_station_doc(doc)]
        rows: List[Dict[str, Any]] = []
        summary = {'total': 0, 'healthy': 0, 'maintenance': 0}

        for station in stations:
            summary['total'] += 1
            row = self._live_row(station) if station['device_type'] in self.LIVE_TYPES else self._campaign_row(station)
            summary[self._summary_status(row['status'], row['issues'])] += 1
            rows.append(row)

        rows.sort(key=lambda item: (item['group_order'], item['name']))
        groups = []
        for device_type in self.TYPE_ORDER:
            group_rows = [row for row in rows if row['device_type'] == device_type]
            if not group_rows:
                continue
            groups.append(
                {
                    'device_type': device_type,
                    'label': self._type_label(device_type),
                    'count': len(group_rows),
                    'rows': group_rows,
                }
            )
        other_rows = [row for row in rows if row['device_type'] not in self.TYPE_ORDER]
        if other_rows:
            groups.append({'device_type': 'Other', 'label': 'Other Stations', 'count': len(other_rows), 'rows': other_rows})

        payload = {'summary': summary, 'rows': rows, 'groups': groups}
        self.repo.cache.set(cache_key, payload, ttl_seconds=120)
        return payload
