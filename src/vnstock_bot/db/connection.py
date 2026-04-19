from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from vnstock_bot.config import get_settings

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        isolation_level=None,   # autocommit; we manage transactions explicitly
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


_conn: sqlite3.Connection | None = None


def get_connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _connect(get_settings().absolute_db_path)
    return _conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in
            conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_v2_columns(conn: sqlite3.Connection) -> None:
    """Defensive ALTER for legacy DBs that predate some columns.

    MUST run BEFORE `executescript(schema.sql)` because the schema has
    CREATE INDEX statements referencing columns added later — if the table
    was created by an older schema, those columns don't exist and the
    index creation fails with `no such column`.
    """
    # decisions: v2 additions (trace_id, 3-scenario targets, bias_flags)
    if _table_exists(conn, "decisions"):
        existing = _column_names(conn, "decisions")
        for col, col_type in [
            ("trace_id",        "TEXT"),
            ("target_bear",     "INTEGER"),
            ("target_base",     "INTEGER"),
            ("target_bull",     "INTEGER"),
            ("bias_flags_json", "TEXT"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE decisions ADD COLUMN {col} {col_type}")

    # events: trace_id (added alongside orchestrator W2)
    if _table_exists(conn, "events"):
        existing = _column_names(conn, "events")
        if "trace_id" not in existing:
            conn.execute("ALTER TABLE events ADD COLUMN trace_id TEXT")


def init_db() -> None:
    settings = get_settings()
    conn = _connect(settings.absolute_db_path)
    # Order matters: migrate first so `CREATE INDEX ... ON decisions(trace_id)`
    # and `ON events(trace_id)` in schema.sql find the columns on legacy DBs.
    _migrate_v2_columns(conn)
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    # Run again post-schema to catch any tables that were just created
    # without migration history (idempotent).
    _migrate_v2_columns(conn)
    conn.close()
    print(f"✅ DB initialized at {settings.absolute_db_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="Create schema")
    args = parser.parse_args()
    if args.init:
        init_db()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
