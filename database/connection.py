"""PostgreSQL connection and shared time utilities."""
import os
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras


def connect():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ.get("DB_NAME", "marinetraffic"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
        sslmode=os.environ.get("DB_SSLMODE", "require"),
    )


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_to_utc(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_to_local(ts, tz_hours):
    if ts is None or tz_hours is None:
        return None
    tz = timezone(timedelta(hours=tz_hours))
    return datetime.fromtimestamp(ts, tz).isoformat()


def b(v):
    """Convert truthy value to 1/0/None for PostgreSQL SMALLINT columns."""
    return None if v is None else int(bool(v))
