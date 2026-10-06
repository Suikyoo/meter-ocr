"""Maintenance commands. Usage: python -m app.cli rebuild-rollup"""
import argparse

from . import db
from .settings import load_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("rebuild-rollup", help="recompute hourly consumption from stored readings")
    parser.parse_args(argv)

    conn = db.connect(load_settings().db_path)
    try:
        db.rebuild_rollup(conn)
    finally:
        conn.close()
    print("hourly rollup rebuilt")


if __name__ == "__main__":
    main()
