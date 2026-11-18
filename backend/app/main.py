from __future__ import annotations

import csv
import io
from contextlib import asynccontextmanager, closing
from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from psycopg.rows import dict_row

from app.database import connect, initialize_database


DEFAULT_GRID_FACTOR = 0.675  # kg CO2/kWh; CEA weighted average for FY 2025-26.
GRID_FACTOR_SOURCE = "CEA CO2 Baseline Database v22.0, FY 2025-26, weighted average"


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="EcoMetrics Campus API",
    description="Campus electricity analytics with visible meter-data quality context.",
    version="1.0.0",
    lifespan=lifespan,
)


def _query_one(statement: str, params: tuple = ()) -> dict:
    with closing(connect()) as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(statement, params)
            row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=503, detail="The campus dataset is not available yet.")
    return row


def _query_all(statement: str, params: tuple = ()) -> list[dict]:
    with closing(connect()) as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(statement, params)
            return cursor.fetchall()


def _resolve_dates(start_date: date | None, end_date: date | None) -> tuple[date, date]:
    bounds = _query_one("SELECT MIN(observed_at)::date AS first_day, MAX(observed_at)::date AS last_day FROM hourly_readings")
    start = start_date or bounds["first_day"]
    end = end_date or bounds["last_day"]
    if start is None or end is None:
        raise HTTPException(status_code=503, detail="The campus dataset has no readings.")
    if start > end:
        raise HTTPException(status_code=422, detail="Start date must be on or before end date.")
    if start < bounds["first_day"] or end > bounds["last_day"]:
        raise HTTPException(status_code=422, detail=f"Choose dates between {bounds['first_day']} and {bounds['last_day']}.")
    return start, end


def _where(start: date, end: date, building_code: str | None = None) -> tuple[str, tuple]:
    clauses = ["r.observed_at >= %s", "r.observed_at < %s"]
    params: list[object] = [datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)]
    if building_code:
        clauses.append("r.building_code = %s")
        params.append(building_code)
    return " AND ".join(clauses), tuple(params)


def _building_count(building_code: str | None) -> int:
    if building_code:
        row = _query_one("SELECT COUNT(*) AS count FROM buildings WHERE building_code = %s", (building_code,))
        if row["count"] == 0:
            raise HTTPException(status_code=404, detail="Building was not found.")
        return 1
    return int(_query_one("SELECT COUNT(*) AS count FROM buildings")["count"])


def _as_float(value: object) -> float:
    return float(value or 0)


@app.get("/api/health/live", tags=["Operations"])
def liveness() -> dict:
    return {"status": "alive"}


@app.get("/api/health/ready", tags=["Operations"])
def readiness() -> dict:
    row = _query_one("SELECT COUNT(*) AS readings FROM hourly_readings")
    if row["readings"] == 0:
        raise HTTPException(status_code=503, detail="Database is ready but the dataset is empty.")
    return {"status": "ready", "hourly_building_records": int(row["readings"])}


@app.get("/api/filters", tags=["Dashboard"])
def filters() -> dict:
    bounds = _query_one("SELECT MIN(observed_at)::date AS first_day, MAX(observed_at)::date AS last_day FROM hourly_readings")
    buildings = _query_all(
        "SELECT building_code, building_name, building_type, area_m2 FROM buildings ORDER BY building_name"
    )
    return {
        "start_date": bounds["first_day"],
        "end_date": bounds["last_day"],
        "buildings": buildings,
        "timezone": "Asia/Kolkata",
    }


