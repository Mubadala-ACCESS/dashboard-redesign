from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = Field(default='Mubadala ACCESS EcoMonitor', alias='APP_NAME')
    app_env: str = Field(default='production', alias='APP_ENV')
    app_host: str = Field(default='0.0.0.0', alias='APP_HOST')
    app_port: int = Field(default=8000, alias='APP_PORT')
    app_base_url: str = Field(default='http://localhost:8000', alias='APP_BASE_URL')
    app_secret_key: str = Field(default='change-me', alias='APP_SECRET_KEY')
    cors_origins: str = Field(default='', alias='CORS_ORIGINS')

    mongo_uri: str = Field(default='mongodb://localhost:27017/', alias='MONGO_URI')
    mongo_db_name: str = Field(default='all_stations_db', alias='MONGO_DB_NAME')
    mongo_stations_info_collection: str = Field(default='stations_info', alias='MONGO_STATIONS_INFO_COLLECTION')
    mongo_buoy_collection: str = Field(default='buoy_01', alias='MONGO_BUOY_COLLECTION')
    mongo_meteo_collection: str = Field(default='f1_meteostation', alias='MONGO_METEO_COLLECTION')
    mongo_fidas_collection: str = Field(default='fidas_nyuad', alias='MONGO_FIDAS_COLLECTION')
    mongo_max_pool_size: int = Field(default=30, alias='MONGO_MAX_POOL_SIZE')
    mongo_min_pool_size: int = Field(default=3, alias='MONGO_MIN_POOL_SIZE')
    mongo_server_selection_timeout_ms: int = Field(default=5000, alias='MONGO_SERVER_SELECTION_TIMEOUT_MS')
    mongo_connect_timeout_ms: int = Field(default=5000, alias='MONGO_CONNECT_TIMEOUT_MS')
    mongo_socket_timeout_ms: int = Field(default=15000, alias='MONGO_SOCKET_TIMEOUT_MS')

    cache_ttl_seconds: int = Field(default=60, alias='CACHE_TTL_SECONDS')
    default_timezone: str = Field(default='Asia/Dubai', alias='DEFAULT_TIMEZONE')
    stale_threshold_hours: int = Field(default=6, alias='STALE_THRESHOLD_HOURS')
    default_public_status: str = Field(default='Active', alias='DEFAULT_PUBLIC_STATUS')
    default_map_lat: float = Field(default=24.4539, alias='DEFAULT_MAP_LAT')
    default_map_lon: float = Field(default=54.3773, alias='DEFAULT_MAP_LON')
    default_map_zoom: int = Field(default=9, alias='DEFAULT_MAP_ZOOM')

    @property
    def cors_origins_list(self) -> List[str]:
        configured = self.cors_origins.strip()
        if not configured:
            return [self.app_base_url.rstrip('/')]
        if configured == '*' and self.app_env.lower() != 'development':
            return [self.app_base_url.rstrip('/')]
        return [item.strip().rstrip('/') for item in configured.split(',') if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
