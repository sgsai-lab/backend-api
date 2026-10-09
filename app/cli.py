"""Operational commands, e.g. `python -m app.cli create-admin --email admin@example.com`."""

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime

from app.core.errors import ValidationFailedError
from app.core.passwords import ensure_password_policy, hash_password
from app.db.session import get_engine, get_sessionmaker
from app.modules.users.models import User, UserRole
from app.modules.users.repository import get_user_by_email


async def create_admin(email: str, full_name: str, password: str) -> str:
    async with get_sessionmaker()() as session:
        user = await get_user_by_email(session, email)
        if user is None:
            user = User(email=email, full_name=full_name)
            session.add(user)
            action = "created"
        else:
            action = "promoted"
        user.role = UserRole.ADMIN
        user.password_hash = await hash_password(password)
        user.email_verified_at = user.email_verified_at or datetime.now(UTC)
        await session.commit()
    await get_engine().dispose()
    return action


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="Create or promote an administrator")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", default="Administrator")
    args = parser.parse_args(argv)

    password = getpass.getpass("Password: ")
    try:
        ensure_password_policy(password, args.email)
    except ValidationFailedError as exc:
        print(f"Rejected: {exc.details[0]['message']}", file=sys.stderr)
        return 1
    action = asyncio.run(create_admin(args.email, args.name, password))
    print(f"Administrator {action}: {args.email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