@app.get("/api/overview", tags=["Dashboard"])
def overview(
    start_date: date | None = None,
    end_date: date | None = None,
    building_code: str | None = None,
    grid_factor: float = Query(DEFAULT_GRID_FACTOR, ge=0, le=2),
) -> dict:
    start, end = _resolve_dates(start_date, end_date)
    where, params = _where(start, end, building_code)
    current = _query_one(
        f"""
        SELECT COALESCE(SUM(r.energy_kwh), 0) AS total_kwh,
               COUNT(*) AS expected_rows,
               COUNT(*) FILTER (WHERE r.energy_kwh IS NOT NULL) AS usable_hours,
               COUNT(*) FILTER (WHERE r.quality_flag = 'partial') AS partial_hours,
               COUNT(*) FILTER (WHERE r.quality_flag = 'missing') AS missing_hours,
               COUNT(*) FILTER (WHERE r.spike_flag) AS spike_hours,
               COALESCE(AVG(r.coverage_pct), 0) AS average_coverage
        FROM hourly_readings r WHERE {where}
        """,
        params,
    )
    days = (end - start).days + 1
    building_count = _building_count(building_code)
    expected = days * 24 * building_count
    usable = int(current["usable_hours"])
    confidence = round(100.0 * usable / expected, 1) if expected else 0.0

    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    previous_where, previous_params = _where(previous_start, previous_end, building_code)
    previous = _query_one(
        f"SELECT COALESCE(SUM(r.energy_kwh), 0) AS total_kwh FROM hourly_readings r WHERE {previous_where}",
        previous_params,
    )
    total_kwh = _as_float(current["total_kwh"])
    previous_kwh = _as_float(previous["total_kwh"])
    change_pct = ((total_kwh / previous_kwh) - 1.0) * 100.0 if previous_kwh > 0 else None

    return {
        "start_date": start,
        "end_date": end,
        "building_code": building_code,
        "electricity_kwh": round(total_kwh, 1),
        "estimated_co2_kg": round(total_kwh * grid_factor, 1),
        "grid_factor_kg_co2_per_kwh": grid_factor,
        "grid_factor_source": GRID_FACTOR_SOURCE,
        "previous_period_kwh": round(previous_kwh, 1),
        "change_vs_previous_pct": round(change_pct, 1) if change_pct is not None else None,
        "average_meter_coverage_pct": round(_as_float(current["average_coverage"]), 1),
        "usable_hour_pct": confidence,
        "usable_hours": usable,
        "expected_hours": expected,
        "partial_hours": int(current["partial_hours"]),
        "missing_hours": int(current["missing_hours"]),
        "statistical_spikes": int(current["spike_hours"]),
    }


@app.get("/api/trends", tags=["Dashboard"])
def trends(
    start_date: date | None = None,
    end_date: date | None = None,
    building_code: str | None = None,
    grain: Literal["day", "month"] = "month",
) -> dict:
    start, end = _resolve_dates(start_date, end_date)
    where, params = _where(start, end, building_code)
    bucket = "date_trunc('day', r.observed_at)" if grain == "day" else "date_trunc('month', r.observed_at)"
    rows = _query_all(
        f"""
        SELECT {bucket} AS bucket,
               SUM(r.energy_kwh) AS energy_kwh,
               AVG(r.coverage_pct) AS coverage_pct
        FROM hourly_readings r
        WHERE {where}
        GROUP BY 1 ORDER BY 1
        """,
        params,
    )
    return {
        "grain": grain,
        "points": [
            {"period": row["bucket"].strftime("%Y-%m-%d"), "energy_kwh": round(float(row["energy_kwh"]), 2) if row["energy_kwh"] is not None else None, "coverage_pct": round(_as_float(row["coverage_pct"]), 1)}
            for row in rows
        ],
    }


@app.get("/api/benchmarks", tags=["Dashboard"])
def benchmarks(
    start_date: date | None = None,
    end_date: date | None = None,
    grid_factor: float = Query(DEFAULT_GRID_FACTOR, ge=0, le=2),
) -> dict:
    start, end = _resolve_dates(start_date, end_date)
    where, params = _where(start, end)
    rows = _query_all(
        f"""
        SELECT b.building_code, b.building_name, b.building_type, b.area_m2,
               COALESCE(SUM(r.energy_kwh), 0) AS energy_kwh,
               AVG(r.coverage_pct) AS coverage_pct,
               COUNT(*) FILTER (WHERE r.energy_kwh IS NOT NULL) AS usable_hours,
               COUNT(r.observed_at) AS observed_rows
        FROM buildings b
        LEFT JOIN hourly_readings r ON r.building_code = b.building_code AND {where}
        GROUP BY b.building_code, b.building_name, b.building_type, b.area_m2
        ORDER BY energy_kwh DESC
        """,
        params,
    )
    return {
        "start_date": start,
        "end_date": end,
        "comparison_note": "Within-campus comparison. Building functions and operating patterns differ.",
        "buildings": [
            {
                "building_code": row["building_code"],
                "building_name": row["building_name"],
                "building_type": row["building_type"],
                "area_m2": round(_as_float(row["area_m2"]), 1),
                "energy_kwh": round(_as_float(row["energy_kwh"]), 1),
                "energy_kwh_per_m2": round(_as_float(row["energy_kwh"]) / _as_float(row["area_m2"]), 3) if row["area_m2"] else None,
                "estimated_co2_kg": round(_as_float(row["energy_kwh"]) * grid_factor, 1),
                "coverage_pct": round(_as_float(row["coverage_pct"]), 1),
                "usable_hours": int(row["usable_hours"] or 0),
                "observed_rows": int(row["observed_rows"] or 0),
            }
            for row in rows
        ],
    }


