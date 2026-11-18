"""Prepare a compact, reproducible hourly view of the public I-BLEND data.

The source archive is not committed to this project. See data/README.md for the
source, license, transformations, and exact command to reproduce the included
hourly CSV from the Figshare archives.
"""

from __future__ import annotations

import argparse
import gzip
import json
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd


TZ = "Asia/Kolkata"
SOURCE_MEMBER = "energy_dataset/all_buildings_power.csv"
SOURCE_COLUMNS = [
    "timestamp",
    "Academic",
    "Boys_main",
    "Boys_backup",
    "Facilities",
    "Girls_main",
    "Girls_backup",
    "Lecture",
    "Library",
    "Mess",
]

BUILDINGS = [
    {"building_code": "academic", "building_name": "Academic building", "building_type": "Academic", "floors": 5, "area_sqft": 61308, "meters": ["Academic"]},
    {"building_code": "lecture", "building_name": "Lecture building", "building_type": "Teaching", "floors": 3, "area_sqft": 17548, "meters": ["Lecture"]},
    {"building_code": "library", "building_name": "Library", "building_type": "Library", "floors": 4, "area_sqft": 26401, "meters": ["Library"]},
    {"building_code": "facilities", "building_name": "Facilities building", "building_type": "Facilities", "floors": 3, "area_sqft": 9769, "meters": ["Facilities"]},
    {"building_code": "dining", "building_name": "Dining building", "building_type": "Dining", "floors": 4, "area_sqft": 50191, "meters": ["Mess"]},
    {"building_code": "boys_dormitory", "building_name": "Boys dormitory", "building_type": "Residential", "floors": 6, "area_sqft": 72745, "meters": ["Boys_main", "Boys_backup"]},
    {"building_code": "girls_dormitory", "building_name": "Girls dormitory", "building_type": "Residential", "floors": 4, "area_sqft": 38126, "meters": ["Girls_main", "Girls_backup"]},
]


def load_calendar(archive_path: Path) -> dict[str, tuple[int | None, str]]:
    """Return date -> (working day, activity band) from the public calendar."""
    calendar: dict[str, tuple[int | None, str]] = {}
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            if not name.startswith("iiitd_calender_schedule/calender_year_") or not name.endswith(".csv"):
                continue
            frame = pd.read_csv(archive.open(name))
            for row in frame.itertuples(index=False):
                day = str(row.Date)[:10]
                working = int(row.working_day) if pd.notna(row.working_day) else None
                activity = str(row.activity).strip().upper()
                calendar[day] = (working, activity if activity in {"H", "L"} else "Unknown")
    return calendar


def aggregate_ready_minutes(minutes: pd.DataFrame) -> list[dict[str, object]]:
    """Aggregate complete sets of minute rows into building-hour records."""
    if minutes.empty:
        return []

    output: list[dict[str, object]] = []
    local_times = minutes["local_time"]
    for building in BUILDINGS:
        meter_values = minutes[building["meters"]].apply(pd.to_numeric, errors="coerce")
        # Dormitory totals require both source meters. A missing backup or mains
        # meter is reported as a coverage problem, rather than being treated as 0.
        minute_power = meter_values.sum(axis=1, min_count=len(building["meters"]))
        series = pd.Series(minute_power.to_numpy(), index=local_times)
        hourly = series.resample("h", label="left", closed="left").agg(["mean", "count"])
        for hour, values in hourly.iterrows():
            valid_minutes = int(values["count"])
            coverage = min(100.0, valid_minutes * 100.0 / 60.0)
            average_kw = float(values["mean"]) / 1000.0 if valid_minutes else None
            usable = average_kw is not None and coverage >= 75.0
            energy_kwh = average_kw if usable else None
            quality = "missing" if valid_minutes == 0 else ("complete" if coverage >= 95.0 else "partial")
            output.append(
                {
                    "observed_at": hour.strftime("%Y-%m-%d %H:%M:%S"),
                    "building_code": building["building_code"],
                    "average_power_kw": round(average_kw, 6) if average_kw is not None else "",
                    "energy_kwh": round(energy_kwh, 6) if energy_kwh is not None else "",
                    "coverage_pct": round(coverage, 1),
                    "working_day": "",
                    "activity_level": "Unknown",
                    "quality_flag": quality,
                    "spike_flag": 0,
                }
            )
    return output


def add_calendar_context(records: list[dict[str, object]], calendar: dict[str, tuple[int | None, str]]) -> None:
    for row in records:
        day = str(row["observed_at"])[:10]
        working, activity = calendar.get(day, (None, "Unknown"))
        row["working_day"] = "" if working is None else working
        row["activity_level"] = activity


def add_statistical_spike_flags(frame: pd.DataFrame) -> None:
    """Flag unusually high hourly loads for review, not as proven equipment faults.

    The comparison group is building × weekday × hour × activity band. At least
    12 historical observations are required. A point is flagged only when it is
    both more than 2.5x the group median and over eight robust median deviations
    above it. The dashboard labels these as statistical spikes for human review.
    """
    valid = frame["average_power_kw"].notna()
    scope = frame.loc[valid].copy()
    times = pd.to_datetime(scope["observed_at"])
    scope["weekday"] = times.dt.dayofweek
    scope["hour"] = times.dt.hour
    group_columns = ["building_code", "working_day", "activity_level", "weekday", "hour"]
    grouped = scope.groupby(group_columns, dropna=False)["average_power_kw"]
    medians = grouped.transform("median")
    counts = grouped.transform("count")
    deviations = (scope["average_power_kw"] - medians).abs()
    mad = deviations.groupby([scope[column] for column in group_columns], dropna=False).transform("median")
    threshold = medians + 8.0 * 1.4826 * mad.clip(lower=0.05)
    spike_mask = (counts >= 12) & (scope["average_power_kw"] > medians * 2.5) & (scope["average_power_kw"] > threshold)
    frame["spike_flag"] = 0
    frame.loc[scope.index[spike_mask], "spike_flag"] = 1


