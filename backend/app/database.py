from __future__ import annotations

import csv
import gzip
import os
import time
from contextlib import closing
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
BUILDINGS_FILE = DATA_DIR / "buildings.csv"
READINGS_FILE = DATA_DIR / "energy_hourly.csv.gz"


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("DB_HOST", "db"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "ecometrics"),
        user=os.getenv("DB_USER", "ecometrics"),
        password=os.getenv("DB_PASSWORD", ""),
        connect_timeout=5,
        row_factory=dict_row,
        application_name="ecometrics-api",
    )


def _create_schema(conn: psycopg.Connection) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS buildings (
            building_code TEXT PRIMARY KEY,
            building_name TEXT NOT NULL,
            building_type TEXT NOT NULL,
            floors INTEGER NOT NULL,
            area_m2 DOUBLE PRECISION NOT NULL,
            source_area_sqft INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS hourly_readings (
            observed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            building_code TEXT NOT NULL REFERENCES buildings(building_code),
            average_power_kw DOUBLE PRECISION,
            energy_kwh DOUBLE PRECISION,
            coverage_pct NUMERIC(5,1) NOT NULL,
            working_day SMALLINT,
            activity_level TEXT NOT NULL DEFAULT 'Unknown',
            quality_flag TEXT NOT NULL,
            spike_flag BOOLEAN NOT NULL DEFAULT FALSE,
            PRIMARY KEY (observed_at, building_code),
            CHECK (coverage_pct >= 0 AND coverage_pct <= 100),
            CHECK (quality_flag IN ('complete', 'partial', 'missing'))
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_hourly_readings_building_time
            ON hourly_readings (building_code, observed_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_hourly_readings_time
            ON hourly_readings (observed_at)
        """,
    ]
    for statement in statements:
        conn.execute(statement)


def _load_buildings(conn: psycopg.Connection) -> None:
    if not BUILDINGS_FILE.exists():
        raise FileNotFoundError(f"Building metadata is missing: {BUILDINGS_FILE}")
    with BUILDINGS_FILE.open("r", encoding="utf-8", newline="") as source:
        records = [
            (
                row["building_code"],
                row["building_name"],
                row["building_type"],
                int(row["floors"]),
                float(row["area_m2"]),
                int(row["source_area_sqft"]),
            )
            for row in csv.DictReader(source)
        ]
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO buildings (building_code, building_name, building_type, floors, area_m2, source_area_sqft)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (building_code) DO UPDATE SET
                building_name = EXCLUDED.building_name,
                building_type = EXCLUDED.building_type,
                floors = EXCLUDED.floors,
                area_m2 = EXCLUDED.area_m2,
                source_area_sqft = EXCLUDED.source_area_sqft
            """,
            records,
        )


def _copy_readings(conn: psycopg.Connection) -> None:
    if not READINGS_FILE.exists():
        raise FileNotFoundError(f"Hourly readings are missing: {READINGS_FILE}")
    copy_sql = """
        COPY hourly_readings (
            observed_at, building_code, average_power_kw, energy_kwh,
            coverage_pct, working_day, activity_level, quality_flag, spike_flag
        ) FROM STDIN WITH (FORMAT CSV, HEADER TRUE, NULL '')
    """
    with gzip.open(READINGS_FILE, "rt", encoding="utf-8", newline="") as source:
        with conn.cursor().copy(copy_sql) as copy:
            for line in source:
                copy.write(line)


def initialize_database() -> None:
    """Create tables and seed data once, safely across concurrent API replicas."""
    last_error: Exception | None = None
    for attempt in range(30):
        try:
            with closing(connect()) as conn:
                with conn.transaction():
                    _create_schema(conn)
                    _load_buildings(conn)
                    # Prevent two fresh replicas from copying the same CSV at once.
                    conn.execute("SELECT pg_advisory_xact_lock(592014270)")
                    count = conn.execute("SELECT COUNT(*) AS rows FROM hourly_readings").fetchone()["rows"]
                    if count == 0:
                        _copy_readings(conn)
            return
        except psycopg.OperationalError as exc:
            last_error = exc
            time.sleep(min(2 + attempt, 8))
    raise RuntimeError(f"PostgreSQL did not become ready: {last_error}") from last_error


def replace_readings() -> None:
    """Reload the shipped CSV after an explicit operator request."""
    with closing(connect()) as conn:
        with conn.transaction():
            _create_schema(conn)
            _load_buildings(conn)
            conn.execute("SELECT pg_advisory_xact_lock(592014270)")
            conn.execute("TRUNCATE TABLE hourly_readings")
            _copy_readings(conn)

