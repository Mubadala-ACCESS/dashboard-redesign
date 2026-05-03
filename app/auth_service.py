from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import re
import secrets
import smtplib
import struct
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import Request
from pymongo import ASCENDING
from pymongo.database import Database

from .settings import Settings


class AuthError(Exception):
    """Authentication or authorization failure with a safe user-facing message."""


@dataclass
class AuthContext:
    user: Optional[Dict[str, Any]]
    session: Optional[Dict[str, Any]]

    @property
    def is_authenticated(self) -> bool:
        return bool(self.user and self.session)


class AuthService:
    USERS = 'auth_users'
    GROUPS = 'auth_groups'
    SESSIONS = 'auth_sessions'
    CHALLENGES = 'auth_login_challenges'
    AUDIT = 'auth_audit'

    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.db[self.USERS].create_index([('username_lc', ASCENDING)], unique=True, background=True)
        self.db[self.USERS].create_index([('email_lc', ASCENDING)], unique=True, background=True)
        self.db[self.GROUPS].create_index([('name', ASCENDING)], unique=True, background=True)
        self.db[self.SESSIONS].create_index([('session_hash', ASCENDING)], unique=True, background=True)
        self.db[self.SESSIONS].create_index([('expires_at', ASCENDING)], expireAfterSeconds=0, background=True)
        self.db[self.CHALLENGES].create_index([('challenge_hash', ASCENDING)], unique=True, background=True)
        self.db[self.CHALLENGES].create_index([('expires_at', ASCENDING)], expireAfterSeconds=0, background=True)

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _secret_bytes(self) -> bytes:
        secret = self.settings.app_secret_key
        if not secret or secret == 'change-me':
            secret = 'development-change-me'
        return hashlib.sha256(secret.encode('utf-8')).digest()

    def _hmac(self, *parts: bytes) -> str:
        mac = hmac.new(self._secret_bytes(), digestmod=hashlib.sha256)
        for part in parts:
            mac.update(part)
        return base64.urlsafe_b64encode(mac.digest()).decode('ascii').rstrip('=')

    def _b64e(self, data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')

    def _b64d(self, data: str) -> bytes:
        return base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))

    def _derive_key(self, label: str) -> bytes:
        return hmac.new(self._secret_bytes(), label.encode('utf-8'), hashlib.sha256).digest()

    def _keystream(self, key: bytes, nonce: bytes, length: int) -> bytes:
        chunks: List[bytes] = []
        counter = 0
        while sum(len(chunk) for chunk in chunks) < length:
            chunks.append(hmac.new(key, nonce + counter.to_bytes(4, 'big'), hashlib.sha256).digest())
            counter += 1
        return b''.join(chunks)[:length]

    def encrypt_text(self, value: str) -> str:
        plaintext = value.encode('utf-8')
        nonce = secrets.token_bytes(16)
        enc_key = self._derive_key('auth:totp:enc')
        mac_key = self._derive_key('auth:totp:mac')
        stream = self._keystream(enc_key, nonce, len(plaintext))
        ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
        body = b'v1' + nonce + ciphertext
        tag = hmac.new(mac_key, body, hashlib.sha256).digest()
        return self._b64e(body + tag)

    def decrypt_text(self, token: str) -> str:
        raw = self._b64d(token)
        if len(raw) < 50 or raw[:2] != b'v1':
            raise AuthError('Invalid encrypted secret.')
        body, tag = raw[:-32], raw[-32:]
        mac_key = self._derive_key('auth:totp:mac')
        expected = hmac.new(mac_key, body, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise AuthError('Invalid encrypted secret.')
        nonce = body[2:18]
        ciphertext = body[18:]
        stream = self._keystream(self._derive_key('auth:totp:enc'), nonce, len(ciphertext))
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream))
        return plaintext.decode('utf-8')

    def hash_password(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        iterations = int(self.settings.auth_password_iterations)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
        return f'pbkdf2_sha256${iterations}${self._b64e(salt)}${self._b64e(digest)}'

    def verify_password(self, password: str, encoded: str) -> bool:
        try:
            scheme, iterations, salt, expected = encoded.split('$', 3)
            if scheme != 'pbkdf2_sha256':
                return False
            digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), self._b64d(salt), int(iterations))
            return hmac.compare_digest(self._b64e(digest), expected)
        except Exception:
            return False

    def generate_totp_secret(self) -> str:
        return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')

    def totp_uri(self, username: str, secret: str) -> str:
        issuer = re.sub(r'[:\n\r]+', ' ', self.settings.auth_issuer).strip()
        label = f'{issuer}:{username}'
        return (
            'otpauth://totp/'
            f'{label.replace(" ", "%20")}?secret={secret}&issuer={issuer.replace(" ", "%20")}&digits=6&period=30'
        )

    def _totp_code(self, secret: str, step: int) -> str:
        padded = secret + '=' * (-len(secret) % 8)
        key = base64.b32decode(padded, casefold=True)
        digest = hmac.new(key, struct.pack('>Q', step), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        code = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
        return f'{code % 1000000:06d}'

    def verify_totp(self, secret: str, code: str, last_step: Optional[int] = None) -> Optional[int]:
        normalized = re.sub(r'\s+', '', code or '')
        if not re.fullmatch(r'\d{6}', normalized):
            return None
        current = int(time.time() // 30)
        for step in range(current - 1, current + 2):
            if last_step is not None and step <= last_step:
                continue
            if hmac.compare_digest(self._totp_code(secret, step), normalized):
                return step
        return None

    def generate_recovery_codes(self, count: int = 10) -> List[str]:
        codes = []
        for _ in range(count):
            part = secrets.token_hex(6).upper()
            codes.append(f'MACC-{part[:4]}-{part[4:8]}-{part[8:12]}')
        return codes

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    def _signed_cookie(self, token: str) -> str:
        return f'{token}.{self._hmac(token.encode("utf-8"))}'

    def _verify_signed_cookie(self, value: str | None) -> Optional[str]:
        if not value or '.' not in value:
            return None
        token, signature = value.rsplit('.', 1)
        expected = self._hmac(token.encode('utf-8'))
        return token if hmac.compare_digest(signature, expected) else None

    def make_anon_csrf_token(self) -> str:
        token = secrets.token_urlsafe(32)
        return self._signed_cookie(token)

    def verify_anon_csrf(self, request: Request, submitted: str | None) -> bool:
        cookie = request.cookies.get(self.settings.auth_csrf_cookie_name)
        if not cookie or not submitted or not hmac.compare_digest(cookie, submitted):
            return False
        return self._verify_signed_cookie(submitted) is not None

    def set_anon_csrf_cookie(self, response, token: str) -> None:
        response.set_cookie(
            self.settings.auth_csrf_cookie_name,
            token,
            httponly=True,
            secure=self.settings.auth_cookie_secure,
            samesite='lax',
            max_age=3600,
        )

    def clear_anon_csrf_cookie(self, response) -> None:
        response.delete_cookie(self.settings.auth_csrf_cookie_name)

    def find_user_by_login(self, login: str) -> Optional[Dict[str, Any]]:
        key = (login or '').strip().lower()
        if not key:
            return None
        return self.db[self.USERS].find_one({'$or': [{'username_lc': key}, {'email_lc': key}], 'disabled_at': {'$exists': False}})

    def create_login_challenge(self, user: Dict[str, Any], purpose: str, pending_totp_secret: Optional[str] = None) -> str:
        token = secrets.token_urlsafe(32)
        doc: Dict[str, Any] = {
            'challenge_hash': self._hash_token(token),
            'user_id': user['_id'],
            'purpose': purpose,
            'created_at': self._now(),
            'expires_at': self._now() + timedelta(minutes=self.settings.auth_login_challenge_minutes),
        }
        if pending_totp_secret:
            doc['pending_totp_secret'] = self.encrypt_text(pending_totp_secret)
        self.db[self.CHALLENGES].insert_one(doc)
        return token

    def consume_challenge(self, token: str, purpose: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        challenge = self.db[self.CHALLENGES].find_one_and_delete({
            'challenge_hash': self._hash_token(token or ''),
            'purpose': purpose,
            'expires_at': {'$gt': self._now()},
        })
        if not challenge:
            raise AuthError('The sign-in challenge has expired. Please start again.')
        user = self.db[self.USERS].find_one({'_id': challenge['user_id'], 'disabled_at': {'$exists': False}})
        if not user:
            raise AuthError('The user account is no longer active.')
        return user, challenge

    def create_session(self, user: Dict[str, Any], request: Request) -> Tuple[str, Dict[str, Any]]:
        token = secrets.token_urlsafe(32)
        session = {
            'session_hash': self._hash_token(token),
            'user_id': user['_id'],
            'username': user['username'],
            'csrf_token': secrets.token_urlsafe(32),
            'created_at': self._now(),
            'expires_at': self._now() + timedelta(hours=self.settings.auth_session_hours),
            'ip': request.client.host if request.client else '',
            'user_agent': request.headers.get('user-agent', '')[:300],
        }
        self.db[self.SESSIONS].insert_one(session)
        return self._signed_cookie(token), session

    def set_session_cookie(self, response, signed_cookie: str) -> None:
        response.set_cookie(
            self.settings.auth_cookie_name,
            signed_cookie,
            httponly=True,
            secure=self.settings.auth_cookie_secure,
            samesite='lax',
            max_age=self.settings.auth_session_hours * 3600,
        )

    def clear_session_cookie(self, response) -> None:
        response.delete_cookie(self.settings.auth_cookie_name)

    def load_context(self, request: Request) -> AuthContext:
        token = self._verify_signed_cookie(request.cookies.get(self.settings.auth_cookie_name))
        if not token:
            return AuthContext(user=None, session=None)
        session = self.db[self.SESSIONS].find_one({
            'session_hash': self._hash_token(token),
            'expires_at': {'$gt': self._now()},
            'revoked_at': {'$exists': False},
        })
        if not session:
            return AuthContext(user=None, session=None)
        user = self.db[self.USERS].find_one({'_id': session['user_id'], 'disabled_at': {'$exists': False}})
        if not user:
            return AuthContext(user=None, session=None)
        return AuthContext(user=user, session=session)

    def revoke_session(self, ctx: AuthContext) -> None:
        if ctx.session:
            self.db[self.SESSIONS].update_one({'_id': ctx.session['_id']}, {'$set': {'revoked_at': self._now()}})

    def verify_session_csrf(self, request: Request, ctx: AuthContext, submitted: Optional[str]) -> bool:
        token = submitted or request.headers.get('x-csrf-token')
        if not ctx.session or not token:
            return False
        return hmac.compare_digest(str(ctx.session.get('csrf_token') or ''), str(token))

    def user_acl(self, user: Dict[str, Any]) -> Dict[str, Any]:
        permissions = set(user.get('permissions') or [])
        station_acl = list(user.get('station_acl') or [])
        group_names = [str(item) for item in user.get('groups') or []]
        if group_names:
            for group in self.db[self.GROUPS].find({'name': {'$in': group_names}, 'disabled_at': {'$exists': False}}):
                permissions.update(group.get('permissions') or [])
                station_acl.extend(group.get('station_acl') or [])
        return {'permissions': sorted(permissions), 'station_acl': station_acl, 'groups': group_names}

    def can_access_station(self, ctx: AuthContext, station: Dict[str, Any]) -> bool:
        if station.get('is_public', True):
            return True
        if not ctx.is_authenticated:
            return False
        acl = self.user_acl(ctx.user)
        permissions = set(acl['permissions'])
        if {'admin:all', 'station:read:all', 'station:read:private'} & permissions:
            return True
        ids = {str(station.get('station_id')), str(station.get('public_id'))}
        for rule in acl['station_acl']:
            if rule.get('effect', 'allow') != 'allow':
                continue
            scope = rule.get('scope')
            if scope == 'all':
                return True
            if scope == 'private' and not station.get('is_public', True):
                return True
            if scope == 'station' and str(rule.get('station_id')) in ids:
                return True
            if scope == 'device_type' and rule.get('device_type') == station.get('device_type'):
                return True
        return False

    def requires_family_auth(self, device_type: str) -> bool:
        if not device_type:
            return False
        cache_key = f'auth_family_private:{device_type}'
        cached = getattr(self, '_family_cache', {}).get(cache_key) if hasattr(self, '_family_cache') else None
        now_ts = time.time()
        if cached and cached[1] > now_ts:
            return bool(cached[0])
        value = self.db[self.settings.mongo_stations_info_collection].find_one({'type': device_type, 'public': False}, {'_id': 1}) is not None
        if not hasattr(self, '_family_cache'):
            self._family_cache = {}
        self._family_cache[cache_key] = (value, now_ts + 20)
        return value

    def can_access_station_family(self, ctx: AuthContext, device_type: str) -> bool:
        if not self.requires_family_auth(device_type):
            return True
        if not ctx.is_authenticated:
            return False
        acl = self.user_acl(ctx.user)
        permissions = set(acl['permissions'])
        if {'admin:all', 'station:read:all', 'station:read:private'} & permissions:
            return True
        return any(rule.get('effect', 'allow') == 'allow' and rule.get('scope') == 'device_type' and rule.get('device_type') == device_type for rule in acl['station_acl'])

    def ensure_group(self, name: str, permissions: Iterable[str], station_acl: Optional[List[Dict[str, Any]]] = None) -> None:
        self.db[self.GROUPS].update_one(
            {'name': name},
            {
                '$setOnInsert': {'created_at': self._now()},
                '$set': {
                    'name': name,
                    'permissions': sorted(set(permissions)),
                    'station_acl': station_acl or [],
                    'updated_at': self._now(),
                },
            },
            upsert=True,
        )

    def upsert_user(
        self,
        username: str,
        email: str,
        password: str,
        groups: Optional[List[str]] = None,
        permissions: Optional[List[str]] = None,
        station_acl: Optional[List[Dict[str, Any]]] = None,
        require_totp_setup: bool = True,
    ) -> Dict[str, Any]:
        username = username.strip()
        email = email.strip()
        if not re.fullmatch(r'[A-Za-z0-9_.-]{3,64}', username):
            raise AuthError('Username contains invalid characters.')
        if '@' not in email or len(email) > 255:
            raise AuthError('Email address is invalid.')
        doc = {
            'username': username,
            'username_lc': username.lower(),
            'email': email,
            'email_lc': email.lower(),
            'password_hash': self.hash_password(password),
            'groups': groups or [],
            'permissions': permissions or [],
            'station_acl': station_acl or [],
            'require_totp_setup': bool(require_totp_setup),
            'updated_at': self._now(),
        }
        result = self.db[self.USERS].find_one_and_update(
            {'username_lc': username.lower()},
            {'$set': doc, '$setOnInsert': {'created_at': self._now()}},
            upsert=True,
            return_document=True,
        )
        return result

    def complete_totp_setup(self, user: Dict[str, Any], secret: str, step: int) -> List[str]:
        codes = self.generate_recovery_codes()
        recovery = [{'hash': self.hash_password(code), 'created_at': self._now(), 'used_at': None} for code in codes]
        self.db[self.USERS].update_one(
            {'_id': user['_id']},
            {
                '$set': {
                    'totp_secret': self.encrypt_text(secret),
                    'totp_enabled': True,
                    'require_totp_setup': False,
                    'last_totp_step': step,
                    'recovery_codes': recovery,
                    'updated_at': self._now(),
                }
            },
        )
        return codes

    def verify_user_totp_or_recovery(self, user: Dict[str, Any], code: str) -> bool:
        secret_token = user.get('totp_secret')
        if secret_token:
            try:
                step = self.verify_totp(self.decrypt_text(secret_token), code, user.get('last_totp_step'))
            except AuthError:
                step = None
            if step is not None:
                self.db[self.USERS].update_one({'_id': user['_id']}, {'$set': {'last_totp_step': step, 'updated_at': self._now()}})
                return True
        normalized = re.sub(r'\s+', '', code or '').upper()
        for index, item in enumerate(user.get('recovery_codes') or []):
            if item.get('used_at'):
                continue
            if self.verify_password(normalized, item.get('hash', '')):
                self.db[self.USERS].update_one(
                    {'_id': user['_id']},
                    {'$set': {f'recovery_codes.{index}.used_at': self._now(), 'updated_at': self._now()}},
                )
                return True
        return False

    def safe_next_url(self, value: str | None, fallback: str = '/') -> str:
        if not value:
            return fallback
        if not value.startswith('/') or value.startswith('//') or '\n' in value or '\r' in value:
            return fallback
        return value

    def send_security_email(self, to_email: str, subject: str, message: str) -> None:
        if not self.settings.auth_email_enabled:
            return
        if not (self.settings.smtp_server and self.settings.smtp_from and self.settings.smtp_password):
            return
        msg = MIMEText(message, 'plain')
        msg['Subject'] = subject
        msg['From'] = self.settings.smtp_from
        msg['To'] = to_email
        try:
            with smtplib.SMTP(self.settings.smtp_server, self.settings.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(self.settings.smtp_from, self.settings.smtp_password)
                server.sendmail(self.settings.smtp_from, [to_email], msg.as_string())
        except Exception as exc:
            self.db[self.AUDIT].insert_one({
                'event': 'security_email_failed',
                'to': to_email,
                'subject': subject,
                'error': str(exc)[:300],
                'created_at': self._now(),
            })

    def export_users_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['username', 'email', 'groups', 'permissions', 'totp_enabled', 'disabled'])
        for user in self.db[self.USERS].find({}, {'password_hash': 0, 'totp_secret': 0, 'recovery_codes': 0}):
            writer.writerow([
                user.get('username'),
                user.get('email'),
                '|'.join(user.get('groups') or []),
                '|'.join(user.get('permissions') or []),
                bool(user.get('totp_enabled')),
                bool(user.get('disabled_at')),
            ])
        return buffer.getvalue()
