from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .mongo_service import MongoDashboardRepository


class StatusService:
    TS_CANDIDATES = ['datetime', 'Timestamp', 'ts', 'time', 'created_at']
    TYPE_ORDER = [
        'IoTBox',
        'Fidas_Palas',
        'Meteorological',
        'Buoy',
        'SBNTransect',
        'underwater_probe',
        'coral_reef',
        'JWCruise',
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
        if collection_name not in self.db.list_collection_names():
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

    def _check_drift(self, record: Dict[str, Any], station: Dict[str, Any], issues: List[str]) -> None:
        if station['device_type'] != 'IoTBox':
            return
        threshold = 5.0
        air = record.get('air_sensor')
        if isinstance(air, list) and len(air) >= 2 and isinstance(air[0], dict) and isinstance(air[1], dict):
            for key in ('humidity', 'temperature', 'pressure'):
                diff = self._percent_diff(air[0].get(key), air[1].get(key))
                if diff is not None and diff > threshold:
                    issues.append(f'Drift in {key}: {diff:.1f}%')
        co2 = record.get('co2_sensor')
        if isinstance(co2, list) and len(co2) >= 2 and isinstance(co2[0], dict) and isinstance(co2[1], dict):
            diff = self._percent_diff(co2[0].get('co2'), co2[1].get('co2'))
            if diff is not None and diff > threshold:
                issues.append(f'Drift in CO2: {diff:.1f}%')

    def _null_fields(self, record: Dict[str, Any]) -> List[str]:
        ignore = set(self.TS_CANDIDATES + ['_id'])
        found: List[str] = []

        def walk(node: Any, prefix: str = '') -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    name = f'{prefix}.{key}' if prefix else key
                    if key in ignore:
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
            return None, ['No records found']

        ts_value = None
        for field in self.TS_CANDIDATES:
            if field in record:
                ts_value = record.get(field)
                break
        record_ts = self._parse_ts(ts_value)
        if record_ts is None:
            issues.append('Missing or invalid timestamp')
        else:
            age = self._now_utc() - record_ts
            threshold = timedelta(hours=self.settings.stale_threshold_hours)
            if age > threshold:
                issues.append(f'Stale data: {int(age.total_seconds() // 60)} minutes old')

        nulls = self._null_fields(record)
        if nulls:
            preview = ', '.join(nulls[:8])
            issues.append(f'Null fields: {preview}' + ('...' if len(nulls) > 8 else ''))

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
        if status == 'Decommissioned':
            return 'subtle'
        return ''

    def _summary_status(self, row_status: str, issues: List[str]) -> str:
        if row_status == 'Decommissioned':
            return 'decommissioned'
        if row_status == 'Maintenance' or issues:
            return 'maintenance'
        return 'healthy'

    def _campaign_row(self, station: Dict[str, Any]) -> Dict[str, Any]:
        extent = self.repo.get_time_extent(station)
        status = station.get('status') or 'Available'
        if status not in {'Active', 'Maintenance', 'Decommissioned'}:
            status = 'Active'
        if status == 'Maintenance':
            issues = ['Marked for maintenance in station metadata']
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
        if station.get('status') == 'Decommissioned':
            return {
                'station_id': station['public_id'],
                'public_id': station['public_id'],
                'name': station['name'],
                'device_type': station['device_type'],
                'device_label': station['device_label'],
                'group_order': self._type_rank(station['device_type']),
                'group_label': self._type_label(station['device_type']),
                'status': 'Decommissioned',
                'status_class': 'subtle',
                'last_update': 'N/A',
                'issues': [],
                'issue_count': 0,
            }

        collection_name, _ = self.repo._collection_for_station(station)
        record, _ = self._latest_record(collection_name) if collection_name else (None, None)
        record_ts, issues = self._issues_for_record(record, station)
        if station.get('status') == 'Maintenance' and 'Marked for maintenance in station metadata' not in issues:
            issues.append('Marked for maintenance in station metadata')
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
        cache_key = 'network_status_all_types_v1'
        cached = self.repo.cache.get(cache_key)
        if cached:
            return cached

        docs = list(self.db[self.settings.mongo_stations_info_collection].find({}, self.repo.station_projection))
        stations = [self.repo._normalize_station(doc) for doc in docs]
        rows: List[Dict[str, Any]] = []
        summary = {'total': 0, 'healthy': 0, 'maintenance': 0, 'decommissioned': 0}

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