@app.get("/api/activity", tags=["Operating profile"])
def activity(
    start_date: date | None = None,
    end_date: date | None = None,
    building_code: str | None = None,
) -> dict:
    start, end = _resolve_dates(start_date, end_date)
    where, params = _where(start, end, building_code)
    hourly = _query_all(
        f"""
        WITH campus_hour AS (
            SELECT r.observed_at,
                   EXTRACT(HOUR FROM r.observed_at)::INTEGER AS hour,
                   SUM(r.energy_kwh) AS energy_kwh,
                   SUM(r.average_power_kw) AS average_power_kw
            FROM hourly_readings r WHERE {where}
            GROUP BY r.observed_at
        )
        SELECT hour,
               AVG(energy_kwh) AS energy_kwh,
               AVG(average_power_kw) AS average_power_kw,
               COUNT(*) FILTER (WHERE energy_kwh IS NOT NULL) AS usable_hours
        FROM campus_hour
        GROUP BY hour ORDER BY hour
        """,
        params,
    )
    daily = _query_all(
        f"""
        SELECT r.observed_at::date AS campus_date,
               r.activity_level,
               r.working_day,
               SUM(r.energy_kwh) AS daily_kwh
        FROM hourly_readings r WHERE {where}
        GROUP BY r.observed_at::date, r.activity_level, r.working_day
        """,
        params,
    )
    daily_by_band: dict[str, list[float]] = {}
    working_days: dict[str, list[float]] = {"working": [], "non_working": []}
    for row in daily:
        if row["daily_kwh"] is None:
            continue
        total = _as_float(row["daily_kwh"])
        band = row["activity_level"] if row["activity_level"] in {"H", "L"} else "Unknown"
        daily_by_band.setdefault(band, []).append(total)
        working_key = "working" if row["working_day"] == 1 else "non_working" if row["working_day"] == 0 else None
        if working_key:
            working_days[working_key].append(total)

    def mean_values(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 1) if values else None

    profile = {"hourly_profile": [
        {"hour": int(row["hour"]), "energy_kwh": round(_as_float(row["energy_kwh"]), 2), "average_power_kw": round(_as_float(row["average_power_kw"]), 2), "usable_hours": int(row["usable_hours"])}
        for row in hourly
    ]}
    return {
        **profile,
        "calendar_comparison": [
            {"activity_level": band, "days": len(values), "mean_daily_kwh": mean_values(values)}
            for band, values in sorted(daily_by_band.items())
        ],
        "working_day_comparison": [
            {"day_type": label, "days": len(values), "mean_daily_kwh": mean_values(values)}
            for label, values in [("Working day", working_days["working"]), ("Non-working day", working_days["non_working"])]
            if values
        ],
        "schedule_note": "The source calendar marks working days and high/low academic activity. It does not specify each building's opening hours.",
    }


