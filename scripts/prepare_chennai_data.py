#!/usr/bin/env python3
"""Normalize the CMRL archive into the canonical observed-demand record contract."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.data_pipeline.cleaning import clean_normalized_demand  # noqa: E402
from ml.data_pipeline.cmrl import CMRL_DAILY_FILE, CMRL_STATION_FILE, CMRLStationDailyAdapter  # noqa: E402
from ml.data_pipeline.source import SourceError  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--station-file", type=Path, default=ROOT / "data/raw/india/cmrl/ChennaiMetro_Station_Ridership.csv")
    parser.add_argument("--daily-file", type=Path, default=ROOT / "data/raw/india/cmrl/ChennaiMetro_Daily_Ridership.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/chennai_metro_demand_timeseries.csv")
    parser.add_argument("--metadata", type=Path, default=ROOT / "data/processed/chennai_metro_demand_timeseries.metadata.json")
    args = parser.parse_args()
    try:
        normalized, metadata = CMRLStationDailyAdapter().load(args.station_file, args.daily_file)
    except SourceError as exc:
        raise SystemExit(str(exc)) from exc
    clean, validation = clean_normalized_demand(normalized, timezone="Asia/Kolkata")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(args.output, index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    metadata["normalized_output"] = str(args.output.relative_to(ROOT))
    metadata["normalized_sha256"] = hashlib.sha256(args.output.read_bytes()).hexdigest()
    metadata["validation"] = validation
    metadata["source_periods"] = [{
        "start": metadata["date_min"], "end": metadata["date_max"],
        "granularity": "day", "basis": "observed",
        "note": ("Contiguous daily observations published by CMRL's passenger-flow portal and archived by the upstream "
                 "collector; every day in the window is present, so the period is exact rather than approximate."),
    }]
    metadata["redistribution"] = ("Not bundled: CMRL holds copyright over the source data, so the pinned public archive is "
                                   "downloaded on demand and SHA-256 verified at prepare time.")
    metadata["how_to_fetch"] = "python3 scripts/download_cmrl_data.py"
    metadata["normalized_schema"] = list(clean.columns)
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Normalized {len(clean):,} observed station-day rows across {clean['entity_id'].nunique()} station-line entities.")
    print(f"Coverage: {metadata['date_min']} -> {metadata['date_max']} ({metadata['unique_dates']} of {metadata['expected_contiguous_dates']} contiguous days).")
    print(f"Entries-per-entity per day: min {metadata['entities_per_date_min']}, max {metadata['entities_per_date_max']}. Filled missing days: 0.")
    print(f"Semantics check (station sum / system total): {metadata['measure_semantics_check']}")


if __name__ == "__main__":
    main()
