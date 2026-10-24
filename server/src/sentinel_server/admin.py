"""``sentinel-admin``: database migrations and API keys.

sentinel-admin migrate
sentinel-admin create-key --name ci --scope ingest --scope read
sentinel-admin revoke-key snl_AbCdEfGh
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sentinel_server.db import migrate
from sentinel_server.db.models import Scope
from sentinel_server.db.session import make_engine, make_sessionmaker
from sentinel_server.keys import create_key, revoke
from sentinel_server.settings import get_settings


def main(argv: list[str] | None = None) -> int:
    """Run a command; returns the exit status."""
    parser = argparse.ArgumentParser(prog="sentinel-admin", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply database migrations")
    create = commands.add_parser("create-key", help="create an API key and print it once")
    create.add_argument("--name", required=True)
    create.add_argument("--scope", action="append", choices=[s.value for s in Scope], required=True)
    rev = commands.add_parser("revoke-key", help="revoke a key by its displayed prefix")
    rev.add_argument("prefix")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.command == "migrate":
        migrate.upgrade(settings.database_url)
        return 0
    return asyncio.run(_keys(args, settings.database_url))


async def _keys(args: argparse.Namespace, url: str) -> int:
    engine = make_engine(url, pool_size=1)
    try:
        async with make_sessionmaker(engine)() as session:
            if args.command == "create-key":
                secret, key = await create_key(session, args.name, [Scope(s) for s in args.scope])
                await session.commit()
                print(secret)
                scopes = ", ".join(key.scopes)
                print(f"created {key.prefix} ({scopes}); it is not shown again", file=sys.stderr)
                return 0
            if await revoke(session, args.prefix):
                print(f"revoked {args.prefix}", file=sys.stderr)
                return 0
            print(f"no live key with prefix {args.prefix}", file=sys.stderr)
            return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
