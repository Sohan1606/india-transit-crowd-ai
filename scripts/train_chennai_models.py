#!/usr/bin/env python3
"""Train the day-granularity Chennai observed-demand family and prove the future path.

Outputs, in ``backend/models/<system_id>/``:
  transitcrowd.joblib        champion regression + classification models, frozen thresholds
  model_report.json          chronological benchmark report (validation-selected champion)
  station_analytics.json     training-window behaviour profiles
  evaluation_replay.json     (a) one-step replay on the held-out window and
                             (b) multi-day recursive projection measured over the same window
  future_forecast.json       forecast for a date after the last observation (today or later)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.features.daily import FEATURE_COLUMNS, TARGET, build_supervised_frame, features_for_target  # noqa: E402
from ml.data_pipeline.cleaning import clean_normalized_demand  # noqa: E402
from ml.evaluation.metrics import regression_metrics  # noqa: E402
from ml.training.forecast import project_future  # noqa: E402
from ml.training.registry import get_model_family, model_family_directory  # noqa: E402
from ml.training.risk import classify_demand  # noqa: E402
from ml.training.train_daily import save_artifacts, train_daily  # noqa: E402


def _regress(bundle: dict, X: pd.DataFrame) -> float:
    return float(np.asarray(bundle["regression_model"].predict(X), dtype=float).reshape(-1)[0])


def one_step_replay(daily: pd.DataFrame, bundle: dict, days, tz: str) -> list[dict]:
    """One-step-ahead prediction for each held-out day, using only true prior observations."""
    predictions, actuals = [], []
    for day in days:
        part = daily.loc[pd.to_datetime(daily["timestamp"]).dt.normalize().eq(pd.Timestamp(day).normalize())]
        for row in part.itertuples():
            try:
                features = features_for_target(daily, row.entity_id, pd.Timestamp(day), timezone=tz)
            except ValueError:
                continue
            predictions.append((row.entity_id, max(_regress(bundle, features[FEATURE_COLUMNS]), 0.0), float(row.demand_count)))
    if not predictions:
        return []
    frame = pd.DataFrame(predictions, columns=["entity_id", "predicted", "actual"])
    overall = regression_metrics(frame["actual"], frame["predicted"])
    per_entity = []
    for entity_id, part in frame.groupby("entity_id"):
        metrics = regression_metrics(part["actual"], part["predicted"])
        per_entity.append({"entity_id": entity_id,
                           "entity_name": bundle["entity_names"].get(entity_id, entity_id),
                           "observations": int(len(part)), **{key: round(value, 4) for key, value in metrics.items()},
                           "mean_actual": round(float(part["actual"].mean()), 2)})
    return [{"overall": {**overall, "evaluated_rows": int(len(frame)),
                         "mape_percent": round(float(np.mean(np.abs(frame["predicted"] - frame["actual"])
                                                            / np.maximum(frame["actual"], 1)) * 100), 3)},
             "per_entity_sample": sorted(per_entity, key=lambda item: item["mae"])[:10]}][0]


def recursive_projection_over_holdout(daily: pd.DataFrame, bundle: dict, cutoff: pd.Timestamp,
                                      holdout_days, tz: str) -> dict:
    """The honest accuracy figure for the FUTURE forecast path: no held-out truth is used."""
    history = daily.loc[pd.to_datetime(daily["timestamp"]) <= cutoff].copy()
    rows = []
    start = pd.Timestamp(cutoff).normalize() + pd.Timedelta(days=1)
    for entity_id in bundle["entity_ids"]:
        if not history["entity_id"].eq(entity_id).any():
            continue
        projected = project_future(history, entity_id, lambda X: _regress(bundle, X),
                                   start, pd.Timestamp(holdout_days[-1]), timezone=tz)
        rows.append(projected)
    if not rows:
        return {}
    projection = pd.concat(rows, ignore_index=True)
    projection = projection[[column for column in projection.columns if not str(column).startswith("_")]]
    truth = daily[["entity_id", "timestamp", "demand_count"]].copy()
    truth["timestamp"] = pd.to_datetime(truth["timestamp"]).dt.normalize()
    joined = projection.merge(truth, left_on=["entity_id", "timestamp"], right_on=["entity_id", "timestamp"], how="inner")
    joined = joined.dropna(subset=["forecast_demand", "demand_count"])
    if joined.empty:
        return {}
    metrics = regression_metrics(joined["demand_count"], joined["forecast_demand"])
    horizon = pd.to_datetime(joined["timestamp"]).dt.normalize()
    early = joined[horizon <= pd.Timestamp(holdout_days[min(6, len(holdout_days) - 1)])]
    late = joined[horizon >= pd.Timestamp(holdout_days[max(0, len(holdout_days) - 7)])]
    return {
        "mode": "recursive multi-day-ahead projection from the training cutoff only",
        "projection_window_caveat": (
            "The window runs from the day after the training cutoff to the last observed day, so it also covers the "
            "validation calendar days. They are not inputs here: nothing after the cutoff enters this audit. It is a "
            "measurement of the serving path, not a second model-selection signal."
        ),
        "why_this_is_the_relevant_number": (
            "Training stopped at the cutoff; every day after it is produced by re-feeding the model's "
            "own forecasts, exactly as the live future-forecast path does. Held-out observations are used "
            "only as answers for scoring, never as inputs."
        ),
        "projection_start": str(pd.Timestamp(cutoff).normalize().date() + pd.Timedelta(days=1)),
        "projection_end": str(pd.to_datetime(joined["timestamp"]).max().date()),
        "evaluated_rows": int(len(joined)),
        "entities": int(joined["entity_id"].nunique()),
        "mae": round(metrics["mae"], 4), "rmse": round(metrics["rmse"], 4), "r2": round(metrics["r2"], 5),
        "smape_percent": round(float(np.mean(2 * np.abs(joined["forecast_demand"] - joined["demand_count"])
                                              / np.maximum(joined["forecast_demand"] + joined["demand_count"], 1)) * 100), 3),
        "first_7_days_mae": round(float(np.mean(np.abs(early["forecast_demand"] - early["demand_count"]))), 4) if len(early) else None,
        "last_7_days_mae": round(float(np.mean(np.abs(late["forecast_demand"] - late["demand_count"]))), 4) if len(late) else None,
    }


def future_forecast_snapshot(daily: pd.DataFrame, bundle: dict, target_day: date, tz: str) -> dict:
    """Forecast a calendar day that has not happened yet; nothing here is an observation.

    Days between the data frontier and the target are produced by the same recursive
    projection that the API uses, so a horizon beyond one day is a genuine multi-day
    forecast rather than an implicitly shorter one-step call.
    """
    data_end = pd.Timestamp(daily["timestamp"].max()).normalize()
    target = pd.Timestamp(target_day.isoformat()).tz_localize(tz)
    horizon = int((target - data_end).days)
    if horizon < 1:
        raise SystemExit(f"Target {target_day} is not in the future relative to the data frontier {data_end.date()}.")
    results: list[dict] = []
    for entity_id in bundle["entity_ids"]:
        try:
            projected = project_future(daily, entity_id, lambda X: _regress(bundle, X),
                                      data_end + pd.Timedelta(days=1), target, timezone=tz,
                                      min_history_days=int(bundle.get("min_history_days", 28)))
            row = projected.iloc[-1]
            if row.get("forecast_demand") is None or pd.isna(row.get("forecast_demand")):
                results.append({"entity_id": entity_id, "error": str(row.get("forecast_error"))})
                continue
            demand = float(row["forecast_demand"])
        except ValueError as exc:
            results.append({"station_id": entity_id, "station_name": bundle["entity_names"].get(entity_id, entity_id),
                            "error": str(exc)})
            continue
        risk, source = classify_demand(demand, entity_id, bundle["system_id"], bundle["risk_thresholds"])
        results.append({
            "station_id": entity_id, "station_name": bundle["entity_names"].get(entity_id, entity_id),
            "predicted_entries": round(demand, 2), "risk_band": risk, "threshold_source": source,
        })
    scored = [row for row in results if "predicted_entries" in row]
    unresolvable = [row for row in results if "predicted_entries" not in row]
    return {
        "kind": "MODEL_FORECAST_NOT_LIVE_COUNT",
        "statement": (
            "These are machine-learned forecasts for a calendar day that has not yet been observed by the "
            "source. They are not live passengers, not occupancy and not a measured count."
        ),
        "system_id": bundle["system_id"], "target_date": target_day.isoformat(),
        "forecast_horizon_days": horizon, "data_frontier": str(data_end.date()),
        "training_cutoff": str(pd.Timestamp(bundle["training_cutoff"]).normalize().date()),
        "model": bundle["regression_model_key"], "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stations": sorted(scored, key=lambda row: -row["predicted_entries"]),
        "top_stations": sorted(scored, key=lambda row: -row["predicted_entries"])[:12],
        "unprojectable_stations": unresolvable,
        "system_total_predicted_entries": round(float(sum(row["predicted_entries"] for row in scored)), 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/processed/chennai_metro_demand_timeseries.csv")
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--system-id", default="chennai-cmrl-metro")
    parser.add_argument("--future-date", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--target-date", default=None, help="Future calendar day to forecast (default: tomorrow).")
    parser.add_argument("--skip-future", action="store_true")
    parser.add_argument("--refresh-only", action="store_true",
                        help="Reuse the saved champion and only rebuild the replay + future snapshots.")
    args = parser.parse_args()
    if not args.data.is_file():
        raise SystemExit(f"Normalized dataset not found: {args.data}. Run download_cmrl_data.py and prepare_chennai_data.py.")
    family = get_model_family(args.system_id)
    tz = str(family["timezone"])
    daily, quality = clean_normalized_demand(pd.read_csv(args.data), timezone=tz)
    metadata_path = args.metadata or args.data.with_suffix(".metadata.json")
    dataset_metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    dataset_metadata["training_input"] = str(args.data.relative_to(ROOT))
    dataset_metadata["training_input_sha256"] = __import__("hashlib").sha256(args.data.read_bytes()).hexdigest()
    dataset_metadata["training_quality_check"] = quality

    output_dir = model_family_directory(ROOT / "backend/models", args.system_id)
    if args.refresh_only:
        import joblib
        bundle = joblib.load(output_dir / "transitcrowd.joblib")
        if bundle.get("bundle_format") != "transitcrowd-model-v2" or bundle.get("granularity") != "day":
            raise SystemExit("Saved bundle is not a current day-granularity bundle; retrain instead of refreshing.")
        if not bundle.get("entity_ids"):
            bundle["entity_ids"] = sorted(bundle.get("entity_names", {}))
        report = json.loads((output_dir / "model_report.json").read_text(encoding="utf-8"))
        result = {"bundle": bundle, "report": report, "train_cutoff": pd.Timestamp(report["split"]["train"]["end"]),
                  "supervised": build_supervised_frame(daily, timezone=tz)}
    else:
        result = train_daily(daily, dataset_metadata=dataset_metadata, tz=tz)
        bundle, report = result["bundle"], result["report"]
        save_artifacts(result, output_dir)

    supervised = result["supervised"]
    # The final 15% window is reported once; use it for both replay modes.
    holdout_days = sorted(pd.to_datetime(supervised["timestamp"]).dt.normalize().unique())
    holdout_days = holdout_days[int(len(holdout_days) * 0.85):]
    replay = {
        "note": "Historical replay modes. Neither is a future forecast; both stop at the last observed day.",
        "held_out_window": {"start": str(pd.Timestamp(holdout_days[0]).date()), "end": str(pd.Timestamp(holdout_days[-1]).date()),
                            "days": int(len(holdout_days))},
        "one_step_replay_using_true_history": one_step_replay(daily, bundle, holdout_days, tz),
        "recursive_projection_over_same_window": recursive_projection_over_holdout(
            daily, bundle, result["train_cutoff"], holdout_days, tz),
        "final_test_partition_reported_once": report["split"]["test"],
    }
    (output_dir / "evaluation_replay.json").write_text(
        json.dumps(json.loads(json.dumps(replay, default=str)), indent=2), encoding="utf-8")

    if not args.skip_future:
        target = date.fromisoformat(args.target_date) if args.target_date else (
            pd.Timestamp(daily["timestamp"].max()).tz_convert(tz).date() + pd.Timedelta(days=1))
        snapshot = future_forecast_snapshot(daily, bundle, target, tz)
        (output_dir / "future_forecast.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print(f"Future forecast written for {snapshot['target_date']} (+{snapshot['forecast_horizon_days']} day(s) past the data frontier).")

    print(f"Rows: train {report['split']['train']['rows']:,} / validation {report['split']['validation']['rows']:,} / test {report['split']['test']['rows']:,}")
    print(f"Regression champion: {report['regression']['champion_name']}  test MAE={report['regression']['models'][[m['key'] for m in report['regression']['models']].index(report['regression']['champion_key'])]['test']['mae']:.2f}")
    print(f"Classification champion: {report['classification']['champion_name']}  test macro-F1={report['classification']['models'][[m['key'] for m in report['classification']['models']].index(report['classification']['champion_key'])]['test']['f1_macro']:.4f}")
    print(f"Recursive projection (future path) MAE={replay['recursive_projection_over_same_window'].get('mae')} RMSE={replay['recursive_projection_over_same_window'].get('rmse')}")
    print(f"Artifacts: {output_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