@app.get("/api/opportunities", tags=["Operating profile"])
def opportunities(
    start_date: date | None = None,
    end_date: date | None = None,
    building_code: str | None = None,
) -> dict:
    start, end = _resolve_dates(start_date, end_date)
    where, params = _where(start, end, building_code)
    rows = _query_all(
        f"""
        SELECT b.building_code, b.building_name, b.building_type,
               AVG(r.average_power_kw) FILTER (
                   WHERE r.working_day = 1 AND EXTRACT(HOUR FROM r.observed_at)::INTEGER BETWEEN 9 AND 17
               ) AS daytime_avg_kw,
               AVG(r.average_power_kw) FILTER (
                   WHERE EXTRACT(HOUR FROM r.observed_at)::INTEGER < 6
                      OR EXTRACT(HOUR FROM r.observed_at)::INTEGER >= 22
               ) AS night_avg_kw,
               SUM(r.energy_kwh) FILTER (
                   WHERE EXTRACT(HOUR FROM r.observed_at)::INTEGER < 6
                      OR EXTRACT(HOUR FROM r.observed_at)::INTEGER >= 22
               ) AS night_kwh
        FROM buildings b
        JOIN hourly_readings r ON r.building_code = b.building_code
        WHERE {where}
        GROUP BY b.building_code, b.building_name, b.building_type
        ORDER BY b.building_name
        """,
        params,
    )
    _building_count(building_code)
    items = []
    for row in rows:
        day_kw = _as_float(row["daytime_avg_kw"])
        night_kw = _as_float(row["night_avg_kw"])
        ratio = round(100.0 * night_kw / day_kw, 1) if day_kw > 0 else None
        items.append(
            {
                "building_code": row["building_code"],
                "building_name": row["building_name"],
                "building_type": row["building_type"],
                "daytime_avg_kw": round(day_kw, 2),
                "night_avg_kw": round(night_kw, 2),
                "night_to_day_pct": ratio,
                "night_kwh": round(_as_float(row["night_kwh"]), 1),
                "review_note": (
                    f"Night load averaged {ratio}% of working-day daytime load. Review this against the building's expected use."
                    if ratio is not None
                    else "There is not enough working-day daytime data for a comparison."
                ),
            }
        )
    return {
        "start_date": start,
        "end_date": end,
        "night_window": "00:00–05:59 and 22:00–23:59 local time",
        "day_window": "09:00–17:59 on working days",
        "interpretation_note": "A night-to-day ratio is a review signal, not a measured savings estimate. Dormitory and always-on loads can remain active overnight.",
        "buildings": items,
    }


