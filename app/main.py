from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Optional

import orjson
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
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


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version='2.0.0', default_response_class=JSONResponse)
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
    def home(request: Request, repo: MongoDashboardRepository = Depends(get_repo)):
        return templates.TemplateResponse(request, 'index.html', {
            'app_name': settings.app_name,
            'page_title': 'Map',
            'network_summary': repo.get_network_summary(),
        })

    @app.get('/get-started', response_class=HTMLResponse)
    def get_started(request: Request, repo: MongoDashboardRepository = Depends(get_repo)):
        return templates.TemplateResponse(request, 'get_started.html', {
            'app_name': settings.app_name,
            'page_title': 'Get Started',
            'glossary': repo.metadata_service.glossary(),
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
        })

    @app.get('/alerts')
    def alerts_redirect():
        return RedirectResponse(url='/status', status_code=307)

    @app.get('/station/{station_id}', response_class=HTMLResponse)
    def station_page(request: Request, station_id: str, repo: MongoDashboardRepository = Depends(get_repo)):
        try:
            summary = repo.get_station_summary(station_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        station_templates = {
            'Fidas_Palas': 'fidas_station.html',
            'Meteorological': 'meteostation_station.html',
            'Buoy': 'buoy_station.html',
        }
        template_name = station_templates.get(summary.get('device_type'), 'station.html')
        return templates.TemplateResponse(request, template_name, {
            'app_name': settings.app_name,
            'page_title': summary['name'],
            'station': summary,
        })

    @app.get('/station/{station_id}/report')
    def report_redirect(station_id: str):
        return RedirectResponse(url=f'/station/{station_id}', status_code=307)

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
        return repo.list_stations(privacy=privacy, device_type=device_type, status=status, search=search)

    @app.get('/api/status')
    def api_status(repo: MongoDashboardRepository = Depends(get_repo)):
        return StatusService(repo).network_status()

    @app.get('/api/stations/{station_id}')
    def api_station_summary(station_id: str, repo: MongoDashboardRepository = Depends(get_repo)):
        try:
            return repo.get_station_summary(station_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get('/api/stations/{station_id}/metadata')
    def api_station_metadata(station_id: str, repo: MongoDashboardRepository = Depends(get_repo)):
        try:
            return repo.get_metadata_payload(station_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
            return repo.get_latest_cards(
                station_id,
                period=period,
                include_trends=include_trends,
                include_sensor_trends=include_sensor_trends,
                clean=clean,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get('/api/stations/{station_id}/timeseries')
    def api_station_timeseries(
        station_id: str,
        period: str = Query(default='24H'),
        aggregation: str = Query(default='raw'),
        metrics: Optional[str] = Query(default=None, description='Comma-separated metric keys'),
        split_sensors: bool = Query(default=False),
        clean: bool = Query(default=False),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        metric_list = [item for item in (metrics.split(',') if metrics else []) if item]
        try:
            return repo.get_timeseries(station_id, period=period, aggregation=aggregation, metrics=metric_list, split_sensors=split_sensors, clean=clean)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get('/api/stations/{station_id}/spectra')
    def api_station_spectra(
        station_id: str,
        period: str = Query(default='24H'),
        max_frames: int = Query(default=700, ge=24, le=1000),
        clean: bool = Query(default=False),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        try:
            return repo.get_fidas_spectra(station_id, period=period, max_frames=max_frames, clean=clean)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get('/api/stations/{station_id}/profiles')
    def api_station_profiles(
        station_id: str,
        period: str = Query(default='24H'),
        metrics: Optional[str] = Query(default=None, description='Comma-separated profile metric keys'),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        metric_list = [item for item in (metrics.split(',') if metrics else []) if item]
        try:
            return repo.get_buoy_profiles(station_id, period=period, metrics=metric_list)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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
        metric_list = [item for item in (metrics.split(',') if metrics else []) if item]
        frame = repo.export_frame(station_id, period=period, aggregation=aggregation, metrics=metric_list, split_sensors=split_sensors, clean=clean)
        if frame.empty:
            raise HTTPException(status_code=404, detail='No data available for export.')
        buffer = io.StringIO()
        frame.to_csv(buffer, index=False)
        filename = f'{station_id}_{period}_{aggregation}.csv'
        return StreamingResponse(iter([buffer.getvalue()]), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})

    @app.get('/api/stations/{station_id}/export.json')
    def api_station_export_json(
        station_id: str,
        period: str = Query(default='24H'),
        aggregation: str = Query(default='raw'),
        metrics: Optional[str] = Query(default=None),
        split_sensors: bool = Query(default=False),
        clean: bool = Query(default=False),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        metric_list = [item for item in (metrics.split(',') if metrics else []) if item]
        frame = repo.export_frame(station_id, period=period, aggregation=aggregation, metrics=metric_list, split_sensors=split_sensors, clean=clean)
        if frame.empty:
            raise HTTPException(status_code=404, detail='No data available for export.')
        return Response(orjson.dumps(frame.to_dict(orient='records')), media_type='application/json')

    return app


@lru_cache(maxsize=1)
def get_repo() -> MongoDashboardRepository:
    settings = get_settings()
    metadata_service = MetadataService(APP_DIR)
    return MongoDashboardRepository(settings=settings, metadata_service=metadata_service)


app = create_app()
