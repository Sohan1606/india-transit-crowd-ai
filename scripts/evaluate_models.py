#!/usr/bin/env python3
"""Independently replay held-out metrics for the saved champion artifacts."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.data_pipeline.cleaning import clean_normalized_demand  # noqa: E402
from ml.evaluation.metrics import classification_metrics, regression_metrics  # noqa: E402
from ml.features.forecasting import FEATURE_COLUMNS, TARGET, build_supervised_frame  # noqa: E402
from ml.training.train import _predict_class, _probabilities, _risk_labels, _jsonable  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/processed/namma_metro_station_hourly.csv")
    parser.add_argument("--artifact", type=Path, default=ROOT / "backend/models/bengaluru-namma-metro/transitcrowd.joblib")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if not args.artifact.is_file():
        parser.error(f"Saved model artifact not found: {args.artifact}")
    if not args.data.is_file():
        parser.error(f"Normalized observed-demand data not found: {args.data}")
    bundle = joblib.load(args.artifact)
    timezone = str(bundle.get("model_family", {}).get("timezone", "Asia/Kolkata"))
    hourly, _ = clean_normalized_demand(pd.read_csv(args.data), timezone=timezone)
    frame = build_supervised_frame(hourly, timezone=timezone)
    test = frame.loc[frame["timestamp"] > pd.Timestamp(bundle["validation_cutoff"])].copy()
    if test.empty:
        parser.error("No held-out test samples are available after the saved validation cutoff.")

    regression_prediction = bundle["regression_model"].predict(test[FEATURE_COLUMNS])
    regression = regression_metrics(test[TARGET], regression_prediction)
    labels = _risk_labels(test, bundle["risk_thresholds"])
    class_prediction = _predict_class(bundle["classification_model_key"], bundle["classification_model"], test[FEATURE_COLUMNS])
    class_probabilities = _probabilities(bundle["classification_model_key"], bundle["classification_model"], test[FEATURE_COLUMNS])
    classification = classification_metrics(labels, class_prediction, class_probabilities)
    replay = {
        "replayed_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "dataset": str(args.data.relative_to(ROOT).as_posix()) if args.data.is_relative_to(ROOT) else args.data.name,
        "test_start": pd.Timestamp(test["timestamp"].min()).isoformat(),
        "test_end": pd.Timestamp(test["timestamp"].max()).isoformat(),
        "test_rows": int(len(test)),
        "regression_champion": bundle["regression_model_key"],
        "regression_metrics": regression,
        "classification_champion": bundle["classification_model_key"],
        "classification_metrics": classification,
        "note": "Independent replay of persisted champion artifacts on the recorded latest chronological test partition; no refit and no model selection.",
    }
    output = args.output or args.artifact.parent / "evaluation_replay.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_jsonable(replay), indent=2, allow_nan=False), encoding="utf-8")
    print(f"Held-out rows: {len(test):,} | {replay['test_start']} → {replay['test_end']}")
    print(f"Regression champion {replay['regression_champion']}: MAE={regression['mae']:.4f}, RMSE={regression['rmse']:.4f}, R2={regression['r2']:.5f}")
    print(f"Classification champion {replay['classification_champion']}: macro-F1={classification['f1_macro']:.5f}, HIGH recall={classification['high_recall']:.5f}, SEVERE recall={classification['severe_recall']:.5f}")
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
