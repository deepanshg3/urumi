#!/usr/bin/env python3
"""Retire the old assessment credential accounts.

Run this inside a gateway container (or on the host with DATABASE_URL set)
after demo mode is in place. Only accounts matching ``assessment-*@urumi.local``
are touched; demo personas (``demo-*@urumi.demo``) and normal users are not.

For each matching account the script:

* deletes every API key row minted for the assessment;
* revokes all browser sessions;
* rotates the password to a fresh random value that is never printed;
* deactivates the account so it can no longer sign in.

With ``--delete-files`` it also deletes ``assessment-credentials*.txt`` from
the repository root. Nothing secret is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TARGET_LIKE = "assessment-%@urumi.local"


def _backend():
    from sqlalchemy import delete, select, update

    from services.gateway.auth import set_user_password
    from services.gateway.db import ApiKey, Database, LoginSession, User, utcnow

    return {
        "delete": delete,
        "select": select,
        "update": update,
        "set_user_password": set_user_password,
        "ApiKey": ApiKey,
        "Database": Database,
        "LoginSession": LoginSession,
        "User": User,
        "utcnow": utcnow,
    }


async def retire(database_url: str) -> tuple[int, int, int]:
    backend = _backend()
    Database = backend["Database"]
    User = backend["User"]
    ApiKey = backend["ApiKey"]
    LoginSession = backend["LoginSession"]
    select = backend["select"]
    delete = backend["delete"]
    update = backend["update"]
    utcnow = backend["utcnow"]
    set_user_password = backend["set_user_password"]

    database = Database(database_url)
    accounts = keys = sessions = 0
    try:
        async with database.session_factory() as session:
            users = list(
                (
                    await session.execute(
                        select(User).where(User.email.like(TARGET_LIKE))
                    )
                ).scalars()
            )
        for user in users:
            accounts += 1
            async with database.session_factory() as session:
                removed = await session.execute(
                    delete(ApiKey).where(ApiKey.user_id == user.id)
                )
                keys += removed.rowcount or 0
                revoked = await session.execute(
                    update(LoginSession)
                    .where(
                        LoginSession.user_id == user.id,
                        LoginSession.revoked_at.is_(None),
                    )
                    .values(revoked_at=utcnow())
                )
                sessions += revoked.rowcount or 0
                await session.execute(
                    update(User).where(User.id == user.id).values(is_active=False)
                )
                await session.commit()
            # Rotate to a random value we deliberately never print.
            await set_user_password(
                database, user.id, secrets.token_urlsafe(32), revoke_sessions=False
            )
    finally:
        await database.dispose()
    return accounts, keys, sessions


def delete_credential_files(directory: Path) -> list[str]:
    deleted: list[str] = []
    for path in sorted(directory.glob("assessment-credentials*.txt")):
        if path.is_file():
            path.unlink()
            deleted.append(path.name)
    return deleted


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Gateway database URL (defaults to DATABASE_URL).",
    )
    parser.add_argument(
        "--delete-files",
        action="store_true",
        help="Delete assessment-credentials*.txt from this repository root.",
    )
    parser.add_argument(
        "--files-dir",
        default=str(REPO_ROOT),
        help="Directory searched by --delete-files.",
    )
    args = parser.parse_args(argv)
    if not args.database_url:
        print("no database URL: set DATABASE_URL or pass --database-url", file=sys.stderr)
        return 2

    accounts, keys, sessions = asyncio.run(retire(args.database_url))
    print(
        f"retired {accounts} assessment account(s): "
        f"{keys} API key(s) deleted, {sessions} session(s) revoked, "
        "passwords rotated, accounts deactivated"
    )
    if args.delete_files:
        deleted = delete_credential_files(Path(args.files_dir))
        if deleted:
            print("deleted credential files: " + ", ".join(deleted))
        else:
            print("no credential files found to delete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
