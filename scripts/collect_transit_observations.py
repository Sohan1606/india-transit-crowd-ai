#!/usr/bin/env python3
"""Append-only collector that grows a genuine longitudinal demand history.

Why this exists
---------------
Mumbai's suburban railway has real observed passenger counts only as isolated survey
cross-sections (one typical weekday per survey window), so no future-demand model can
be trained from it today. The only way to get a longitudinal series is to accumulate
observations over time. This script is that accumulation step: each run stores what the
source reported, when it was reported, and a hash of the raw payload, and it never
fills, interpolates or back-fills a missing day.

Two ingestion modes
-------------------
``--source cmrl``      fetch the official CMRL passenger-flow endpoint for the previous
                       complete day and record station-level entries plus the system total.
``--source manual``    ingest a locally prepared CSV (station, date, count, direction...)
                       for operators that publish no machine-readable feed (Mumbai suburban
                       railway, BEST, MMMOCL's Looker dashboard).

Storage layout (git-ignored by design; see docs/chennai-metro-dataset.md)
    data/collected/observations-YYYY-MM-DD.jsonl   one immutable file per collection date
    data/collected/observations.csv                consolidated canonical view, rebuilt
    data/collected/raw/PAYLOAD-<sha256>.json       verbatim payloads, hashed

Run ``--status`` to see coverage and gaps without collecting anything.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.data_pipeline.cmrl import (  # noqa: E402
    CMRL_SOURCE_ID, CMRL_STATION_NAMES, CMRL_SYSTEM_ID, resolve_station_code,
)
from ml.data_pipeline.source import BMRCL_TIMEZONE  # noqa: E402

COLLECT_ROOT = ROOT / "data/collected"
USER_AGENT = "india-transit-crowd-ai/1.0 (data collector; research use)"
MUMBAI_SYSTEM_ID = "mumbai-suburban-railway"
MANUAL_REQUIRED_COLUMNS = ["station_id", "station_name", "date", "demand_count"]
MANUAL_OPTIONAL_COLUMNS = ["line_id", "direction", "time_interval", "measure", "service_type", "note"]


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _utc_now() -> str:
    return datetime.now(dt_timezone.utc).isoformat(timespec="seconds")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fetch_json(url: str, timeout: int = 45) -> tuple[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed official host
        payload = response.read().decode("utf-8", errors="replace")
    return payload, json.loads(payload)


def store_raw(payload_text: str, directory: Path) -> Path:
    digest = _sha256(payload_text)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"PAYLOAD-{digest}.json"
    if path.exists() and path.read_text(encoding="utf-8") != payload_text:
        raise SystemExit(f"Hash collision detected for {path.name}; refusing to overwrite.")
    path.write_text(payload_text, encoding="utf-8")
    return path


def existing_keys(jsonl_root: Path) -> set[tuple[str, str, str, str]]:
    """(source_id, entity_id, timestamp, measure) already collected — duplicates are refused."""
    seen: set[tuple[str, str, str, str]] = set()
    for file in sorted(jsonl_root.glob("observations-*.jsonl")):
        for line in file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            seen.add((str(record.get("source_id")), str(record.get("entity_id")),
                      str(record.get("timestamp")), str(record.get("measure"))))
    return seen


def collect_cmrl(target_day: date, raw_dir: Path, seen: set) -> list[dict[str, Any]]:
    """Read yesterday's station entries and system total from the official portal API.

    The payload carries no date field, so the observation day is inferred from the day
    index (``1`` = last complete day) and recorded in ``date_inference``. The upstream
    dashboard itself lags by roughly a day, which is exactly why the collector is run
    daily rather than on demand.
    """
    base = "https://commuters-dataapi.chennaimetrorail.org/api/PassengerFlow"
    station_text, station_payload = fetch_json(f"{base}/stationData/1")
    total_text, totals = fetch_json(f"{base}/allTicketCount/1")
    station_file = store_raw(station_text, raw_dir)
    total_file = store_raw(total_text, raw_dir)
    stamp = _utc_now()
    timestamp = f"{target_day.isoformat()}T00:00:00+05:30"
    date_inference = ("day index 1 in the CMRL API means the last complete day; the payload itself is unlabelled, "
                      f"so the collector records the run date minus one day in {BMRCL_TIMEZONE}")
    lines = station_payload if isinstance(station_payload, list) else [station_payload]
    rows: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for block in lines:
        line = str(block.get("line") or "").strip().zfill(2)
        categories = list(block.get("categories") or [])
        series = next((item for item in block.get("series", []) if str(item.get("name")) == "Total"), None)
        if not categories or series is None:
            continue
        for name, value in zip(categories, series.get("data") or []):
            code = resolve_station_code(str(name))
            if code is None:
                unmatched.append(f"{line}:{name}")
                continue
            try:
                count = int(float(value))
            except (TypeError, ValueError):
                continue
            if count < 0:
                continue
            record = {
                "system_id": CMRL_SYSTEM_ID, "entity_type": "STATION", "entity_id": f"line-{line}-{code.lower()}",
                "entity_name": f"{CMRL_STATION_NAMES[code]} (Line {line})", "timestamp": timestamp,
                "date": target_day.isoformat(), "time_interval": "P1D", "demand_count": count,
                "measure": "daily_station_entries", "unit": "passengers", "observation_type": "observed",
                "source_id": CMRL_SOURCE_ID, "line_id": line, "direction": None, "service_type": None,
                "collection_timestamp_utc": stamp, "source_payload_day_index": 1, "date_inference": date_inference,
                "raw_payload_sha256": station_file.stem.replace("PAYLOAD-", ""), "raw_payload_file": station_file.name,
                "source_page": f"{base}/stationData/1",
                "provenance": "official CMRL passenger-flow portal API",
                "licence_note": "CMRL copyright; stored locally for research use, not redistributed by this project",
            }
            key = (record["source_id"], record["entity_id"], timestamp, record["measure"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(record)
    if unmatched:
        print(f"WARNING: {len(unmatched)} station label(s) not in the pinned code map were skipped: "
              f"{', '.join(sorted(set(unmatched))[:6])}. Update CMRL_API_STATION_CODES after verifying with CMRL.")
    system_total = None
    if isinstance(totals, dict):
        try:
            system_total = int(float(totals.get("totalTickets")))
        except (TypeError, ValueError):
            system_total = None
    if system_total is not None and system_total >= 0:
        record = {
            "system_id": CMRL_SYSTEM_ID, "entity_type": "SYSTEM", "entity_id": "chennai-metro-network",
            "entity_name": "Chennai Metro network ticket count", "timestamp": timestamp, "date": target_day.isoformat(),
            "time_interval": "P1D", "demand_count": system_total, "measure": "daily_system_tickets",
            "unit": "tickets", "observation_type": "observed", "source_id": CMRL_SOURCE_ID,
            "collection_timestamp_utc": stamp, "source_payload_day_index": 1, "date_inference": date_inference,
            "raw_payload_sha256": total_file.stem.replace("PAYLOAD-", ""), "raw_payload_file": total_file.name,
            "source_page": f"{base}/allTicketCount/1", "provenance": "official CMRL passenger-flow portal API",
            "licence_note": "CMRL copyright; not redistributed",
        }
        if (record["source_id"], record["entity_id"], timestamp, record["measure"]) not in seen:
            rows.append(record)
    station_sum = sum(row["demand_count"] for row in rows if row["entity_type"] == "STATION")
    if system_total and station_sum:
        print(f"Cross-check: station sum {station_sum:,} vs system ticket count {system_total:,} "
              f"(ratio {station_sum / system_total:.4f}); ~1.0 confirms entries-only semantics.")
    return rows


def collect_manual(csv_path: Path, source_id: str, system_id: str, raw_dir: Path, seen: set) -> list[dict[str, Any]]:
    text = csv_path.read_text(encoding="utf-8")
    stored = store_raw(text, raw_dir)
    stamp, rows = _utc_now(), []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in MANUAL_REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"{csv_path} is missing required column(s): {', '.join(missing)}")
        for line_number, entry in enumerate(reader, start=2):
            try:
                day = date.fromisoformat(str(entry["date"]).strip())
                count = int(float(str(entry["demand_count"]).strip()))
            except (TypeError, ValueError) as exc:
                raise SystemExit(f"{csv_path}:{line_number}: unreadable date or demand_count ({exc})") from exc
            if count < 0:
                raise SystemExit(f"{csv_path}:{line_number}: negative counts are not accepted; a closed station is reported by the operator, not inferred.")
            timestamp = f"{day.isoformat()}T00:00:00+05:30"
            entity_id = str(entry["station_id"]).strip().lower()
            interval = (entry.get("time_interval") or "P1D").strip()
            measure = (entry.get("measure") or "daily_station_entries").strip()
            record = {
                "system_id": system_id, "entity_type": "STATION", "entity_id": entity_id,
                "entity_name": str(entry["station_name"]).strip(), "timestamp": timestamp, "date": day.isoformat(),
                "time_interval": interval, "demand_count": count, "measure": measure, "unit": "passengers",
                "observation_type": "observed", "source_id": source_id,
                "collection_timestamp_utc": stamp,
                "source_timestamp": str(entry.get("note") or "").strip() or None,
                "raw_payload_sha256": _sha256(text), "raw_payload_file": stored.name,
                "line_id": (entry.get("line_id") or None), "direction": (entry.get("direction") or None),
                "service_type": (entry.get("service_type") or None),
                "provenance": f"operator-published figure entered by hand from {csv_path.name}; verify against the source before use",
            }
            key = (source_id, entity_id, timestamp, measure)
            if key in seen:
                continue
            seen.add(key)
            rows.append(record)
    return rows


def rebuild_consolidated(jsonl_root: Path, csv_path: Path) -> int:
    records: dict[str, dict[str, Any]] = {}
    for file in sorted(jsonl_root.glob("observations-*.jsonl")):
        for line in file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            records[record["raw_payload_sha256"][:12] + "|" + "|".join(
                str(record.get(key)) for key in ("source_id", "entity_id", "timestamp", "measure"))] = record
    if not records:
        return 0
    ordered = sorted(records.values(), key=lambda item: (item["timestamp"], item["system_id"], item["entity_id"]))
    columns = ["system_id", "entity_id", "entity_name", "entity_type", "timestamp", "time_interval", "demand_count",
               "measure", "unit", "observation_type", "source_id", "collection_timestamp_utc", "raw_payload_sha256",
               "raw_payload_file", "line_id", "direction", "service_type", "provenance", "licence_note"]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ordered)
    return len(ordered)


def status(jsonl_root: Path) -> None:
    files = sorted(jsonl_root.glob("observations-*.jsonl"))
    records = [json.loads(line) for file in files for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"collection files: {len(files)}   records: {len(records)}")
    if not records:
        print("nothing collected yet; run with --source cmrl or --source manual --input <csv>")
        return
    for system_id in sorted({str(r["system_id"]) for r in records}):
        subset = [r for r in records if r["system_id"] == system_id]
        days = sorted({date.fromisoformat(r["date"]) for r in subset})
        per_day: dict[str, int] = {}
        for record in subset:
            per_day[record["date"]] = per_day.get(record["date"], 0) + 1
        span = (days[-1] - days[0]).days
        missing = [(days[0] + timedelta(days=offset)).isoformat() for offset in range(span + 1)
                   if (days[0] + timedelta(days=offset)).isoformat() not in per_day]
        print(f"  {system_id}: {len(days)} observed day(s) {days[0].isoformat()}..{days[-1].isoformat()}, "
              f"{len(subset)} records, records-per-day min {min(per_day.values())} max {max(per_day.values())}")
        print(f"    collection gaps: {len(missing)} day(s)" + (f" (first: {', '.join(missing[:5])})" if missing else ""))
        print(f"    distinct collection stamps: {len({r['collection_timestamp_utc'] for r in subset})}")
    print("A gap means the collector did not run or the source published nothing; no gap is ever filled with a guess.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["cmrl", "manual"], help="Which observed-demand source to poll.")
    parser.add_argument("--input", type=Path, help="CSV to ingest with --source manual.")
    parser.add_argument("--system-id", default=MUMBAI_SYSTEM_ID, help="System recorded for --source manual rows.")
    parser.add_argument("--source-id", default="mumbai-manual-operator-figures", help="Provenance key for manual rows.")
    parser.add_argument("--date", default=None, help="Observation date (YYYY-MM-DD). Default: the source's reported day.")
    parser.add_argument("--outdir", type=Path, default=COLLECT_ROOT)
    parser.add_argument("--status", action="store_true", help="Report coverage and gaps, collecting nothing.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate, but write nothing.")
    args = parser.parse_args()

    jsonl_root = args.outdir
    if args.status:
        status(jsonl_root)
        return
    if not args.source:
        parser.error("--source is required unless --status is used")

    target = date.fromisoformat(args.date) if args.date else (
        datetime.now(tz=dt_timezone(timedelta(hours=5, minutes=30))).date() - timedelta(days=1))
    jsonl_root.mkdir(parents=True, exist_ok=True)
    seen = existing_keys(jsonl_root)
    if args.source == "cmrl":
        rows = collect_cmrl(target, jsonl_root / "raw", seen)
    else:
        if not args.input or not args.input.is_file():
            parser.error("--source manual requires --input pointing at an existing CSV")
        rows = collect_manual(args.input, args.source_id, args.system_id, jsonl_root / "raw", seen)
    if not rows:
        print("No new observations: every (source, station, day, measure) key was already collected.")
        return
    if args.dry_run:
        print(f"[dry-run] would append {len(rows)} record(s) covering {len({r['date'] for r in rows})} day(s).")
        for row in rows[:3]:
            print("   ", {key: row[key] for key in ("timestamp", "entity_id", "demand_count", "source_id")})
        return
    output = jsonl_root / f"observations-{target.isoformat()}.jsonl"
    with output.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    total = rebuild_consolidated(jsonl_root, jsonl_root / "observations.csv")
    print(f"Appended {len(rows)} record(s) to {_display(output)}")
    print(f"Consolidated canonical view rebuilt: {_display(jsonl_root / 'observations.csv')} ({total} records)")
    print("Note: nothing was interpolated. Days with no collection stay absent and appear as gaps in --status.")


if __name__ == "__main__":
    main()
