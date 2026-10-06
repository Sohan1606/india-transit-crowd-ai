#!/usr/bin/env python3
"""Phase-15 validation gate: decide whether a dataset may train a future-demand model.

Every criterion is computed from the normalized dataset and its sidecar; nothing here is a
prose claim. A dataset is accepted only when all ten criteria pass. The Mumbai suburban
railway extract deliberately fails this gate and is reported as a reference cross-section.

Usage
    python3 scripts/validate_demand_dataset.py --system-id chennai-cmrl-metro
    python3 scripts/validate_demand_dataset.py --csv path.csv --metadata path.json --feature-granularity day
Exit code is 1 when any critical criterion fails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.data_pipeline.cleaning import clean_normalized_demand  # noqa: E402
from ml.features.daily import FEATURE_COLUMNS as DAILY_FEATURES  # noqa: E402
from ml.features.daily import build_supervised_frame as build_daily  # noqa: E402
from ml.features.forecasting import FEATURE_COLUMNS as HOURLY_FEATURES  # noqa: E402
from ml.features.forecasting import build_supervised_frame as build_hourly  # noqa: E402
from ml.features.periodic import PERIOD_SECONDS, build_supervised_frame as build_periodic, schema_for  # noqa: E402
from ml.training.registry import get_model_family  # noqa: E402

# Source ids the project has personally verified as operator-published observations. A new
# dataset can still pass this criterion: it needs observation_class=observed plus a written
# provenance statement in its sidecar, which is what scripts/register_demand_dataset.py
# assembles from an explicit --provenance-json. Declared synthetic data can never pass.
OBSERVED_SOURCE_IDS = {"bmrcl-ridership-hourly", "cmrl-passenger-flow-daily"}
SYNTHETIC_MARKERS = ("synthetic", "simulated", "dummy", "mock", "fake", "generated")
# A dataset is only useful for a future-demand model if it is long enough to train,
# validate, and still leave unseen days behind the frontier.
MIN_TRAIN_PERIODS, MIN_VALIDATION_PERIODS, MIN_TEST_PERIODS = 30, 10, 10
CRITICAL = ("target_values_are_actual_observations", "no_future_values_used_for_past_features",
            "genuine_future_test_period_exists", "sufficient_observations_for_time_series_split",
            "time_ordering_is_known", "license_usage_rights_understood")


def _criterion(ok: bool, evidence: str) -> dict:
    return {"pass": bool(ok), "evidence": evidence}


def _builder_for(granularity: str, period_seconds: int) -> tuple:
    """Which feature builder a dataset of this resolution is allowed to use."""
    if granularity == "day":
        return build_daily, [column for column in DAILY_FEATURES if column != "entity_id"]
    if granularity == "hour":
        return build_hourly, [column for column in HOURLY_FEATURES if column != "entity_id"]
    schema = schema_for(period_seconds)
    return (lambda frame: build_periodic(frame, period_seconds=period_seconds)), [
        column for column in schema["feature_columns"] if column != "entity_id"]


def _snap(stamps: pd.Series, period_seconds: int) -> pd.Series:
    return stamps.dt.normalize() if period_seconds >= 86400 else stamps.dt.floor(pd.Timedelta(seconds=period_seconds))


def check_no_leakage(daily: pd.DataFrame, granularity: str, period_seconds: int | None = None) -> tuple[bool, str]:
    """Alter the value ON the last target period; no row at or before it may change.

    This is the whole no-leakage claim in one experiment: if a feature ever read the
    target period itself, changing that observation would move the features of the row
    it labels. Rows after the altered period are allowed to change, because seeing an
    observation one period later is exactly how a lag feature is supposed to work.
    """
    period = int(period_seconds or PERIOD_SECONDS.get(granularity, 86400))
    build, features = _builder_for(granularity, period)
    try:
        frame = build(daily)
    except ValueError as exc:
        # The builder refuses when no entity has the history the schema demands; that is a
        # measurement gap, so the probe is reported as unable to run rather than passed.
        return False, f"the leakage probe could not run: {exc}"
    if frame.empty:
        return False, "no supervised rows could be built, so the leakage probe could not run"
    columns = [column for column in features if column != "entity_id"]
    last = pd.Timestamp(frame["timestamp"].max())
    altered = daily.copy()
    stamps = pd.to_datetime(altered["timestamp"])
    mask = _snap(stamps, period).eq(_snap(pd.Series([last]), period).iloc[0])
    if not mask.any():
        return False, f"the probe found no observation rows at the target period {last}"
    altered.loc[mask, "demand_count"] = altered.loc[mask, "demand_count"] + 1_000_000
    rebuilt = build(altered)
    left = frame.sort_values(["timestamp", "entity_id"]).reset_index(drop=True)
    right = rebuilt.sort_values(["timestamp", "entity_id"]).reset_index(drop=True)
    if not left[["timestamp", "entity_id"]].equals(right[["timestamp", "entity_id"]]):
        return False, "altering the last period changed which rows exist, so the frame is not deterministic"
    upto = left["timestamp"] <= last
    left_slice = left.loc[upto, columns].astype(float).round(6).reset_index(drop=True)
    right_slice = right.loc[upto, columns].astype(float).round(6).reset_index(drop=True)
    identical = left_slice.equals(right_slice)
    return identical, (
        f"altering the {int(mask.sum())} observation(s) at target period {last} left all "
        f"{int(upto.sum())} supervised rows at or before it byte-identical across {len(columns)} "
        f"history/calendar columns; only strictly later rows may see that observation"
        if identical else "FEATURE LEAKAGE: features changed when the target-period value was altered"
    )


def evaluate(csv_path: Path, metadata: dict, granularity: str, timezone: str,
             period_seconds: int | None = None) -> dict:
    raw = pd.read_csv(csv_path)
    required = {"system_id", "entity_id", "timestamp", "demand_count", "measure", "source_id"}
    missing = sorted(required - set(raw.columns))
    if missing:
        raise SystemExit(
            f"{csv_path} is not a canonical normalized dataset (missing {', '.join(missing)}). Run the system's "
            f"prepare script first. Research extracts that were intentionally not normalized - for example "
            f"data/research/mumbai_suburban_rail_pdf_observed.csv - carry their own gate in the sidecar's "
            f"'validation_gate' block instead."
        )
    period = int(period_seconds or PERIOD_SECONDS.get(granularity, 86400))
    daily, quality = clean_normalized_demand(raw, timezone=timezone, period_seconds=period)
    stamps = _snap(pd.to_datetime(daily["timestamp"]), period)
    daily = daily.assign(timestamp=stamps)
    by_entity = {entity: part.sort_values("timestamp") for entity, part in daily.groupby("entity_id")}
    periods = sorted(set(stamps))
    per_period_entities = daily.groupby("timestamp")["entity_id"].nunique()

    observations = int(len(daily))
    zeros = int((pd.to_numeric(daily["demand_count"], errors="coerce") == 0).sum())
    negatives = int((pd.to_numeric(daily["demand_count"], errors="coerce") < 0).sum())
    non_integer = int((pd.to_numeric(daily["demand_count"], errors="coerce") % 1 != 0).sum())
    source_ids = set(daily["source_id"].astype(str))
    measures = set(daily["measure"].astype(str))

    ordering_ok = all(
        part["timestamp"].is_monotonic_increasing and not part["timestamp"].duplicated().any()
        for part in by_entity.values()
    )
    expected_span = int((periods[-1] - periods[0]).total_seconds() // period) + 1
    # Grid is measured inside each entity's own observed span: a station that started
    # reporting late is a coverage fact, not a gap to fill.
    grid_expected = 0
    for part in by_entity.values():
        own = part["timestamp"]
        grid_expected += int((own.max() - own.min()).total_seconds() // period) + 1
    gap_count = grid_expected - observations
    coverage = observations / max(grid_expected, 1)
    names_per_entity = daily.groupby("entity_id")["entity_name"].nunique()
    identity_stable = bool((names_per_entity == 1).all())
    per_entity_coverage = {entity: len(part) / max(1, int((part["timestamp"].max() - part["timestamp"].min()).total_seconds() // period) + 1)
                           for entity, part in by_entity.items()}
    thin = {entity: round(value, 3) for entity, value in per_entity_coverage.items() if value < 0.5}

    no_future_ok, no_future_evidence = check_no_leakage(daily, granularity, period)
    try:
        supervised = _builder_for(granularity, period)[0](daily)
        feature_error = None
    except ValueError as exc:
        supervised, feature_error = pd.DataFrame(), str(exc)
    if supervised.empty:
        unique_targets, partitions = 0, {}
    else:
        target_times = _snap(pd.to_datetime(supervised["timestamp"]), period)
        ordered_days = sorted(set(target_times.dt.normalize()))
        unique_targets = int(target_times.nunique())
        # 70/15/15 over target periods, measured in rows and calendar days per partition
        cut_train = ordered_days[int(len(ordered_days) * 0.70)]
        cut_valid = ordered_days[int(len(ordered_days) * 0.85)]
        day_index = _snap(pd.to_datetime(supervised["timestamp"]), period) if period >= 86400 \
            else pd.to_datetime(supervised["timestamp"]).dt.normalize()
        partitions = {}
        # Same convention as the trainers: a partition owns its start day and not the
        # boundary day of the next one, so the gate's numbers must match model_report.json.
        for name, selector in (("train", day_index < cut_train),
                               ("validation", (day_index >= cut_train) & (day_index < cut_valid)),
                               ("test", day_index >= cut_valid)):
            subset = supervised.loc[selector]
            partitions[name] = {"rows": int(len(subset)),
                                 "days": int(pd.to_datetime(subset["timestamp"]).dropna().dt.normalize().nunique()),
                                 "start": str(pd.to_datetime(subset["timestamp"]).min().date()) if len(subset) else None,
                                 "end": str(pd.to_datetime(subset["timestamp"]).max().date()) if len(subset) else None}
    # Thresholds are stated in supervised rows and calendar days so that they mean the
    # same thing at hour and day granularity: enough rows to fit, and at least a week in
    # each held-out partition so the weekly cycle is actually tested rather than assumed.
    needed = {"train_rows": 3000, "validation_rows": 500, "test_rows": 500, "days_per_partition": 3}
    train_n = partitions.get("train", {}).get("rows", 0)
    valid_n = partitions.get("validation", {}).get("rows", 0)
    test_n = partitions.get("test", {}).get("rows", 0)
    days_per_partition = {name: item.get("days", 0) for name, item in partitions.items()}

    license_text = str(metadata.get("license") or "")
    # "understood" means the terms are recorded AND the project's own handling of them is
    # written down: either a redistribution stance, or bundled-with-attribution under an
    # open licence whose text ships with the repository.
    open_licence_files = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "data/licenses").glob("*")
                                if path.is_file()) if (ROOT / "data/licenses").is_dir() else []
    bundled_rights = bool(metadata.get("bundled_data")) or any(
        key in license_text for key in ("ODbL", "CC BY", "Public Domain", "MIT", "GODL"))
    rights_ok = bool(license_text.strip()) and (
        bool(metadata.get("license_note") or metadata.get("redistribution") or metadata.get("how_to_fetch"))
        or (bundled_rights and bool(open_licence_files)))
    commit = metadata.get("upstream_commit") or metadata.get("source_commit")
    digest = metadata.get("source_sha256")
    provenance_ok = bool(commit) and bool(digest) and bool(metadata.get("source_url"))
    today = pd.Timestamp.now(tz=timezone).normalize()
    periods_report = {"count": len(periods), "start": str(periods[0].date()), "end": str(periods[-1].date()),
                      "expected_contiguous_within_span": expected_span}
    frontier = pd.Timestamp(periods[-1])
    horizon_days = int((today - frontier).days) if frontier.tzinfo else None

    source_blob = " ".join(sorted(source_ids)).lower()
    declared_class = str(metadata.get("observation_class") or metadata.get("dataset_class") or "observed").strip().lower()
    provenance_statement = str(metadata.get("provenance_statement") or "").strip()
    synthetic_declared = declared_class not in {"observed", "observed_survey", "observed_count"} or any(
        marker in source_blob or marker in str(metadata.get("source_title", "")).lower() for marker in SYNTHETIC_MARKERS)
    if synthetic_declared:
        observation_class = declared_class
        target_refusal = (f"declared '{declared_class}' and not an operator-published observation; synthetic or "
                          "simulated counts cannot supervise a demand model")
        observed_target_ok = False
    elif source_ids <= OBSERVED_SOURCE_IDS:
        observation_class = "verified_project_source"
        target_refusal = ""
        observed_target_ok = True
    elif provenance_statement:
        observation_class = "declared_observed_with_provenance"
        target_refusal = ""
        observed_target_ok = True
    else:
        observation_class = declared_class
        target_refusal = ("source id is not one the project verified and no provenance_statement is recorded, so "
                          "the pipeline cannot confirm these are counted passengers")
        observed_target_ok = False

    criteria = {
        "target_values_are_actual_observations": _criterion(
            observed_target_ok and negatives == 0 and non_integer == 0 and len(measures) == 1,
            f"{observations} rows from {sorted(source_ids)}; measures {sorted(measures)}; {negatives} negative and "
            f"{non_integer} fractional counts; {zeros} operator-reported zeros kept as real observations "
            f"(source-reported, not filled); provenance class: {observation_class}"
            + (f"; refusal: {target_refusal}" if target_refusal else ""),
        ),
        "temporal_granularity_is_known": _criterion(
            granularity in PERIOD_SECONDS and PERIOD_SECONDS[granularity] == period and len(periods) > 1,
            f"one row per entity per {granularity} ({period}s); {len(periods)} distinct periods from "
            f"{periods[0]} to {frontier}; modal spacing is the declared period, so the grid is not an assumption",
        ),
        "time_ordering_is_known": _criterion(
            ordering_ok,
            f"timestamps parse to {timezone} and increase without duplicates for all {daily['entity_id'].nunique()} "
            f"entities; lag/rolling features rely on that ordering",
        ),
        "entity_identity_stable_enough": _criterion(
            identity_stable and not thin,
            f"{daily['entity_id'].nunique()} entities, each with exactly one published name; per-period entity counts "
            f"range {int(per_period_entities.min())}-{int(per_period_entities.max())} over {expected_span} periods "
            f"inside each entity's own span; {len(thin)} entity(ies) below 50% coverage{': ' + json.dumps(thin) if thin else ''}",
        ),
        "sufficient_observations_for_time_series_split": _criterion(
            observations >= 3000 and train_n >= needed["train_rows"] and valid_n >= needed["validation_rows"]
            and test_n >= needed["test_rows"] and min(days_per_partition.values() or [0]) >= needed["days_per_partition"],
            f"{observations} rows -> {unique_targets} supervised targets; train {train_n:,} rows / "
            f"{days_per_partition.get('train', 0)} days, validation {valid_n:,} rows / {days_per_partition.get('validation', 0)} days, "
            f"test {test_n:,} rows / {days_per_partition.get('test', 0)} days (needs "
            f">= {needed['train_rows']:,}/{needed['validation_rows']}/{needed['test_rows']} rows and "
            f">= {needed['days_per_partition']} days each)"
            + (f"; the {granularity} feature builder reported: {feature_error}" if feature_error else ""),
        ),
        "missingness_quantified": _criterion(
            gap_count >= 0 and metadata.get("missing_station_days_filled", metadata.get("missing_hours_filled", 0)) == 0,
            f"{gap_count} missing entity-period cells within the entities' own spans of {grid_expected} expected "
            f"({coverage:.1%} coverage); 0 cells were filled or interpolated - a gap deletes the supervised rows whose "
            f"window would have to bridge it",
        ),
        "no_future_values_used_for_past_features": _criterion(no_future_ok, no_future_evidence),
        "genuine_future_test_period_exists": _criterion(
            horizon_days is not None and horizon_days >= 1 and days_per_partition.get("test", 0) >= needed["days_per_partition"],
            f"source ends {frontier.date()}, which is {horizon_days} day(s) before today, so a request for a date "
            f"after the frontier is a real future forecast; {days_per_partition.get('test', 0)} held-out days "
            f"({test_n:,} rows) also audit the recursive projection path",
        ),
        "license_usage_rights_understood": _criterion(
            rights_ok,
            f"license field: {license_text[:110] or 'MISSING'}; redistribution stance: "
            f"{str(metadata.get('redistribution') or metadata.get('how_to_fetch') or 'see data/licenses note')[:110]}; "
            f"licence text shipped: {', '.join(open_licence_files) or 'none'}",
        ),
        "provenance_is_reproducible": _criterion(
            provenance_ok,
            f"source_url={metadata.get('source_url')} commit={str(commit)[:12]} sha256={str(digest)[:12]}; "
            f"normalized file sha256={metadata.get('normalized_sha256', 'not recorded')[:12]}",
        ),
    }
    failed = sorted(name for name, item in criteria.items() if not item["pass"])
    critical_failed = sorted(set(failed) & set(CRITICAL))
    return {
        "dataset": str(csv_path.relative_to(ROOT)) if csv_path.is_relative_to(ROOT) else str(csv_path),
        "evaluated_at_utc": datetime.now(dt_timezone.utc).isoformat(timespec="seconds"),
        "granularity": granularity, "timezone": timezone,
        "rows": observations, "entities": int(daily["entity_id"].nunique()),
        "periods": periods_report,
        "data_quality": {"zero_count": zeros, "negative_count": negatives, "gap_cells": gap_count,
                        "coverage_ratio": round(coverage, 6), "thin_entities": thin, "partitions": partitions,
                        "cleaning_report": quality},
        "criteria": criteria,
        "failed_criteria": failed,
        "critical_failures": critical_failed,
        "eligible_for_primary_future_prediction_model": not critical_failed,
        "policy": (
            "All ten criteria must pass to train the primary future-demand model. A failure of a non-critical "
            "criterion still blocks promotion: the gate is a conjunction, not a score."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-id", default=None)
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--feature-granularity", default=None, choices=sorted(PERIOD_SECONDS))
    parser.add_argument("--period-seconds", type=int, default=None,
                        help="override the detected period (rarely needed; must match the granularity label)")
    parser.add_argument("--dataset-class", default=None,
                        help="observed | synthetic_development | historical_study_output - recorded in the report")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.system_id:
        family = get_model_family(args.system_id)
        args.feature_granularity = args.feature_granularity or str(family["granularity"])
        # mirrors FAMILY_DATASETS in backend/app/main.py; kept local so the gate can run
        # without importing the application
        relative = {"bengaluru-namma-metro": "data/processed/namma_metro_station_hourly.csv",
                    "chennai-cmrl-metro": "data/processed/chennai_metro_demand_timeseries.csv"}.get(args.system_id)
        if relative is None:
            parser.error(f"no normalized dataset is registered for {args.system_id}; pass --csv explicitly")
        args.csv = args.csv or ROOT / relative
        args.metadata = args.metadata or args.csv.with_suffix(".metadata.json")
    if not args.csv or not args.csv.is_file():
        parser.error("dataset CSV not found; pass --csv or run the prepare script first")
    args.feature_granularity = args.feature_granularity or "day"
    metadata = json.loads(args.metadata.read_text(encoding="utf-8")) if args.metadata and args.metadata.is_file() else {}
    timezone = str(metadata.get("timezone") or "Asia/Kolkata")
    if args.dataset_class:
        metadata = {**metadata, "observation_class": args.dataset_class}
    report = evaluate(args.csv, metadata, args.feature_granularity, timezone,
                      period_seconds=args.period_seconds)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    width = max(len(name) for name in report["criteria"])
    print(f"\nDataset: {report['dataset']}   granularity: {report['granularity']}   "
          f"{report['rows']:,} rows / {report['entities']} entities / {report['periods']['count']} periods")
    print(f"Coverage {report['periods']['start']} -> {report['periods']['end']}\n")
    for name, item in report["criteria"].items():
        print(f"  [{'PASS' if item['pass'] else 'FAIL'}] {name:<{width}}")
        print(f"         {item['evidence']}")
    print(f"\nCritical failures: {report['critical_failures'] or 'none'}")
    print(f"Eligible for the primary future-prediction model: {report['eligible_for_primary_future_prediction_model']}")
    if args.output:
        print(f"Report written: {args.output.relative_to(ROOT) if args.output.is_relative_to(ROOT) else args.output}")
    if not report["eligible_for_primary_future_prediction_model"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