def write_buildings(out_path: Path) -> None:
    rows = []
    for building in BUILDINGS:
        rows.append(
            {
                "building_code": building["building_code"],
                "building_name": building["building_name"],
                "building_type": building["building_type"],
                "floors": building["floors"],
                "area_m2": round(float(building["area_sqft"]) * 0.09290304, 2),
                "source_area_sqft": building["area_sqft"],
            }
        )
    pd.DataFrame(rows).to_csv(out_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the EcoMetrics hourly I-BLEND dataset.")
    parser.add_argument("--energy-archive", required=True, type=Path, help="Path to energy_dataset.zip from Figshare")
    parser.add_argument("--calendar-archive", required=True, type=Path, help="Path to the IIITD calendar zip from Figshare")
    parser.add_argument("--output", default=Path("data/energy_hourly.csv.gz"), type=Path)
    parser.add_argument("--start-date", default="2013-08-10", type=date.fromisoformat)
    parser.add_argument("--end-date", default="2017-12-31", type=date.fromisoformat)
    args = parser.parse_args()
    if args.end_date < args.start_date:
        parser.error("--end-date must be on or after --start-date")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    buildings_path = args.output.parent / "buildings.csv"
    calendar = load_calendar(args.calendar_archive)
    start_at = pd.Timestamp(args.start_date)
    end_at = pd.Timestamp(args.end_date) + pd.Timedelta(days=1)
    records: list[dict[str, object]] = []
    total_source_rows = 0
    carry = pd.DataFrame(columns=SOURCE_COLUMNS)

    with zipfile.ZipFile(args.energy_archive) as archive:
        if SOURCE_MEMBER not in archive.namelist():
            raise FileNotFoundError(f"{SOURCE_MEMBER} was not found in {args.energy_archive}")
        with archive.open(SOURCE_MEMBER) as source:
            chunks = pd.read_csv(source, usecols=SOURCE_COLUMNS, na_values=["NA"], chunksize=100_000, low_memory=False)
            for raw in chunks:
                total_source_rows += len(raw)
                batch = pd.concat([carry, raw], ignore_index=True)
                batch = batch.drop_duplicates(subset=["timestamp"], keep="last")
                local = pd.to_datetime(batch["timestamp"], unit="s", utc=True).dt.tz_convert(TZ).dt.tz_localize(None)
                batch = batch.assign(local_time=local)

                complete_before = batch["local_time"].max().floor("h")
                ready = batch.loc[batch["local_time"] < complete_before].copy()
                carry = batch.loc[batch["local_time"] >= complete_before, SOURCE_COLUMNS].copy()

                ready = ready.loc[(ready["local_time"] >= start_at) & (ready["local_time"] < end_at)]
                if not ready.empty:
                    records.extend(aggregate_ready_minutes(ready))

    if not carry.empty:
        carry["local_time"] = pd.to_datetime(carry["timestamp"], unit="s", utc=True).dt.tz_convert(TZ).dt.tz_localize(None)
        carry = carry.loc[(carry["local_time"] >= start_at) & (carry["local_time"] < end_at)]
        if not carry.empty:
            records.extend(aggregate_ready_minutes(carry))

    if not records:
        raise RuntimeError("No hourly records were produced. Check the archive and selected date window.")

    add_calendar_context(records, calendar)
    frame = pd.DataFrame.from_records(records)
    frame["average_power_kw"] = pd.to_numeric(frame["average_power_kw"], errors="coerce")
    frame["energy_kwh"] = pd.to_numeric(frame["energy_kwh"], errors="coerce")
    frame["coverage_pct"] = pd.to_numeric(frame["coverage_pct"], errors="coerce").fillna(0.0)
    add_statistical_spike_flags(frame)
    frame = frame.sort_values(["observed_at", "building_code"], kind="stable")

    field_order = ["observed_at", "building_code", "average_power_kw", "energy_kwh", "coverage_pct", "working_day", "activity_level", "quality_flag", "spike_flag"]
    frame[field_order].to_csv(args.output, index=False, compression="gzip", float_format="%.6f")
    write_buildings(buildings_path)

    profile = {
        "source": "I-BLEND / IIIT-Delhi",
        "timezone": TZ,
        "selected_start": str(frame["observed_at"].min()),
        "selected_end": str(frame["observed_at"].max()),
        "source_rows_scanned": total_source_rows,
        "hourly_building_records": int(len(frame)),
        "building_count": int(frame["building_code"].nunique()),
        "complete_hours": int((frame["quality_flag"] == "complete").sum()),
        "partial_hours": int((frame["quality_flag"] == "partial").sum()),
        "missing_hours": int((frame["quality_flag"] == "missing").sum()),
        "statistical_spikes_for_review": int(frame["spike_flag"].sum()),
        "reproduction_command": "python scripts/prepare_dataset.py --energy-archive energy_dataset.zip --calendar-archive iiitd_calender_schedule.zip",
    }
    (args.output.parent / "dataset_profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
    print(json.dumps(profile, indent=2))
    print(f"Wrote {args.output} ({args.output.stat().st_size / (1024 * 1024):.2f} MiB)")


if __name__ == "__main__":
    main()