@app.get("/api/quality", tags=["Data quality"])
def quality(
    start_date: date | None = None,
    end_date: date | None = None,
    building_code: str | None = None,
) -> dict:
    start, end = _resolve_dates(start_date, end_date)
    where, params = _where(start, end, building_code)
    building_count = _building_count(building_code)
    expected_per_building = ((end - start).days + 1) * 24
    summary = _query_one(
        f"""
        SELECT COUNT(*) AS observed_rows,
               COUNT(*) FILTER (WHERE r.energy_kwh IS NOT NULL) AS usable_hours,
               COUNT(*) FILTER (WHERE r.quality_flag = 'partial') AS partial_hours,
               COUNT(*) FILTER (WHERE r.quality_flag = 'missing') AS missing_hours,
               COUNT(*) FILTER (WHERE r.spike_flag) AS spike_hours,
               COUNT(*) FILTER (WHERE r.quality_flag <> 'complete' OR r.spike_flag) AS flagged_rows,
               COALESCE(AVG(r.coverage_pct), 0) AS average_coverage
        FROM hourly_readings r WHERE {where}
        """,
        params,
    )
    per_building = _query_all(
        f"""
        SELECT b.building_code, b.building_name, b.building_type,
               COUNT(r.observed_at) AS observed_rows,
               COUNT(r.observed_at) FILTER (WHERE r.energy_kwh IS NOT NULL) AS usable_hours,
               COUNT(r.observed_at) FILTER (WHERE r.quality_flag = 'partial') AS partial_hours,
               COUNT(r.observed_at) FILTER (WHERE r.quality_flag = 'missing') AS missing_hours,
               COUNT(r.observed_at) FILTER (WHERE r.spike_flag) AS spike_hours,
               COALESCE(AVG(r.coverage_pct), 0) AS average_coverage
        FROM buildings b
        LEFT JOIN hourly_readings r ON r.building_code = b.building_code AND {where}
        WHERE (%s::text IS NULL OR b.building_code = %s)
        GROUP BY b.building_code, b.building_name, b.building_type
        ORDER BY average_coverage ASC, b.building_name
        """,
        params + (building_code, building_code),
    )
    events = _query_all(
        f"""
        SELECT r.observed_at, b.building_name, r.average_power_kw, r.coverage_pct,
               r.quality_flag, r.spike_flag
        FROM hourly_readings r JOIN buildings b USING (building_code)
        WHERE {where} AND (r.quality_flag <> 'complete' OR r.spike_flag)
        ORDER BY r.spike_flag DESC, r.coverage_pct ASC, r.observed_at DESC
        LIMIT 120
        """,
        params,
    )
    expected = expected_per_building * building_count
    usable = int(summary["usable_hours"])
    return {
        "start_date": start,
        "end_date": end,
        "expected_hours": expected,
        "observed_rows": int(summary["observed_rows"]),
        "usable_hours": usable,
        "usable_hour_pct": round(100.0 * usable / expected, 1) if expected else 0,
        "average_meter_coverage_pct": round(_as_float(summary["average_coverage"]), 1),
        "partial_hours": int(summary["partial_hours"]),
        "missing_hours": int(summary["missing_hours"]),
        "statistical_spikes": int(summary["spike_hours"]),
        "flagged_rows": int(summary["flagged_rows"]),
        "status_thresholds": {"healthy_pct": 95, "watch_pct": 75},
        "method_note": "Coverage is the share of expected one-minute samples available in each hour. Hours below 75% coverage are excluded from energy totals. Statistical spikes are review flags, not confirmed equipment faults.",
        "buildings": [
            {
                "building_code": row["building_code"],
                "building_name": row["building_name"],
                "building_type": row["building_type"],
                "observed_rows": int(row["observed_rows"]),
                "usable_hours": int(row["usable_hours"]),
                "coverage_pct": round(_as_float(row["average_coverage"]), 1),
                "usable_hour_pct": round(100.0 * int(row["usable_hours"]) / expected_per_building, 1) if expected_per_building else 0,
                "partial_hours": int(row["partial_hours"]),
                "missing_hours": int(row["missing_hours"]),
                "spike_hours": int(row["spike_hours"]),
                "status": "healthy" if 100.0 * int(row["usable_hours"]) / expected_per_building >= 95 else "watch" if 100.0 * int(row["usable_hours"]) / expected_per_building >= 75 else "attention",
            }
            for row in per_building
        ],
        "events": [
            {
                "observed_at": row["observed_at"],
                "building_name": row["building_name"],
                "average_power_kw": round(_as_float(row["average_power_kw"]), 2) if row["average_power_kw"] is not None else None,
                "coverage_pct": round(_as_float(row["coverage_pct"]), 1),
                "quality_flag": row["quality_flag"],
                "spike_flag": bool(row["spike_flag"]),
            }
            for row in events
        ],
    }


@app.get("/api/quality/export.csv", tags=["Data quality"])
def export_quality(
    start_date: date | None = None,
    end_date: date | None = None,
    building_code: str | None = None,
) -> StreamingResponse:
    start, end = _resolve_dates(start_date, end_date)
    where, params = _where(start, end, building_code)
    _building_count(building_code)

    def csv_rows():
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["observed_at_local", "building", "average_power_kw", "coverage_pct", "quality_flag", "statistical_spike_for_review"])
        yield output.getvalue()
        with closing(connect()) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    f"""
                    SELECT r.observed_at, b.building_name, r.average_power_kw,
                           r.coverage_pct, r.quality_flag, r.spike_flag
                    FROM hourly_readings r JOIN buildings b USING (building_code)
                    WHERE {where} AND (r.quality_flag <> 'complete' OR r.spike_flag)
                    ORDER BY r.observed_at, b.building_name
                    """,
                    params,
                )
                for row in cursor:
                    output.seek(0)
                    output.truncate(0)
                    writer.writerow([
                        row["observed_at"], row["building_name"], row["average_power_kw"],
                        row["coverage_pct"], row["quality_flag"], row["spike_flag"],
                    ])
                    yield output.getvalue()

    filename = f"ecometrics-quality-{start}-{end}.csv"
    return StreamingResponse(
        csv_rows(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
