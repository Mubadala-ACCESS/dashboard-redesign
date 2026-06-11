from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


class MetadataService:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.metadata_dir = base_dir / 'data' / 'metadata'
        self._metadata_index = {
            'IoTBox': ['iotbox_metadata.json'],
            'Meteorological': ['meteostation_metadata.json'],
            'Buoy': ['buoy_metadata.json'],
            'SpotterBuoy': ['spotter_buoy_metadata.json'],
            'Fidas_Palas': ['fidas_metadata.json'],
            'SBNTransect': ['exo_metadata.json', 'idronaut_metadata.json'],
            'JWCruise': ['exo_metadata.json', 'idronaut_metadata.json', 'ead_ctd_metadata.json'],
            'underwater_probe': ['exo_metadata.json'],
            'coral_reef': ['coral_reef_metadata.json'],
        }
        self._display_names = {
            'iotbox_metadata.json': 'IoT Box',
            'meteostation_metadata.json': 'Meteorological Station',
            'buoy_metadata.json': 'Buoy',
            'spotter_buoy_metadata.json': 'Sofar Spotter Buoy',
            'fidas_metadata.json': 'Fidas Palas 200S',
            'exo_metadata.json': 'EXO Sonde 2',
            'idronaut_metadata.json': 'Idronaut',
            'ead_ctd_metadata.json': 'EAD CTD',
            'coral_reef_metadata.json': 'Coral Reef Monitoring',
        }
        self._glossary_file = base_dir / 'data' / 'glossary.json'
        self._thresholds_file = base_dir / 'data' / 'thresholds.json'

    def read_json(self, filename: str) -> Any:
        path = self.metadata_dir / filename
        if not path.exists():
            return []
        content = path.read_text(encoding='utf-8').strip()
        if not content:
            return []
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return []

    def metadata_tabs_for_device(self, device_type: str) -> List[Dict[str, Any]]:
        tabs: List[Dict[str, Any]] = []
        for filename in self._metadata_index.get(device_type, []):
            items = self.read_json(filename)
            tabs.append(
                {
                    'file': filename,
                    'label': self._display_names.get(filename, filename.replace('_metadata.json', '').replace('_', ' ').title()),
                    'items': items,
                }
            )
        return tabs

    def special_availability(self) -> Dict[str, Dict[str, str]]:
        rows = self.read_json('available_data.json')
        return {row['station_type']: row for row in rows}

    def glossary(self) -> List[Dict[str, Any]]:
        return json.loads(self._glossary_file.read_text(encoding='utf-8'))

    def metadata_catalog(self) -> List[Dict[str, Any]]:
        catalog: List[Dict[str, Any]] = []
        seen_files: set[str] = set()
        for filenames in self._metadata_index.values():
            for filename in filenames:
                if filename in seen_files:
                    continue
                seen_files.add(filename)
                items = self.read_json(filename)
                catalog.append(
                    {
                        'file': filename,
                        'label': self._display_names.get(filename, filename.replace('_metadata.json', '').replace('_', ' ').title()),
                        'items': items,
                    }
                )
        return catalog

    def thresholds(self) -> Dict[str, Any]:
        return json.loads(self._thresholds_file.read_text(encoding='utf-8'))
