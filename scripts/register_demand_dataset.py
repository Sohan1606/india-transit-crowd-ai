#!/usr/bin/env python3
"""Adaptive ingestion: profile an arbitrary demand table, validate it, normalize it, gate it.

This is the pipeline's front door for a dataset that is not one of the two code-defined
families. It exists so that "works with any compatible dataset" means something checkable:
the column roles are decided from the data (types, cardinality, value pattern, temporal
structure, repetition), the observation period is measured rather than assumed, and the
ten-criterion forecasting gate has to pass before anything is registered or trained.

    # inspect what a file contains and what the pipeline would decide
    python3 scripts/register_demand_dataset.py --csv incoming.csv --system-id pune-metro \\
        --city Pune --mode METRO --operator Maha-Metro --source-id maha-metro-afc \\
        --source-url https://example.org/afc --licence "CC BY 4.0" --dataset-class observed --dry-run

    # write the canonical dataset + sidecar + gate report, then register and train
    python3 scripts/register_demand_dataset.py ... --write --install-registry --train

Deliberate refusals (each is a non-zero exit with a reason, never a silent fallback):
* no explicit decision when two columns could both be the demand target;
* a declared granularity that disagrees with the measured timestamp spacing;
* anything declared synthetic, simulated or modelled: it can be profiled and used for
  development testing, but it can never become a production family or a training label;
* a period the trainers do not implement (profiling and gating still complete, so the
  dataset is documented rather than discarded).
"""
from __future__ import annotations

import argparse
import hashlib
import tempfile
import json
import re
import subprocess
import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.data_pipeline.cleaning import DataValidationError, clean_normalized_demand  # noqa: E402
from ml.data_pipeline.profile import measure_relations, profile_dataset  # noqa: E402
from ml.features.periodic import PERIOD_SECONDS  # noqa: E402
from ml.training.registry import REGISTRY_PATH, get_model_family, register_family  # noqa: E402
from scripts.validate_demand_dataset import evaluate  # noqa: E402

PRODUCTION_CLASSES = {"observed", "observed_survey", "observed_count"}
DEVELOPMENT_CLASSES = {"synthetic_development", "simulated", "modelled_output", "historical_study_output"}
TRAINABLE = ("day", "hour")


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def decide(profile: dict[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], list[str]]:
    """Merge the profiler's semantic decision with explicit overrides; collect refusals."""
    refusals: list[str] = []
    mapping = dict(profile["mapping"])
    for role, flag in (("timestamp", "timestamp_column"), ("entity", "entity_column"),
                       ("demand", "demand_column"), ("entity_name", "entity_name_column")):
        override = getattr(args, flag, None)
        if override:
            if override not in profile["columns"]:
                refusals.append(f"--{flag.replace('_', '-')} '{override}' is not a column of the file "
                                f"(available: {', '.join(sorted(profile['columns']))})")
            mapping[role] = override
    # An override may point at a column the profiler disqualified (usually because its header
    # says forecast/modelled/synthetic). That is allowed for development datasets, where the
    # whole file is declared non-observed, and refused for production ones.
    chosen = mapping.get("demand")
    disqualified = ((profile["scores"].get("demand") or {}).get(chosen) or {}).get("disqualifiers") or []
    if disqualified:
        warning = f"column '{chosen}' was disqualified by the profiler: {'; '.join(disqualified)}"
        if args.dataset_class in PRODUCTION_CLASSES:
            refusals.append(warning + ". For an observed production family the target must be a counted "
                           "passenger column; only development datasets may override this.")
        else:
            print(f"[warn] {warning} (accepted because the dataset is declared {args.dataset_class})")

    for role in ("timestamp", "entity", "demand"):
        if not mapping.get(role):
            refusals.append(
                f"no column could be identified as the {role} from its data characteristics; pass "
                f"--{'timestamp' if role == 'timestamp' else role}-column explicitly if the file genuinely has one"
            )
    near_ties = list(profile["ambiguous_demand_columns"])
    if mapping.get("demand") and near_ties and not args.demand_column:
        listing = ", ".join(f"{name} (score {(profile['scores']['demand'].get(name) or {}).get('score')})"
                            for name in [mapping["demand"], *near_ties][:8])
        refusals.append(
            f"two or more columns are equally plausible as the observed passenger count: {listing}. The pipeline "
            "will not guess which measure to train on - pass --demand-column, and only combine measures that are "
            "documented as the same quantity"
        )
    if args.granularity != "auto":
        detected = (profile["granularity"] or {}).get("detected")
        if detected and detected != args.granularity:
            refusals.append(
                f"--granularity {args.granularity} contradicts the measured timestamp spacing "
                f"({detected}); a forecast cannot claim a finer resolution than the source publishes"
            )
    granularity = args.granularity if args.granularity != "auto" else (profile["granularity"] or {}).get("detected")
    if granularity not in PERIOD_SECONDS:
        detail = (profile["granularity"] or {}).get("error") or "the timestamps do not form a regular grid"
        refusals.append(f"observation period could not be established: {detail}")
    return {"mapping": mapping, "granularity": granularity,
            "period_seconds": PERIOD_SECONDS.get(str(granularity), 86400)}, refusals


