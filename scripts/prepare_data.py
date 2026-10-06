#!/usr/bin/env python3
"""Normalize and validate the pinned BMRCL source into the shared record contract."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.data_pipeline.cleaning import clean_normalized_demand  # noqa: E402
from ml.data_pipeline.source import BMRCLRidershipAdapter, SourceError  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/raw/india/bmrcl-station-hourly.csv.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/namma_metro_station_hourly.csv")
    parser.add_argument("--metadata", type=Path, default=ROOT / "data/processed/namma_metro_station_hourly.metadata.json")
    args = parser.parse_args()
    try:
        normalized, metadata = BMRCLRidershipAdapter().load(args.input)
    except SourceError as exc:
        raise SystemExit(str(exc)) from exc
    clean, validation = clean_normalized_demand(normalized)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(args.output, index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    metadata["normalized_output"] = str(args.output.relative_to(ROOT)) if args.output.is_relative_to(ROOT) else args.output.name
    metadata["normalized_sha256"] = hashlib.sha256(args.output.read_bytes()).hexdigest()
    metadata["validation"] = validation
    metadata["normalized_schema"] = list(clean.columns)
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Normalized {len(clean):,} observed station-hour rows across {clean['entity_id'].nunique()} stations.")
    print(f"Coverage: {metadata['date_min']} → {metadata['date_max']} (source periods remain discontinuous).")
    print(f"Preserved explicit zeros: {metadata['explicit_zero_observations']:,}; filled missing hours: 0.")
    print(f"Saved {args.output}\nMetadata: {args.metadata}")


if __name__ == "__main__":
    main()
