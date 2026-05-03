from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import orjson
from fastapi import Body, Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, ORJSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .metadata_service import MetadataService
from .auth_service import AuthContext, AuthError, AuthService
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


class StationAuthRequired(Exception):
    def __init__(self, station: dict):
        self.station = station


class StationAccessDenied(Exception):
    def __init__(self, station: dict):
        self.station = station


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


def login_url_for(request: Request, next_url: Optional[str] = None) -> str:
    target = next_url or request.url.path
    if request.url.query and not next_url:
        target = f'{target}?{request.url.query}'
    return f'/login?next={quote(target, safe="/")}'


def station_auth_response(request: Request, auth: AuthService, station: dict) -> Response:
    login_url = login_url_for(request, f"/station/{station.get('public_id')}")
    if 'application/json' in request.headers.get('accept', ''):
        return JSONResponse(
            {'detail': 'Authentication required for this private station.', 'login_url': login_url},
            status_code=401,
        )
    return RedirectResponse(url=login_url, status_code=303)


def require_station_access(
    request: Request,
    repo: MongoDashboardRepository,
    auth: AuthService,
    station_id: str,
    summary: bool = False,
) -> dict:
    fresh_station = repo.resolve_station_fresh(station_id)
    if station_id != fresh_station.get('public_id'):
        raise KeyError('Station not found.')
    station = repo.get_station_summary(station_id) if summary else fresh_station
    station['is_public'] = fresh_station.get('is_public', station.get('is_public', True))
    station['privacy'] = fresh_station.get('privacy', station.get('privacy', 'Public'))
    ctx = auth.load_context(request)
    if auth.can_access_station(ctx, fresh_station):
        return station
    if not ctx.is_authenticated:
        raise StationAuthRequired(station)
    raise StationAccessDenied(station)


def require_family_access(request: Request, auth: AuthService, device_type: str) -> None:
    ctx = auth.load_context(request)
    if auth.can_access_station_family(ctx, device_type):
        return
    if not ctx.is_authenticated:
        raise HTTPException(status_code=401, detail='Authentication required for this private station family.')
    raise HTTPException(status_code=403, detail='You do not have access to this private station family.')


