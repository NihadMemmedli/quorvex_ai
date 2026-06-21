"""Run Alembic commands with a programmatic config.

The production image and local bind-mounted backend do not always include the
root alembic.ini file. This runner keeps Makefile migration targets independent
of that file while still using the repository migration directory.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlmodel import SQLModel


def build_config() -> Config:
    project_root = Path(__file__).resolve().parents[2]
    config = Config()
    config.set_main_option("script_location", str(project_root / "orchestrator" / "migrations"))

    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)

    return config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run repository Alembic commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

    revision_parser = subparsers.add_parser("revision")
    revision_parser.add_argument("-m", "--message", required=True)
    revision_parser.add_argument("--autogenerate", action="store_true")

    upgrade_parser = subparsers.add_parser("upgrade")
    upgrade_parser.add_argument("revision", nargs="?", default="head")

    downgrade_parser = subparsers.add_parser("downgrade")
    downgrade_parser.add_argument("revision", nargs="?", default="-1")

    history_parser = subparsers.add_parser("history")
    history_parser.add_argument("-r", "--rev-range", default=None)
    history_parser.add_argument("--verbose", action="store_true")

    stamp_parser = subparsers.add_parser("stamp")
    stamp_parser.add_argument("revision")

    args = parser.parse_args()
    config = build_config()

    if args.command == "revision":
        command.revision(config, message=args.message, autogenerate=args.autogenerate)
    elif args.command == "upgrade":
        if args.revision == "head":
            from orchestrator.api import db as db_module

            should_stamp_head_after_sync = db_module._run_alembic_migrations()
            if should_stamp_head_after_sync:
                try:
                    SQLModel.metadata.create_all(db_module.engine, checkfirst=True)
                except (ProgrammingError, OperationalError) as exc:
                    if "already exists" not in str(exc).lower():
                        raise
                db_module._run_migrations()
                db_module._stamp_alembic_head()
        else:
            command.upgrade(config, args.revision)
    elif args.command == "downgrade":
        command.downgrade(config, args.revision)
    elif args.command == "history":
        command.history(config, rev_range=args.rev_range, verbose=args.verbose)
    elif args.command == "stamp":
        command.stamp(config, args.revision)


if __name__ == "__main__":
    main()