def normalize(frame: pd.DataFrame, decisions: dict[str, Any], args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    mapping = decisions["mapping"]
    period = int(decisions["period_seconds"])
    stamps = pd.to_datetime(frame[mapping["timestamp"]], errors="coerce")
    stamps = stamps.dt.tz_localize(args.timezone) if stamps.dt.tz is None else stamps.dt.tz_convert(args.timezone)
    stamps = stamps.dt.normalize() if period >= 86400 else stamps.dt.floor(pd.Timedelta(seconds=period))
    if args.entity_key_columns:
        parts = [name.strip() for name in args.entity_key_columns.split(",") if name.strip()]
        unknown = [name for name in parts if name not in frame.columns]
        if unknown:
            raise DataValidationError(f"--entity-key-columns names missing columns: {unknown}")
        entity = parts[0] and frame[parts[0]].astype(str).str.strip()
        for extra in parts[1:]:
            entity = entity + " / " + frame[extra].astype(str).str.strip()
        entity = entity.astype(str)
    else:
        entity = frame[mapping["entity"]].astype(str).str.strip()
    entity_name = (frame[mapping["entity_name"]].astype(str).str.strip()
                   if mapping.get("entity_name") else entity)
    demand = pd.to_numeric(frame[mapping["demand"]], errors="coerce")
    canonical = pd.DataFrame({
        "system_id": args.system_id,
        "city": args.city,
        "mode": args.mode,
        "operator": args.operator,
        "line_id": frame[args.line_column].astype(str) if args.line_column and args.line_column in frame else "",
        "station_id": entity.map(_slug),
        "entity_id": entity.map(_slug),
        "entity_name": entity_name,
        "entity_type": args.entity_type,
        "timestamp": stamps,
        "date": stamps.dt.date.astype(str),
        "time_interval": stamps.dt.strftime("%H:%M" if period < 86400 else "day"),
        "demand_count": demand,
        "measure": args.measure or f"{decisions['granularity']}_station_demand",
        "service_count": pd.to_numeric(frame[args.services_column], errors="coerce") if args.services_column else pd.NA,
        "source_id": args.source_id,
        "observation_type": args.observation_type,
        "provenance": args.source_url,
    })
    # The shared contract enforces one system/city/mode/operator/entity_type, whole
    # non-negative counts, one record per entity-period and period-aligned stamps.
    cleaned, report = clean_normalized_demand(canonical, timezone=args.timezone, period_seconds=period)
    return cleaned, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--system-id", required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--mode", default="METRO")
    parser.add_argument("--operator", required=True)
    parser.add_argument("--entity-type", default="STATION")
    parser.add_argument("--timezone", default="Asia/Kolkata")
    parser.add_argument("--granularity", default="auto", choices=["auto", *sorted(PERIOD_SECONDS)])
    parser.add_argument("--timestamp-column", default=None)
    parser.add_argument("--entity-column", default=None)
    parser.add_argument("--entity-name-column", default=None)
    parser.add_argument("--entity-key-columns", default=None,
                        help="comma-separated columns that together identify an entity, e.g. 'Line,Station' when a "
                             "terminal is reported once per corridor instead of once per station")
    parser.add_argument("--demand-column", default=None)
    parser.add_argument("--measure", default=None, help="canonical measure label, e.g. daily_station_entries")
    parser.add_argument("--line-column", default=None)
    parser.add_argument("--services-column", default=None, help="optional scheduled-services count")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-commit", default=None)
    parser.add_argument("--licence", default=None, dest="license")
    parser.add_argument("--license-note", default=None)
    parser.add_argument("--redistribution", default=None)
    parser.add_argument("--observation-type", default="directly_observed")
    parser.add_argument("--dataset-class", default="observed",
                        choices=sorted(PRODUCTION_CLASSES | DEVELOPMENT_CLASSES))
    parser.add_argument("--provenance-statement", default=None,
                        help="one paragraph naming who counted these passengers, when and how")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="profile, decide and gate without writing anything")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--install-registry", action="store_true")
    parser.add_argument("--allow-development-family", action="store_true",
                        help="register a non-production family marked development_only (never served)")
    parser.add_argument("--train", action="store_true")
    args = parser.parse_args()

    if not args.csv.is_file():
        parser.error(f"CSV not found: {args.csv}")
    frame = pd.read_csv(args.csv)
    profile = profile_dataset(frame, timezone=args.timezone)
    decisions, refusals = decide(profile, args)
    print(f"[profile] {args.csv.name}: {profile['rows']:,} rows x {len(profile['columns'])} columns")
    for role in ("timestamp", "entity", "entity_name", "demand"):
        chosen = decisions["mapping"].get(role)
        print(f"[profile]   {role:<12}= {chosen or 'UNRESOLVED'}")
    print(f"[profile]   granularity  = {decisions['granularity']} "
          f"({profile['granularity'].get('evidence', {}).get('modal_spacing_share', 0):.0%} of gaps at "
          f"{profile['granularity'].get('evidence', {}).get('modal_spacing_seconds')}s)"
          if profile["granularity"].get("evidence") else f"[profile]   granularity  = {decisions['granularity']}")
    if refusals:
        print("\nREFUSED - the dataset cannot enter the pipeline as it stands:")
        for reason in refusals:
            print(f"  - {reason}")
        raise SystemExit(2)

    try:
        cleaned, cleaning_report = normalize(frame, decisions, args)
    except (DataValidationError, ValueError) as exc:
        print(f"\nREFUSED - normalization failed: {exc}")
        raise SystemExit(2) from exc

    relations: dict[str, Any] = {}
    measure_candidates = [column for column in ([decisions["mapping"].get("demand")] + list(profile["ambiguous_demand_columns"]))
                          if column in frame.columns]
    if len(measure_candidates) > 1:
        relations = measure_relations(frame, measure_candidates[:6])
        if relations["sum_matches"]:
            print(f"[measures] additive relation detected: {relations['sum_matches']} - these columns are NOT "
                  "interchangeable and are never summed into one target")

    # A dry run writes nothing into the project: every artifact goes into a temporary directory
    # that is discarded on exit, so "look but don't touch" really means that.
    scratch = tempfile.TemporaryDirectory(prefix="register-dryrun-") if args.dry_run else None
    out_dir = Path(scratch.name) if scratch else (
        args.out_dir or (ROOT / "data/development" if args.dataset_class in DEVELOPMENT_CLASSES else ROOT / "data/processed"))
    stem = f"{_slug(args.system_id)}_demand_timeseries"
    csv_path = out_dir / f"{stem}.csv"
    sidecar_path = csv_path.with_suffix(".metadata.json")
    gate_path = out_dir / f"{args.system_id}_validation_gate.json"
    source_sha = _sha256(args.csv)
    normalized_sha = ""
    if args.write or args.dry_run:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(cleaned.to_csv(index=False), encoding="utf-8")
        normalized_sha = _sha256(csv_path)

    stamps = pd.to_datetime(cleaned["timestamp"])
    metadata = {
        "system_id": args.system_id, "generated_at_utc": datetime.now(dt_timezone.utc).isoformat(timespec="seconds"),
        "source_file": str(args.csv.relative_to(ROOT)) if args.csv.is_relative_to(ROOT) else str(args.csv),
        "source_title": f"{args.operator} observed passenger demand ({args.dataset_class})",
        "source_url": args.source_url, "upstream_commit": args.source_commit, "source_sha256": source_sha,
        "normalized_sha256": normalized_sha, "license": args.license, "license_note": args.license_note,
        "redistribution": args.redistribution or ("Development fixture; not a production dataset."
                                                 if args.dataset_class in DEVELOPMENT_CLASSES else
                                                 "Publisher terms apply; refetched from the recorded source."),
        "provenance_statement": args.provenance_statement, "observation_class": args.dataset_class,
        "granularity": decisions["granularity"], "period_seconds": decisions["period_seconds"],
        "timezone": args.timezone, "measure": cleaned["measure"].iloc[0],
        "column_mapping": {key: value for key, value in decisions["mapping"].items() if isinstance(value, str)},
        "profiler_scores": {role: {name: (value["score"] if isinstance(value, dict) else value)
                                   for name, value in (profile["scores"].get(role) or {}).items()}
                            for role in ("timestamp", "entity")},
        "ambiguous_demand_columns": profile["ambiguous_demand_columns"], "measure_relations": relations,
        "timestamp_min": str(stamps.min()), "timestamp_max": str(stamps.max()),
        "unique_days": int(stamps.dt.normalize().nunique()), "observed_rows": int(len(cleaned)),
        "station_count": int(cleaned["entity_id"].nunique()),
        "station_ids": sorted(cleaned["entity_id"].astype(str).unique().tolist()),
        "station_names": {str(key): str(value) for key, value in
                          cleaned.groupby("entity_id")["entity_name"].first().items()},
        "explicit_zero_observations": int((cleaned["demand_count"] == 0).sum()),
        "missing_station_days_filled": 0, "missing_hours_filled": 0,
        "cleaning_report": cleaning_report, "is_live": False,
        "dataset_class": args.dataset_class,
        "production_eligible": args.dataset_class in PRODUCTION_CLASSES,
        "how_to_fetch": "python3 scripts/register_demand_dataset.py --csv <file> ... (this run)",
    }
    if args.write:
        sidecar_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    report = evaluate(csv_path, metadata, decisions["granularity"], args.timezone,
                      period_seconds=decisions["period_seconds"])
    if args.write or args.dry_run:
        gate_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    passed = sum(1 for item in report["criteria"].values() if item["pass"])
    print(f"[gate] {passed}/{len(report['criteria'])} criteria pass | eligible: "
          f"{report['eligible_for_primary_future_prediction_model']}")
    for name, item in report["criteria"].items():
        if not item["pass"]:
            print(f"[gate]   FAIL {name}: {item['evidence'][:150]}")

    if args.dry_run:
        if scratch is not None:
            scratch.cleanup()
        print("[dry-run] nothing written to the project; the decision and gate above are the output")
        return

    for written in (csv_path, sidecar_path, gate_path):
        print(f"[write] {_rel(written)}")

    if args.dataset_class in DEVELOPMENT_CLASSES and not args.allow_development_family:
        print("\nThis dataset is classified as development/test data, so it was not registered as a served "
              "family. Re-run with --allow-development-family to register it as development_only (the API will "
              "still refuse to serve it), and never present its numbers as observed passengers.")
        raise SystemExit(0)
    # The gate is a conjunction: the report also names the critical subset for triage, but a
    # family is promoted only when every criterion passes.
    if passed != len(report["criteria"]):
        print(f"\nNot registered: {passed}/{len(report['criteria'])} criteria pass and the gate is a conjunction, "
              "not a score. Fix the data (or document why a criterion cannot be met) and re-run.")
        raise SystemExit(1)

    family = {
        "system_id": args.system_id, "city": args.city, "mode": args.mode, "operator": args.operator,
        "timezone": args.timezone, "entity_type": args.entity_type, "measure": metadata["measure"],
        "artifact_subdirectory": args.system_id, "source_id": args.source_id,
        "granularity": decisions["granularity"], "target": f"target_next_{_slug(str(decisions['granularity']))}_demand",
        "feature_period_seconds": decisions["period_seconds"],
        "label_unit": "entries" if "entries" in metadata["measure"] else "passengers",
        "dataset_relative_path": str(csv_path.relative_to(ROOT)),
        "metadata_relative_path": str(sidecar_path.relative_to(ROOT)),
        "max_recursive_horizon_days": 60 if decisions["granularity"] == "day" else 336,
        "development_only": args.dataset_class in DEVELOPMENT_CLASSES,
        "registered_at_utc": datetime.now(dt_timezone.utc).isoformat(timespec="seconds"),
    }
    if args.install_registry:
        path = register_family(family, REGISTRY_PATH)
        print(f"[registry] family '{args.system_id}' written to {path.relative_to(ROOT)}"
              + (" (development_only: not served)" if family["development_only"] else ""))
    if args.train:
        if decisions["granularity"] not in TRAINABLE:
            print(f"[train] skipped: no leakage-safe trainer is implemented for '{decisions['granularity']}' "
                  "data. The gate and features were computed with the generic periodic builder, so the dataset is "
                  "documented; training it would require wiring a period-specific inference service, which has not "
                  "been validated. Refusing to substitute the day or hour trainer instead.")
            return
        try:
            get_model_family(args.system_id)
        except ValueError:
            print("[train] skipped: register the family first (--install-registry) so the trainer can bind the "
                  "model to a verified system/mode/operator family.")
            return
        if decisions["granularity"] == "day":
            from ml.training.train_daily import save_artifacts, train_daily
            result = train_daily(cleaned, dataset_metadata=metadata, tz=args.timezone)
            directory = ROOT / "backend/models" / args.system_id
            save_artifacts(result, directory)
            print(f"[train] day-granularity family trained and saved to {_rel(directory)}")
        else:
            command = [sys.executable, str(ROOT / "scripts/train_models.py"), "--data", str(csv_path),
                       "--metadata", str(sidecar_path), "--output-dir", str(ROOT / "backend/models" / args.system_id)]
            print("[train] " + " ".join(str(part) for part in command))
            subprocess.run([str(part) for part in command], check=True)


if __name__ == "__main__":
    main()
