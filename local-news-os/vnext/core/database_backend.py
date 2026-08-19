#!/usr/bin/env python3
"""Database backend compatibility for LOCAL NEWS OS vNext.

SQLite remains the deterministic local/test backend. Production instances may
bind PostgreSQL through an instance-configured environment-variable reference.
The adapter deliberately exposes the small sqlite-like connection surface used
by vNext core so domain modules do not branch on backend or locality.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

POSTGRES_SCHEMES = ("postgres://", "postgresql://")
_APPEND_ONLY_TRIGGER_RE = re.compile(
    r"CREATE\s+TRIGGER\s+IF\s+NOT\s+EXISTS\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"BEFORE\s+(?P<operation>UPDATE|DELETE)\s+ON\s+(?P<table>[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"BEGIN\s+SELECT\s+RAISE\(ABORT,\s*'[^']*'\);\s+END\s*;",
    re.IGNORECASE | re.DOTALL,
)


class DatabaseBackendError(RuntimeError):
    pass


class MissingPostgresDriver(DatabaseBackendError):
    pass


def backend_name(target: str | Path) -> str:
    value = str(target)
    return "postgresql" if value.startswith(POSTGRES_SCHEMES) else "sqlite"


def _qmark_to_pyformat(sql: str) -> str:
    """Translate DB-API qmark placeholders without touching quoted literals."""
    out: list[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        char = sql[i]
        if char == "'" and not in_double:
            out.append(char)
            if in_single and i + 1 < len(sql) and sql[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            out.append(char)
            i += 1
            continue
        if char == "?" and not in_single and not in_double:
            out.append("%s")
        else:
            out.append(char)
        i += 1
    return "".join(out)


def _rewrite_insert_or_ignore(sql: str) -> str:
    stripped = sql.strip()
    if not re.match(r"^INSERT\s+OR\s+IGNORE\s+INTO\b", stripped, re.IGNORECASE):
        return sql
    rewritten = re.sub(
        r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\b",
        "INSERT INTO",
        sql,
        count=1,
        flags=re.IGNORECASE,
    ).rstrip().rstrip(";")
    if " ON CONFLICT " not in f" {rewritten.upper()} ":
        rewritten += " ON CONFLICT DO NOTHING"
    return rewritten


def translate_query_for_postgres(sql: str) -> str:
    stripped = sql.strip()
    if stripped.upper() == "BEGIN IMMEDIATE":
        # The caller's critical section is serialized by an advisory xact lock.
        return "SELECT pg_advisory_xact_lock(7608242601)"
    if re.match(r"^\s*INSERT\s+OR\s+REPLACE\b", sql, re.IGNORECASE):
        raise DatabaseBackendError("INSERT OR REPLACE is not supported by the PostgreSQL compatibility contract")
    return _qmark_to_pyformat(_rewrite_insert_or_ignore(sql))


def translate_schema_for_postgres(script: str) -> str:
    """Translate the constrained vNext SQLite DDL contract to PostgreSQL DDL."""
    original = script
    translated = re.sub(r"(?mi)^\s*PRAGMA\s+foreign_keys\s*=\s*ON\s*;\s*", "", script)
    translated = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "SERIAL PRIMARY KEY",
        translated,
        flags=re.IGNORECASE,
    )

    def trigger_replacement(match: re.Match[str]) -> str:
        name = match.group("name")
        operation = match.group("operation").upper()
        table = match.group("table")
        return (
            f"DROP TRIGGER IF EXISTS {name} ON {table};\n"
            f"CREATE TRIGGER {name} BEFORE {operation} ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION local_news_reject_append_only_mutation();"
        )

    translated = _APPEND_ONLY_TRIGGER_RE.sub(trigger_replacement, translated)
    if "RAISE(ABORT" in original.upper():
        function = """
