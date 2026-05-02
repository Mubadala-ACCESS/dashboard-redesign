from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Optional

import orjson
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, ORJSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .metadata_service import MetadataService
from .mongo_service import MongoDashboardRepository
from .settings import Settings, get_settings
from .status_service import StatusService

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / 'frontend'
TEMPLATES_DIR = FRONTEND_DIR / 'templates'
STATIC_DIR = FRONTEND_DIR / 'static'
APP_DIR = BASE_DIR / 'app'


def orjson_dumps(value, *, default=None, **kwargs):
    kwargs.pop('sort_keys', None)
    return orjson.dumps(value, default=default).decode()


def parse_metric_list(metrics: Optional[str]) -> list[str]:
    if not metrics:
        return []
    delimiter = '|' if '|' in metrics else ','
    return [item for item in metrics.split(delimiter) if item]


def require_public_station_ref(repo: MongoDashboardRepository, station_id: str) -> dict:
    summary = repo.get_station_summary(station_id)
    if station_id != summary.get('public_id'):
        raise KeyError('Station not found.')
    return summary


def require_public_station(repo: MongoDashboardRepository, station_id: str) -> dict:
    station = repo.resolve_station(station_id)
    if station_id != station.get('public_id'):
        raise KeyError('Station not found.')
    return station


