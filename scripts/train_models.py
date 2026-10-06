#!/usr/bin/env python3
"""Train benchmarks for a registered India transit mode/operator family."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.data_pipeline.cleaning import clean_normalized_demand  # noqa: E402
from ml.training.registry import get_model_family, model_family_directory  # noqa: E402
from ml.training.train import train_and_save  # noqa: E402
from scripts.render_model_report import render as render_report  # noqa: E402


def default_data_path() -> Path:
    return ROOT / "data/processed/namma_metro_station_hourly.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=default_data_path())
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Defaults to backend/models/<registered system_id>.")
    parser.add_argument("--metadata", type=Path, default=None,
                        help="Optional source metadata JSON; defaults to the normalized file's adjacent .metadata.json.")
    args = parser.parse_args()
    if not args.data.is_file():
        parser.error(f"Normalized dataset not found: {args.data}. Run scripts/download_data.py and scripts/prepare_data.py first.")
    raw = pd.read_csv(args.data)
    if "system_id" not in raw.columns or raw.empty:
        parser.error("Normalized demand input must include rows with one registered system_id.")
    system_id = str(raw["system_id"].iloc[0])
    family = get_model_family(system_id)
    hourly, quality = clean_normalized_demand(raw, timezone=str(family.get("timezone", "Asia/Kolkata")))
    system_id = str(hourly["system_id"].iloc[0])
    output_dir = args.output_dir or model_family_directory(ROOT / "backend/models", system_id)
    meta_path = args.metadata or args.data.with_suffix(".metadata.json")
    dataset_metadata = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    dataset_metadata["training_input"] = str(args.data.relative_to(ROOT)) if args.data.is_relative_to(ROOT) else args.data.name
    dataset_metadata["training_input_sha256"] = __import__("hashlib").sha256(args.data.read_bytes()).hexdigest()
    dataset_metadata["training_quality_check"] = quality
    report = train_and_save(hourly, output_dir, dataset_metadata)
    human_report = ROOT / "docs/model_report.md"
    human_report.parent.mkdir(parents=True, exist_ok=True)
    human_report.write_text(render_report(report), encoding="utf-8")
    print(f"Human-readable report: {human_report}")
    print("Champions selected on validation (the final test did not select models):")
    print(f"Regression: {report['regression']['champion_name']}")
    print(f"Classification: {report['classification']['champion_name']}")
    print(f"System family: {system_id}")
    print(f"Artifacts: {output_dir}")


if __name__ == "__main__":
    main()