CREATE OR REPLACE FUNCTION local_news_reject_append_only_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;
"""
        translated = function + "\n" + translated
    if "RAISE(ABORT" in translated.upper() or "AUTOINCREMENT" in translated.upper() or "PRAGMA " in translated.upper():
        raise DatabaseBackendError("SQLite-only schema syntax remains after PostgreSQL translation")
    return translated


class _PostgresCursor:
    def __init__(self, cursor: Any, *, lastrowid: int | None = None) -> None:
        self._cursor = cursor
        self._lastrowid = lastrowid

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount)

    @property
    def lastrowid(self) -> int | None:
        return self._lastrowid

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self) -> Iterable[Any]:
        return iter(self._cursor)


class PostgresCompatConnection:
    """Small sqlite-compatible facade over psycopg 3 used by vNext core."""

    backend = "postgresql"

    def __init__(self, raw: Any) -> None:
        self._raw = raw
        self.total_changes = 0

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> _PostgresCursor:
        query = translate_query_for_postgres(sql)
        cursor = self._raw.cursor()
        event_insert = bool(
            re.match(r"^\s*INSERT\s+INTO\s+runtime_events\b", query, re.IGNORECASE)
            and " RETURNING " not in f" {query.upper()} "
        )
        if event_insert:
            query = query.rstrip().rstrip(";") + " RETURNING event_id"
        cursor.execute(query, tuple(params))
        lastrowid = None
        if event_insert:
            row = cursor.fetchone()
            if row is not None:
                lastrowid = int(row["event_id"] if isinstance(row, dict) else row[0])
        if re.match(r"^\s*(INSERT|UPDATE|DELETE)\b", query, re.IGNORECASE) and cursor.rowcount > 0:
            self.total_changes += int(cursor.rowcount)
        return _PostgresCursor(cursor, lastrowid=lastrowid)

    def executescript(self, script: str) -> None:
        translated = translate_schema_for_postgres(script)
        cursor = self._raw.cursor()
        # DDL contains function bodies with semicolons, so submit the translated
        # schema through psycopg's simple-query path instead of naively splitting.
        cursor.execute(translated, prepare=False)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


def connect_database(target: str | Path):
    if backend_name(target) == "sqlite":
        conn = sqlite3.connect(str(target))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    try:
        import psycopg  # type: ignore
        from psycopg.rows import dict_row  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only in deployed PostgreSQL mode
        raise MissingPostgresDriver("psycopg 3 is required for PostgreSQL runtime bindings") from exc
    raw = psycopg.connect(str(target), row_factory=dict_row, autocommit=False)
    return PostgresCompatConnection(raw)


def resolve_runtime_database_target(*, instance_cfg: dict[str, Any] | None = None) -> str:
    """Resolve a DB target without exposing a connection string to repository state."""
    if instance_cfg is not None:
        backend = (instance_cfg.get("runtime") or {}).get("state_backend") or {}
        secret_ref = str(backend.get("connection_secret_ref") or "")
        if not secret_ref or "://" in secret_ref or "//" in secret_ref:
            raise DatabaseBackendError("invalid instance database secret reference")
        target = os.environ.get(secret_ref)
        if target:
            expected = str(backend.get("kind") or "database")
            actual = backend_name(target)
            if expected == "postgresql" and actual != "postgresql":
                raise DatabaseBackendError("production instance requires a PostgreSQL database URL")
            return target
        if instance_cfg.get("environment") == "production":
            raise DatabaseBackendError(f"missing production database secret: {secret_ref}")

    url = os.environ.get("LOCAL_NEWS_RUNTIME_DATABASE_URL")
    if url:
        return url
    legacy = os.environ.get("LOCAL_NEWS_RUNTIME_DB")
    if legacy:
        if (os.environ.get("VERCEL_ENV") or "").lower() == "production":
            raise DatabaseBackendError("production runtime may not fall back to SQLite")
        return legacy
    raise DatabaseBackendError("runtime database is not configured")


def self_test() -> None:
    assert backend_name("postgresql://example.invalid/db") == "postgresql"
    assert backend_name("postgres://example.invalid/db") == "postgresql"
    assert backend_name("/tmp/runtime.sqlite3") == "sqlite"
    assert _qmark_to_pyformat("SELECT '?' AS literal, x FROM t WHERE a=? AND b=\"?\"") == (
        "SELECT '?' AS literal, x FROM t WHERE a=%s AND b=\"?\""
    )
    assert translate_query_for_postgres("BEGIN IMMEDIATE").startswith("SELECT pg_advisory_xact_lock")
    assert translate_query_for_postgres("INSERT OR IGNORE INTO x(a) VALUES(?)") == (
        "INSERT INTO x(a) VALUES(%s) ON CONFLICT DO NOTHING"
    )
    sample = """
PRAGMA foreign_keys = ON;
CREATE TABLE t (event_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS t_no_update
BEFORE UPDATE ON t
BEGIN
    SELECT RAISE(ABORT, 't is append-only');
END;
"""
    translated = translate_schema_for_postgres(sample)
    assert "SERIAL PRIMARY KEY" in translated
    assert "local_news_reject_append_only_mutation" in translated
    assert "AUTOINCREMENT" not in translated and "RAISE(ABORT" not in translated and "PRAGMA " not in translated
    print("LOCAL_NEWS_OS_VNEXT_DATABASE_BACKEND_SELF_TEST_PASS")


if __name__ == "__main__":
    self_test()