def cached_json_response(repo: MongoDashboardRepository, cache_key: str, producer, ttl_seconds: int = 30) -> Response:
    full_key = f'api_json:{cache_key}'
    cached = repo.cache.get(full_key)
    if cached is not None:
        return Response(content=cached, media_type='application/json')
    payload = repo.public_payload(producer())
    content = orjson.dumps(payload)
    repo.cache.set(full_key, content, ttl_seconds=ttl_seconds)
    return Response(content=content, media_type='application/json')


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version='2.0.0', default_response_class=ORJSONResponse)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )
    app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.policies['json.dumps_function'] = orjson_dumps
    app.state.templates = templates

    @app.get('/health')
    def health(repo: MongoDashboardRepository = Depends(get_repo)):
        return {'service': settings.app_name, **repo.healthcheck()}

    @app.get('/', response_class=HTMLResponse)
    def home(request: Request):
        return templates.TemplateResponse(request, 'index.html', {
            'app_name': settings.app_name,
            'page_title': 'Map',
            'network_summary': {},
        })

    @app.get('/get-started', response_class=HTMLResponse)
    def get_started(request: Request, repo: MongoDashboardRepository = Depends(get_repo)):
        return templates.TemplateResponse(request, 'get_started.html', {
            'app_name': settings.app_name,
            'page_title': 'Get Started',
            'glossary': repo.metadata_service.glossary(),
            'metadata_catalog': repo.metadata_service.metadata_catalog(),
        })

    @app.get('/glossary')
    def glossary_redirect():
        return RedirectResponse(url='/get-started', status_code=307)

    @app.get('/support')
    def support_redirect():
        return RedirectResponse(url='/get-started', status_code=307)

    @app.get('/status', response_class=HTMLResponse)
    def status_page(request: Request, repo: MongoDashboardRepository = Depends(get_repo)):
        status = StatusService(repo).network_status()
        return templates.TemplateResponse(request, 'status.html', {
            'app_name': settings.app_name,
            'page_title': 'Status',
            'status_summary': status['summary'],
            'status_rows': status['rows'],
            'status_groups': status['groups'],
        })

    @app.get('/alerts')
    def alerts_redirect():
        return RedirectResponse(url='/status', status_code=307)

    @app.get('/station/{station_id}', response_class=HTMLResponse)
    def station_page(request: Request, station_id: str, repo: MongoDashboardRepository = Depends(get_repo)):
        try:
            summary = repo.get_station_summary(station_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc
        if station_id != summary.get('public_id'):
            return RedirectResponse(url=f"/station/{summary['public_id']}", status_code=302)
        station_templates = {
            'Fidas_Palas': 'fidas_station.html',
            'Meteorological': 'meteostation_station.html',
            'Buoy': 'buoy_station.html',
        }
        template_name = station_templates.get(summary.get('device_type'), 'station.html')
        return templates.TemplateResponse(request, template_name, {
            'app_name': settings.app_name,
            'page_title': summary['name'],
            'station': repo.public_payload(summary),
        })

    @app.get('/station/{station_id}/report')
    def report_redirect(station_id: str, repo: MongoDashboardRepository = Depends(get_repo)):
        try:
            summary = repo.get_station_summary(station_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc
        return RedirectResponse(url=f"/station/{summary['public_id']}", status_code=307)

    @app.get('/api/map/filters')
    def api_map_filters(repo: MongoDashboardRepository = Depends(get_repo)):
        return repo.get_filters()

    @app.get('/api/map/stations')
    def api_map_stations(
        privacy: str = Query(default='all'),
        device_type: str = Query(default='all'),
        status: str = Query(default='all'),
        search: str = Query(default=''),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'map_stations:{privacy}:{device_type}:{status}:{search.strip().lower()}'
        return cached_json_response(repo, key, lambda: repo.list_stations(privacy=privacy, device_type=device_type, status=status, search=search), ttl_seconds=30)

    @app.get('/api/status')
    def api_status(repo: MongoDashboardRepository = Depends(get_repo)):
        return StatusService(repo).network_status()

    @app.get('/api/stations/{station_id}')
    def api_station_summary(station_id: str, repo: MongoDashboardRepository = Depends(get_repo)):
        try:
            summary = require_public_station_ref(repo, station_id)
            return cached_json_response(repo, f'summary:{station_id}', lambda: summary, ttl_seconds=30)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc

    @app.get('/api/stations/{station_id}/metadata')
    def api_station_metadata(station_id: str, repo: MongoDashboardRepository = Depends(get_repo)):
        try:
            summary = require_public_station_ref(repo, station_id)
            return cached_json_response(repo, f'metadata:{station_id}', lambda: repo.get_metadata_payload(station_id, station=summary), ttl_seconds=60)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc

    @app.get('/api/stations/{station_id}/latest')
    def api_station_latest(
        station_id: str,
        period: str = Query(default='24H'),
        include_trends: bool = Query(default=False),
        include_sensor_trends: bool = Query(default=False),
        clean: bool = Query(default=False),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        try:
            key = f'latest:{station_id}:{period}:{include_trends}:{include_sensor_trends}:{clean}'
            return cached_json_response(
                repo,
                key,
                lambda: repo.get_latest_cards(
                    station_id,
                    period=period,
                    include_trends=include_trends,
                    include_sensor_trends=include_sensor_trends,
                    clean=clean,
                    station=require_public_station(repo, station_id),
                ),
                ttl_seconds=30,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc

    @app.get('/api/stations/{station_id}/timeseries')
    def api_station_timeseries(
        station_id: str,
        period: str = Query(default='24H'),
        aggregation: str = Query(default='raw'),
        metrics: Optional[str] = Query(default=None, description='Pipe- or comma-separated metric keys'),
        split_sensors: bool = Query(default=False),
        clean: bool = Query(default=False),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        metric_list = parse_metric_list(metrics)
        try:
            key = f'timeseries:{station_id}:{period}:{aggregation}:{split_sensors}:{clean}:{metrics or ""}'
            return cached_json_response(
                repo,
                key,
                lambda: repo.get_timeseries(
                    station_id,
                    period=period,
                    aggregation=aggregation,
                    metrics=metric_list,
                    split_sensors=split_sensors,
                    clean=clean,
                    station=require_public_station(repo, station_id),
                ),
                ttl_seconds=30,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc

    @app.get('/api/stations/{station_id}/spectra')
    def api_station_spectra(
        station_id: str,
        period: str = Query(default='24H'),
        max_frames: int = Query(default=700, ge=24, le=1000),
        clean: bool = Query(default=False),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        try:
            key = f'spectra:{station_id}:{period}:{max_frames}:{clean}'
            return cached_json_response(
                repo,
                key,
                lambda: repo.get_fidas_spectra(station_id, period=period, max_frames=max_frames, clean=clean, station=require_public_station(repo, station_id)),
                ttl_seconds=60,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc

    @app.get('/api/stations/{station_id}/profiles')
    def api_station_profiles(
        station_id: str,
        period: str = Query(default='24H'),
        metrics: Optional[str] = Query(default=None, description='Pipe- or comma-separated profile metric keys'),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        metric_list = parse_metric_list(metrics)
        try:
            key = f'profiles:{station_id}:{period}:{metrics or ""}'
            return cached_json_response(
                repo,
                key,
                lambda: repo.get_buoy_profiles(station_id, period=period, metrics=metric_list, station=require_public_station(repo, station_id)),
                ttl_seconds=60,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc

    @app.get('/api/stations/{station_id}/export.csv')
    def api_station_export_csv(
        station_id: str,
        period: str = Query(default='24H'),
        aggregation: str = Query(default='raw'),
        metrics: Optional[str] = Query(default=None),
        split_sensors: bool = Query(default=False),
        clean: bool = Query(default=False),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        metric_list = parse_metric_list(metrics)
        try:
            station = require_public_station(repo, station_id)
            frame = repo.export_frame(station_id, period=period, aggregation=aggregation, metrics=metric_list, split_sensors=split_sensors, clean=clean, station=station)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc
        if frame.empty:
            raise HTTPException(status_code=404, detail='No data available for export.')
        buffer = io.StringIO()
        frame.to_csv(buffer, index=False)
        filename = f'{station_id}_{period}_{aggregation}.csv'
        return StreamingResponse(iter([buffer.getvalue()]), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})

    return app


@lru_cache(maxsize=1)
def get_repo() -> MongoDashboardRepository:
    settings = get_settings()
    metadata_service = MetadataService(APP_DIR)
    return MongoDashboardRepository(settings=settings, metadata_service=metadata_service)


app = create_app()
