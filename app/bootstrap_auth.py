from __future__ import annotations

import argparse
import os
import secrets

from .auth_service import AuthService
from .main import get_repo
from .settings import get_settings


def readable_password() -> str:
    words = ['Access', 'Marine', 'Station', 'Signal', 'Coral', 'Harbor']
    return f'{secrets.choice(words)}-{secrets.choice(words)}-{secrets.randbelow(9000) + 1000}!'


def main() -> None:
    parser = argparse.ArgumentParser(description='Bootstrap a dashboard admin user.')
    parser.add_argument('--username', default='ptr226')
    parser.add_argument('--email', default='ptr226@nyu.edu')
    parser.add_argument('--password', default=os.getenv('BOOTSTRAP_ADMIN_PASSWORD'))
    args = parser.parse_args()

    settings = get_settings()
    auth = AuthService(settings=settings, db=get_repo().db)
    password = args.password or readable_password()
    auth.ensure_group(
        'admins',
        permissions=['admin:all', 'station:read:all', 'station:read:private'],
        station_acl=[{'effect': 'allow', 'scope': 'all'}],
    )
    auth.upsert_user(
        username=args.username,
        email=args.email,
        password=password,
        groups=['admins'],
        permissions=[],
        station_acl=[],
        require_totp_setup=True,
    )
    print(f'Admin user ready: {args.username} <{args.email}>')
    print(f'Initial password: {password}')
    print('MFA setup will be required at first login.')


if __name__ == '__main__':
    main()