def require_admin_context(request: Request, auth: AuthService) -> AuthContext:
    ctx = auth.load_context(request)
    if not ctx.is_authenticated:
        raise HTTPException(status_code=401, detail='Authentication required.')
    permissions = set(auth.user_acl(ctx.user)['permissions'])
    if 'admin:all' not in permissions:
        raise HTTPException(status_code=403, detail='Admin access required.')
    return ctx


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

    def render_login(
        request: Request,
        auth: AuthService,
        *,
        phase: str = 'password',
        next_url: str = '/',
        error: str = '',
        challenge: str = '',
        username: str = '',
        totp_secret: str = '',
        totp_uri: str = '',
        recovery_codes: Optional[list[str]] = None,
    ) -> HTMLResponse:
        csrf_token = auth.make_anon_csrf_token()
        response = templates.TemplateResponse(request, 'login.html', {
            'app_name': settings.app_name,
            'page_title': 'Sign in',
            'phase': phase,
            'next_url': auth.safe_next_url(next_url),
            'error': error,
            'challenge': challenge,
            'username': username,
            'totp_secret': totp_secret,
            'totp_uri': totp_uri,
            'recovery_codes': recovery_codes or [],
            'csrf_token': csrf_token,
        })
        auth.set_anon_csrf_cookie(response, csrf_token)
        return response

    @app.get('/login', response_class=HTMLResponse)
    def login_page(
        request: Request,
        next: Optional[str] = Query(default='/'),
        auth: AuthService = Depends(get_auth_service),
    ):
        ctx = auth.load_context(request)
        next_url = auth.safe_next_url(next)
        if ctx.is_authenticated:
            return RedirectResponse(url=next_url, status_code=303)
        return render_login(request, auth, next_url=next_url)

    @app.post('/login', response_class=HTMLResponse)
    def login_password(
        request: Request,
        login: str = Form(...),
        password: str = Form(...),
        next_url: str = Form(default='/'),
        csrf_token: str = Form(..., alias='_csrf'),
        auth: AuthService = Depends(get_auth_service),
    ):
        safe_next = auth.safe_next_url(next_url)
        if not auth.verify_anon_csrf(request, csrf_token):
            return render_login(request, auth, next_url=safe_next, error='Your sign-in form expired. Please try again.')
        user = auth.find_user_by_login(login)
        if not user or not auth.verify_password(password, user.get('password_hash', '')):
            return render_login(request, auth, next_url=safe_next, username=login, error='Invalid username or password.')
        if not user.get('totp_enabled') or user.get('require_totp_setup'):
            secret = auth.generate_totp_secret()
            challenge = auth.create_login_challenge(user, 'setup', pending_totp_secret=secret)
            return render_login(
                request,
                auth,
                phase='setup',
                next_url=safe_next,
                challenge=challenge,
                username=user['username'],
                totp_secret=secret,
                totp_uri=auth.totp_uri(user['username'], secret),
            )
        challenge = auth.create_login_challenge(user, 'mfa')
        return render_login(request, auth, phase='mfa', next_url=safe_next, challenge=challenge, username=user['username'])

    @app.post('/login/mfa', response_class=HTMLResponse)
    def login_mfa(
        request: Request,
        challenge: str = Form(...),
        code: str = Form(...),
        next_url: str = Form(default='/'),
        csrf_token: str = Form(..., alias='_csrf'),
        auth: AuthService = Depends(get_auth_service),
    ):
        safe_next = auth.safe_next_url(next_url)
        if not auth.verify_anon_csrf(request, csrf_token):
            return render_login(request, auth, phase='mfa', next_url=safe_next, challenge=challenge, error='Your MFA form expired. Please try again.')
        try:
            user, _ = auth.consume_challenge(challenge, 'mfa')
        except AuthError as exc:
            return render_login(request, auth, next_url=safe_next, error=str(exc))
        if not auth.verify_user_totp_or_recovery(user, code):
            new_challenge = auth.create_login_challenge(user, 'mfa')
            return render_login(request, auth, phase='mfa', next_url=safe_next, challenge=new_challenge, username=user['username'], error='Invalid authenticator or recovery code.')
        signed_cookie, _ = auth.create_session(user, request)
        response = RedirectResponse(url=safe_next, status_code=303)
        auth.set_session_cookie(response, signed_cookie)
        auth.clear_anon_csrf_cookie(response)
        auth.send_security_email(user.get('email', ''), 'Mubadala ACCESS dashboard sign-in', f'A successful sign-in occurred for {user.get("username")} on the dashboard.')
        return response

    @app.post('/login/setup-mfa', response_class=HTMLResponse)
    def login_setup_mfa(
        request: Request,
        challenge: str = Form(...),
        code: str = Form(...),
        next_url: str = Form(default='/'),
        csrf_token: str = Form(..., alias='_csrf'),
        auth: AuthService = Depends(get_auth_service),
    ):
        safe_next = auth.safe_next_url(next_url)
        if not auth.verify_anon_csrf(request, csrf_token):
            return render_login(request, auth, next_url=safe_next, error='Your setup form expired. Please start again.')
        try:
            user, challenge_doc = auth.consume_challenge(challenge, 'setup')
            secret = auth.decrypt_text(challenge_doc['pending_totp_secret'])
        except AuthError as exc:
            return render_login(request, auth, next_url=safe_next, error=str(exc))
        step = auth.verify_totp(secret, code)
        if step is None:
            new_secret = auth.generate_totp_secret()
            new_challenge = auth.create_login_challenge(user, 'setup', pending_totp_secret=new_secret)
            return render_login(
                request,
                auth,
                phase='setup',
                next_url=safe_next,
                challenge=new_challenge,
                username=user['username'],
                totp_secret=new_secret,
                totp_uri=auth.totp_uri(user['username'], new_secret),
                error='The authenticator code was not valid. A new setup secret has been issued.',
            )
        recovery_codes = auth.complete_totp_setup(user, secret, step)
        signed_cookie, session = auth.create_session(user, request)
        response = templates.TemplateResponse(request, 'login.html', {
            'app_name': settings.app_name,
            'page_title': 'Recovery codes',
            'phase': 'recovery',
            'next_url': safe_next,
            'error': '',
            'challenge': '',
            'username': user['username'],
            'totp_secret': '',
            'totp_uri': '',
            'recovery_codes': recovery_codes,
            'csrf_token': session['csrf_token'],
        })
        auth.set_session_cookie(response, signed_cookie)
        auth.clear_anon_csrf_cookie(response)
        return response

    @app.post('/logout')
    def logout(
        request: Request,
        csrf_token: str = Form(..., alias='_csrf'),
        auth: AuthService = Depends(get_auth_service),
    ):
        ctx = auth.load_context(request)
        if ctx.is_authenticated and auth.verify_session_csrf(request, ctx, csrf_token):
            auth.revoke_session(ctx)
        response = RedirectResponse(url='/', status_code=303)
        auth.clear_session_cookie(response)
        return response

    @app.get('/admin', response_class=HTMLResponse)
    def admin_page(request: Request, auth: AuthService = Depends(get_auth_service)):
        ctx = auth.load_context(request)
        if not ctx.is_authenticated:
            return RedirectResponse(url=login_url_for(request, '/admin'), status_code=303)
        permissions = set(auth.user_acl(ctx.user)['permissions'])
        if 'admin:all' not in permissions:
            raise HTTPException(status_code=403, detail='Admin access required.')
        return templates.TemplateResponse(request, 'admin.html', {
            'app_name': settings.app_name,
            'page_title': 'Access control',
            'user': ctx.user,
            'csrf_token': ctx.session['csrf_token'],
        })

    @app.get('/api/admin/me')
    def api_admin_me(request: Request, auth: AuthService = Depends(get_auth_service)):
        ctx = require_admin_context(request, auth)
        return {
            'user': {
                'username': ctx.user.get('username'),
                'email': ctx.user.get('email'),
                'acl': auth.user_acl(ctx.user),
            },
            'csrf_token': ctx.session.get('csrf_token'),
        }

    @app.get('/api/admin/users')
    def api_admin_users(request: Request, auth: AuthService = Depends(get_auth_service)):
        require_admin_context(request, auth)
        users = []
        for user in auth.db[auth.USERS].find({}, {'password_hash': 0, 'totp_secret': 0, 'recovery_codes': 0}):
            users.append({
                'id': str(user.get('_id')),
                'username': user.get('username'),
                'email': user.get('email'),
                'groups': user.get('groups') or [],
                'permissions': user.get('permissions') or [],
                'station_acl': user.get('station_acl') or [],
                'totp_enabled': bool(user.get('totp_enabled')),
                'disabled': bool(user.get('disabled_at')),
            })
        return {'users': users}

    @app.get('/api/admin/groups')
    def api_admin_groups(request: Request, auth: AuthService = Depends(get_auth_service)):
        require_admin_context(request, auth)
        groups = []
        for group in auth.db[auth.GROUPS].find({}, {'_id': 0}):
            groups.append(group)
        return {'groups': groups}

    @app.post('/api/admin/groups')
    def api_admin_upsert_group(
        request: Request,
        payload: dict = Body(...),
        x_csrf_token: Optional[str] = Header(default=None, alias='x-csrf-token'),
        auth: AuthService = Depends(get_auth_service),
    ):
        ctx = require_admin_context(request, auth)
        if not auth.verify_session_csrf(request, ctx, x_csrf_token):
            raise HTTPException(status_code=403, detail='CSRF validation failed.')
        name = str(payload.get('name') or '').strip()
        if not name:
            raise HTTPException(status_code=400, detail='Group name is required.')
        auth.ensure_group(
            name,
            permissions=[str(item) for item in payload.get('permissions') or []],
            station_acl=payload.get('station_acl') or [],
        )
        return {'ok': True}

    @app.post('/api/admin/users')
    def api_admin_upsert_user(
        request: Request,
        payload: dict = Body(...),
        x_csrf_token: Optional[str] = Header(default=None, alias='x-csrf-token'),
        auth: AuthService = Depends(get_auth_service),
    ):
        ctx = require_admin_context(request, auth)
        if not auth.verify_session_csrf(request, ctx, x_csrf_token):
            raise HTTPException(status_code=403, detail='CSRF validation failed.')
        try:
            user = auth.upsert_user(
                username=str(payload.get('username') or ''),
                email=str(payload.get('email') or ''),
                password=str(payload.get('password') or ''),
                groups=[str(item) for item in payload.get('groups') or []],
                permissions=[str(item) for item in payload.get('permissions') or []],
                station_acl=payload.get('station_acl') or [],
                require_totp_setup=True,
            )
        except AuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {'ok': True, 'user': {'id': str(user.get('_id')), 'username': user.get('username'), 'email': user.get('email')}}

    @app.get('/station/{station_id}', response_class=HTMLResponse)
    def station_page(
        request: Request,
        station_id: str,
        repo: MongoDashboardRepository = Depends(get_repo),
        auth: AuthService = Depends(get_auth_service),
    ):
        try:
            summary = repo.get_station_summary(station_id)
            fresh_station = repo.resolve_station_fresh(station_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc
        if station_id != summary.get('public_id'):
            return RedirectResponse(url=f"/station/{summary['public_id']}", status_code=302)
        summary['is_public'] = fresh_station.get('is_public', summary.get('is_public', True))
        summary['privacy'] = fresh_station.get('privacy', summary.get('privacy', 'Public'))
        ctx = auth.load_context(request)
        if not auth.can_access_station(ctx, fresh_station):
            if not ctx.is_authenticated:
                return station_auth_response(request, auth, summary)
            raise HTTPException(status_code=403, detail='You do not have access to this private station.')
        station_templates = {
            'Fidas_Palas': 'fidas_station.html',
            'Meteorological': 'meteostation_station.html',
            'Buoy': 'buoy_station.html',
            'underwater_probe': 'underwater.html',
            'SBNTransect': 'sbn_stations.html',
            'JWCruise': 'jw_stations.html',
        }
        template_name = station_templates.get(summary.get('device_type'), 'station.html')
        return templates.TemplateResponse(request, template_name, {
            'app_name': settings.app_name,
            'page_title': summary['name'],
            'station': repo.public_payload(summary),
        })

    @app.get('/station/{station_id}/report')
    def report_redirect(
        request: Request,
        station_id: str,
        repo: MongoDashboardRepository = Depends(get_repo),
        auth: AuthService = Depends(get_auth_service),
    ):
        try:
            summary = repo.get_station_summary(station_id)
            fresh_station = repo.resolve_station_fresh(station_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc
        if not auth.can_access_station(auth.load_context(request), fresh_station):
            return station_auth_response(request, auth, summary)
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
        return cached_json_response(repo, key, lambda: repo.list_stations(privacy=privacy, device_type=device_type, status=status, search=search), ttl_seconds=10)

    @app.get('/api/status')
    def api_status(repo: MongoDashboardRepository = Depends(get_repo)):
        return StatusService(repo).network_status()

    @app.get('/api/stations/{station_id}')
    def api_station_summary(
        request: Request,
        station_id: str,
        repo: MongoDashboardRepository = Depends(get_repo),
        auth: AuthService = Depends(get_auth_service),
    ):
        try:
            summary = require_public_station_ref(repo, station_id)
            return cached_json_response(repo, f'summary:{station_id}', lambda: summary, ttl_seconds=30)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc

    @app.get('/api/stations/{station_id}/metadata')
    def api_station_metadata(
        request: Request,
        station_id: str,
        repo: MongoDashboardRepository = Depends(get_repo),
        auth: AuthService = Depends(get_auth_service),
    ):
        try:
            summary = require_public_station_ref(repo, station_id)
            return cached_json_response(repo, f'metadata:{station_id}', lambda: repo.get_metadata_payload(station_id, station=summary), ttl_seconds=60)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc

    @app.get('/api/stations/{station_id}/latest')
    def api_station_latest(
        request: Request,
        station_id: str,
        period: str = Query(default='24H'),
        start_date: Optional[str] = Query(default=None),
        end_date: Optional[str] = Query(default=None),
        include_trends: bool = Query(default=False),
        include_sensor_trends: bool = Query(default=False),
        clean: bool = Query(default=False),
        repo: MongoDashboardRepository = Depends(get_repo),
        auth: AuthService = Depends(get_auth_service),
    ):
        try:
            station = require_station_access(request, repo, auth, station_id)
            key = f'latest:{station_id}:{period}:{start_date or ""}:{end_date or ""}:{include_trends}:{include_sensor_trends}:{clean}'
            return cached_json_response(
                repo,
                key,
                lambda: repo.get_latest_cards(
                    station_id,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    include_trends=include_trends,
                    include_sensor_trends=include_sensor_trends,
                    clean=clean,
                    station=station,
                ),
                ttl_seconds=30,
            )
        except StationAuthRequired as exc:
            return station_auth_response(request, auth, exc.station)
        except StationAccessDenied as exc:
            raise HTTPException(status_code=403, detail='You do not have access to this private station.') from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc

    @app.get('/api/stations/{station_id}/timeseries')
    def api_station_timeseries(
        request: Request,
        station_id: str,
        period: str = Query(default='24H'),
        start_date: Optional[str] = Query(default=None),
        end_date: Optional[str] = Query(default=None),
        aggregation: str = Query(default='raw'),
        metrics: Optional[str] = Query(default=None, description='Pipe- or comma-separated metric keys'),
        split_sensors: bool = Query(default=False),
        clean: bool = Query(default=False),
        repo: MongoDashboardRepository = Depends(get_repo),
        auth: AuthService = Depends(get_auth_service),
    ):
        metric_list = parse_metric_list(metrics)
        try:
            station = require_station_access(request, repo, auth, station_id)
            key = f'timeseries:{station_id}:{period}:{start_date or ""}:{end_date or ""}:{aggregation}:{split_sensors}:{clean}:{metrics or ""}'
            return cached_json_response(
                repo,
                key,
                lambda: repo.get_timeseries(
                    station_id,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    aggregation=aggregation,
                    metrics=metric_list,
                    split_sensors=split_sensors,
                    clean=clean,
                    station=station,
                ),
                ttl_seconds=30,
            )
        except StationAuthRequired as exc:
            return station_auth_response(request, auth, exc.station)
        except StationAccessDenied as exc:
            raise HTTPException(status_code=403, detail='You do not have access to this private station.') from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc

    @app.get('/api/stations/{station_id}/spectra')
    def api_station_spectra(
        request: Request,
        station_id: str,
        period: str = Query(default='24H'),
        start_date: Optional[str] = Query(default=None),
        end_date: Optional[str] = Query(default=None),
        max_frames: int = Query(default=700, ge=24, le=1000),
        clean: bool = Query(default=False),
        repo: MongoDashboardRepository = Depends(get_repo),
        auth: AuthService = Depends(get_auth_service),
    ):
        try:
            station = require_station_access(request, repo, auth, station_id)
            key = f'spectra:{station_id}:{period}:{start_date or ""}:{end_date or ""}:{max_frames}:{clean}'
            return cached_json_response(
                repo,
                key,
                lambda: repo.get_fidas_spectra(station_id, period=period, start_date=start_date, end_date=end_date, max_frames=max_frames, clean=clean, station=station),
                ttl_seconds=60,
            )
        except StationAuthRequired as exc:
            return station_auth_response(request, auth, exc.station)
        except StationAccessDenied as exc:
            raise HTTPException(status_code=403, detail='You do not have access to this private station.') from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc

    @app.get('/api/stations/{station_id}/profiles')
    def api_station_profiles(
        request: Request,
        station_id: str,
        period: str = Query(default='24H'),
        start_date: Optional[str] = Query(default=None),
        end_date: Optional[str] = Query(default=None),
        metrics: Optional[str] = Query(default=None, description='Pipe- or comma-separated profile metric keys'),
        repo: MongoDashboardRepository = Depends(get_repo),
        auth: AuthService = Depends(get_auth_service),
    ):
        metric_list = parse_metric_list(metrics)
        try:
            station = require_station_access(request, repo, auth, station_id)
            key = f'profiles:{station_id}:{period}:{start_date or ""}:{end_date or ""}:{metrics or ""}'
            return cached_json_response(
                repo,
                key,
                lambda: repo.get_buoy_profiles(station_id, period=period, start_date=start_date, end_date=end_date, metrics=metric_list, station=station),
                ttl_seconds=60,
            )
        except StationAuthRequired as exc:
            return station_auth_response(request, auth, exc.station)
        except StationAccessDenied as exc:
            raise HTTPException(status_code=403, detail='You do not have access to this private station.') from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc

    @app.get('/api/stations/{station_id}/available-dates')
    def api_station_available_dates(
        request: Request,
        station_id: str,
        repo: MongoDashboardRepository = Depends(get_repo),
        auth: AuthService = Depends(get_auth_service),
    ):
        try:
            station = require_station_access(request, repo, auth, station_id)
            return cached_json_response(
                repo,
                f'available_dates:{station_id}',
                lambda: repo.get_available_dates(station_id, station=station),
                ttl_seconds=300,
            )
        except StationAuthRequired as exc:
            return station_auth_response(request, auth, exc.station)
        except StationAccessDenied as exc:
            raise HTTPException(status_code=403, detail='You do not have access to this private station.') from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc

    @app.get('/api/stations/{station_id}/export.csv')
    def api_station_export_csv(
        request: Request,
        station_id: str,
        period: str = Query(default='24H'),
        start_date: Optional[str] = Query(default=None),
        end_date: Optional[str] = Query(default=None),
        aggregation: str = Query(default='raw'),
        metrics: Optional[str] = Query(default=None),
        split_sensors: bool = Query(default=False),
        clean: bool = Query(default=False),
        append_location: bool = Query(default=False),
        repo: MongoDashboardRepository = Depends(get_repo),
        auth: AuthService = Depends(get_auth_service),
    ):
        metric_list = parse_metric_list(metrics)
        try:
            station = require_station_access(request, repo, auth, station_id)
            csv_iter = repo.export_csv_iter(station_id, period=period, start_date=start_date, end_date=end_date, aggregation=aggregation, metrics=metric_list, split_sensors=split_sensors, clean=clean, append_location=append_location, station=station)
        except StationAuthRequired as exc:
            return station_auth_response(request, auth, exc.station)
        except StationAccessDenied as exc:
            raise HTTPException(status_code=403, detail='You do not have access to this private station.') from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Station not found.') from exc
        if csv_iter is None:
            raise HTTPException(status_code=404, detail='No data available for export.')
        filename = f'{station_id}_{period}_{aggregation}.csv'
        return StreamingResponse(csv_iter, media_type='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})

    def require_sbn_access(request: Request, auth: AuthService = Depends(get_auth_service)):
        require_family_access(request, auth, 'SBNTransect')

    def require_jw_access(request: Request, auth: AuthService = Depends(get_auth_service)):
        require_family_access(request, auth, 'JWCruise')

    @app.get('/api/sbn/options', dependencies=[Depends(require_sbn_access)])
    def api_sbn_options(repo: MongoDashboardRepository = Depends(get_repo)):
        return cached_json_response(repo, 'sbn_options', repo.get_sbn_options, ttl_seconds=300)

    @app.get('/api/sbn/cells', dependencies=[Depends(require_sbn_access)])
    def api_sbn_cells(
        campaign_month: str = Query(...),
        instrument: str = Query(default='combined'),
        depth_bin_m: int = Query(default=0),
        metric: str = Query(...),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'sbn_cells:{campaign_month}:{instrument}:{depth_bin_m}:{metric}'
        return cached_json_response(
            repo,
            key,
            lambda: repo.get_sbn_cells(campaign_month=campaign_month, instrument=instrument, depth_bin_m=depth_bin_m, metric=metric),
            ttl_seconds=60,
        )

    @app.get('/api/sbn/selection', dependencies=[Depends(require_sbn_access)])
    def api_sbn_selection(
        instrument: str = Query(default='combined'),
        campaign_month: Optional[str] = Query(default=None),
        metric: Optional[str] = Query(default=None),
        depth_bin_m: int = Query(default=0),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'sbn_selection:{instrument}:{campaign_month or ""}:{metric or ""}:{depth_bin_m}'
        return cached_json_response(
            repo,
            key,
            lambda: repo.get_sbn_selection(instrument=instrument, campaign_month=campaign_month, metric=metric, depth_bin_m=depth_bin_m),
            ttl_seconds=60,
        )

    @app.get('/api/sbn/trend', dependencies=[Depends(require_sbn_access)])
    def api_sbn_trend(
        waypoint_id: str = Query(...),
        instrument: str = Query(default='combined'),
        depth_bin_m: int = Query(default=0),
        metric: str = Query(...),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        try:
            key = f'sbn_trend:{waypoint_id}:{instrument}:{depth_bin_m}:{metric}'
            return cached_json_response(
                repo,
                key,
                lambda: repo.get_sbn_trend(waypoint_id=waypoint_id, instrument=instrument, depth_bin_m=depth_bin_m, metric=metric),
                ttl_seconds=60,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='SBN waypoint not found.') from exc

    @app.get('/api/sbn/heatmap/depth-waypoint', dependencies=[Depends(require_sbn_access)])
    def api_sbn_depth_waypoint_heatmap(
        campaign_month: str = Query(...),
        instrument: str = Query(default='combined'),
        metric: str = Query(...),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'sbn_depth_waypoint:{campaign_month}:{instrument}:{metric}'
        return cached_json_response(
            repo,
            key,
            lambda: repo.get_sbn_depth_waypoint_heatmap(campaign_month=campaign_month, instrument=instrument, metric=metric),
            ttl_seconds=60,
        )

    @app.get('/api/sbn/heatmap/month-depth', dependencies=[Depends(require_sbn_access)])
    def api_sbn_month_depth_heatmap(
        waypoint_id: str = Query(...),
        instrument: str = Query(default='combined'),
        metric: str = Query(...),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        try:
            key = f'sbn_month_depth:{waypoint_id}:{instrument}:{metric}'
            return cached_json_response(
                repo,
                key,
                lambda: repo.get_sbn_month_depth_heatmap(waypoint_id=waypoint_id, instrument=instrument, metric=metric),
                ttl_seconds=60,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='SBN waypoint not found.') from exc

    @app.get('/api/sbn/heatmap/month-waypoint', dependencies=[Depends(require_sbn_access)])
    def api_sbn_month_waypoint_heatmap(
        instrument: str = Query(default='combined'),
        depth_bin_m: int = Query(default=0),
        metric: str = Query(...),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'sbn_month_waypoint:{instrument}:{depth_bin_m}:{metric}'
        return cached_json_response(
            repo,
            key,
            lambda: repo.get_sbn_month_waypoint_heatmap(instrument=instrument, depth_bin_m=depth_bin_m, metric=metric),
            ttl_seconds=60,
        )

    @app.get('/api/sbn/crossplot', dependencies=[Depends(require_sbn_access)])
    def api_sbn_crossplot(
        campaign_month: str = Query(...),
        instrument: str = Query(default='combined'),
        depth_bin_m: int = Query(default=0),
        x_metric: str = Query(...),
        y_metric: str = Query(...),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'sbn_crossplot:{campaign_month}:{instrument}:{depth_bin_m}:{x_metric}:{y_metric}'
        return cached_json_response(
            repo,
            key,
            lambda: repo.get_sbn_crossplot(campaign_month=campaign_month, instrument=instrument, depth_bin_m=depth_bin_m, x_metric=x_metric, y_metric=y_metric),
            ttl_seconds=60,
        )

    @app.get('/api/sbn/availability', dependencies=[Depends(require_sbn_access)])
    def api_sbn_availability(
        instrument: str = Query(default='combined'),
        depth_bin_m: int = Query(default=0),
        metric: str = Query(...),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'sbn_availability:{instrument}:{depth_bin_m}:{metric}'
        return cached_json_response(
            repo,
            key,
            lambda: repo.get_sbn_availability(instrument=instrument, depth_bin_m=depth_bin_m, metric=metric),
            ttl_seconds=60,
        )

    @app.get('/api/sbn/profiles', dependencies=[Depends(require_sbn_access)])
    def api_sbn_profiles(
        campaign_month: Optional[str] = Query(default=None),
        instrument: Optional[str] = Query(default=None),
        waypoint_id: Optional[str] = Query(default=None),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'sbn_profiles:{campaign_month or ""}:{instrument or ""}:{waypoint_id or ""}'
        return cached_json_response(
            repo,
            key,
            lambda: repo.get_sbn_profiles(campaign_month=campaign_month, instrument=instrument, waypoint_id=waypoint_id),
            ttl_seconds=120,
        )

    @app.get('/api/sbn/export.csv', dependencies=[Depends(require_sbn_access)])
    def api_sbn_export_csv(
        campaign_month: Optional[str] = Query(default=None),
        instrument: str = Query(default='combined'),
        depth_bin_m: Optional[int] = Query(default=None),
        metrics: Optional[str] = Query(default=None),
        all_depths: bool = Query(default=False),
        append_location: bool = Query(default=False),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        metric_list = parse_metric_list(metrics)
        csv_iter = repo.export_sbn_csv_iter(
            campaign_month=campaign_month,
            instrument=instrument,
            depth_bin_m=depth_bin_m,
            metrics=metric_list,
            all_depths=all_depths,
            append_location=append_location,
        )
        month_part = campaign_month if campaign_month and campaign_month.lower() != 'all' else 'all-months'
        depth_part = 'all-depths' if all_depths else f'{depth_bin_m or 0}m'
        filename = f'sbn_{instrument}_{month_part}_{depth_part}.csv'
        return StreamingResponse(csv_iter, media_type='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})

    @app.get('/api/jw/options', dependencies=[Depends(require_jw_access)])
    def api_jw_options(repo: MongoDashboardRepository = Depends(get_repo)):
        return cached_json_response(repo, 'jw_options', repo.get_jw_options, ttl_seconds=300)

    @app.get('/api/jw/cells', dependencies=[Depends(require_jw_access)])
    def api_jw_cells(
        campaign_month: str = Query(...),
        instrument: str = Query(default='combined'),
        depth_bin_m: int = Query(default=0),
        metric: str = Query(...),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'jw_cells:{campaign_month}:{instrument}:{depth_bin_m}:{metric}'
        return cached_json_response(
            repo,
            key,
            lambda: repo.get_jw_cells(campaign_month=campaign_month, instrument=instrument, depth_bin_m=depth_bin_m, metric=metric),
            ttl_seconds=60,
        )

    @app.get('/api/jw/selection', dependencies=[Depends(require_jw_access)])
    def api_jw_selection(
        instrument: str = Query(default='combined'),
        campaign_month: Optional[str] = Query(default=None),
        metric: Optional[str] = Query(default=None),
        depth_bin_m: int = Query(default=0),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'jw_selection:{instrument}:{campaign_month or ""}:{metric or ""}:{depth_bin_m}'
        return cached_json_response(
            repo,
            key,
            lambda: repo.get_jw_selection(instrument=instrument, campaign_month=campaign_month, metric=metric, depth_bin_m=depth_bin_m),
            ttl_seconds=60,
        )

    @app.get('/api/jw/trend', dependencies=[Depends(require_jw_access)])
    def api_jw_trend(
        waypoint_id: str = Query(...),
        instrument: str = Query(default='combined'),
        depth_bin_m: int = Query(default=0),
        metric: str = Query(...),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        try:
            key = f'jw_trend:{waypoint_id}:{instrument}:{depth_bin_m}:{metric}'
            return cached_json_response(
                repo,
                key,
                lambda: repo.get_jw_trend(waypoint_id=waypoint_id, instrument=instrument, depth_bin_m=depth_bin_m, metric=metric),
                ttl_seconds=60,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Jaywun waypoint not found.') from exc

    @app.get('/api/jw/heatmap/depth-waypoint', dependencies=[Depends(require_jw_access)])
    def api_jw_depth_waypoint_heatmap(
        campaign_month: str = Query(...),
        instrument: str = Query(default='combined'),
        metric: str = Query(...),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'jw_depth_waypoint:{campaign_month}:{instrument}:{metric}'
        return cached_json_response(
            repo,
            key,
            lambda: repo.get_jw_depth_waypoint_heatmap(campaign_month=campaign_month, instrument=instrument, metric=metric),
            ttl_seconds=60,
        )

    @app.get('/api/jw/heatmap/month-depth', dependencies=[Depends(require_jw_access)])
    def api_jw_month_depth_heatmap(
        waypoint_id: str = Query(...),
        instrument: str = Query(default='combined'),
        metric: str = Query(...),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        try:
            key = f'jw_month_depth:{waypoint_id}:{instrument}:{metric}'
            return cached_json_response(
                repo,
                key,
                lambda: repo.get_jw_month_depth_heatmap(waypoint_id=waypoint_id, instrument=instrument, metric=metric),
                ttl_seconds=60,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail='Jaywun waypoint not found.') from exc

    @app.get('/api/jw/heatmap/month-waypoint', dependencies=[Depends(require_jw_access)])
    def api_jw_month_waypoint_heatmap(
        instrument: str = Query(default='combined'),
        depth_bin_m: int = Query(default=0),
        metric: str = Query(...),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'jw_month_waypoint:{instrument}:{depth_bin_m}:{metric}'
        return cached_json_response(
            repo,
            key,
            lambda: repo.get_jw_month_waypoint_heatmap(instrument=instrument, depth_bin_m=depth_bin_m, metric=metric),
            ttl_seconds=60,
        )

    @app.get('/api/jw/crossplot', dependencies=[Depends(require_jw_access)])
    def api_jw_crossplot(
        campaign_month: str = Query(...),
        instrument: str = Query(default='combined'),
        depth_bin_m: int = Query(default=0),
        x_metric: str = Query(...),
        y_metric: str = Query(...),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'jw_crossplot:{campaign_month}:{instrument}:{depth_bin_m}:{x_metric}:{y_metric}'
        return cached_json_response(
            repo,
            key,
            lambda: repo.get_jw_crossplot(campaign_month=campaign_month, instrument=instrument, depth_bin_m=depth_bin_m, x_metric=x_metric, y_metric=y_metric),
            ttl_seconds=60,
        )

    @app.get('/api/jw/profiles', dependencies=[Depends(require_jw_access)])
    def api_jw_profiles(
        campaign_month: Optional[str] = Query(default=None),
        instrument: Optional[str] = Query(default=None),
        waypoint_id: Optional[str] = Query(default=None),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        key = f'jw_profiles:{campaign_month or ""}:{instrument or ""}:{waypoint_id or ""}'
        return cached_json_response(
            repo,
            key,
            lambda: repo.get_jw_profiles(campaign_month=campaign_month, instrument=instrument, waypoint_id=waypoint_id),
            ttl_seconds=120,
        )

    @app.get('/api/jw/export.csv', dependencies=[Depends(require_jw_access)])
    def api_jw_export_csv(
        campaign_month: Optional[str] = Query(default=None),
        instrument: str = Query(default='combined'),
        depth_bin_m: Optional[int] = Query(default=None),
        metrics: Optional[str] = Query(default=None),
        all_depths: bool = Query(default=False),
        append_location: bool = Query(default=False),
        repo: MongoDashboardRepository = Depends(get_repo),
    ):
        metric_list = parse_metric_list(metrics)
        csv_iter = repo.export_jw_csv_iter(
            campaign_month=campaign_month,
            instrument=instrument,
            depth_bin_m=depth_bin_m,
            metrics=metric_list,
            all_depths=all_depths,
            append_location=append_location,
        )
        month_part = campaign_month if campaign_month and campaign_month.lower() != 'all' else 'all-months'
        depth_part = 'all-depths' if all_depths else f'{depth_bin_m or 0}m'
        filename = f'jaywun_{instrument}_{month_part}_{depth_part}.csv'
        return StreamingResponse(csv_iter, media_type='text/csv', headers={'Content-Disposition': f'attachment; filename={filename}'})

    return app


@lru_cache(maxsize=1)
def get_repo() -> MongoDashboardRepository:
    settings = get_settings()
    metadata_service = MetadataService(APP_DIR)
    return MongoDashboardRepository(settings=settings, metadata_service=metadata_service)


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    settings = get_settings()
    return AuthService(settings=settings, db=get_repo().db)


app = create_app()
