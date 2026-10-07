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
import gzip
import hashlib
import shutil
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
from ml.training.registry import OBSERVED_TARGET_CRITERION, REGISTRY_PATH, get_model_family, register_family  # noqa: E402
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


def profile_timestamp_guess(frame: pd.DataFrame) -> str:
    """Cheap fallback used only by --exclude-unobserved-future before profiling has run."""
    from ml.data_pipeline.profile import profile_dataset
    return profile_dataset(frame)["mapping"]["timestamp"]


def _train_only(args: argparse.Namespace) -> None:
    """Run the trainer for a family that is already registered, from the file its entry points at.

    Registration and training are separate effects: a re-train must not re-profile the source, rewrite the
    normalized data or touch provenance, because those are the audited record of how the family was built.
    """
    from ml.training.registry import get_model_family
    family = get_model_family(args.system_id)
    csv_path = ROOT / str(family["dataset_relative_path"])
    sidecar_path = ROOT / str(family["metadata_relative_path"])
    if not csv_path.is_file():
        raise SystemExit(f"the registered normalized file is missing: {csv_path.relative_to(ROOT) if csv_path.is_relative_to(ROOT) else csv_path} - "
                         "re-run registration (for a private source, restore it with scripts/fetch_lfs_object.py --all first)")
    metadata = json.loads(sidecar_path.read_text(encoding="utf-8")) if sidecar_path.is_file() else {}
    granularity = str(family.get("granularity") or metadata.get("granularity") or "day")
    cleaned = pd.read_csv(csv_path, encoding="utf-8-sig")
    if "timestamp" not in cleaned.columns and "observation_timestamp" in cleaned.columns:
        cleaned = cleaned.rename(columns={"observation_timestamp": "timestamp"})
    print(f"[train-only] {args.system_id}: {len(cleaned):,} normalized rows at {granularity} granularity")
    if granularity == "day":
        from ml.training.train_daily import save_artifacts, train_daily
        result = train_daily(cleaned, dataset_metadata=metadata, tz=str(family.get("timezone") or "Asia/Kolkata"),
                             fit_window_days=args.fit_window_days or None)
        directory = ROOT / "backend/models" / args.system_id
        save_artifacts(result, directory)
        print(f"[train-only] day-granularity artifacts saved to backend/models/{args.system_id}")
    else:
        subprocess.run([sys.executable, str(ROOT / "scripts/train_models.py"), "--data", str(csv_path),
                        "--metadata", str(sidecar_path), "--output-dir",
                        str(ROOT / "backend/models" / args.system_id),
                        "--fit-window-days", str(args.fit_window_days or 0)], check=True)
        print(f"[train-only] {granularity}-granularity artifacts saved to backend/models/{args.system_id}")


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
    parser.add_argument("--timestamp-columns", default=None,
                        help="comma-separated columns to join into one timestamp when a file splits it, e.g. "
                             "'Date,Time' - the joined value is what the grid and period are measured from")
    parser.add_argument("--entity-column", default=None)
    parser.add_argument("--entity-name-column", default=None)
    parser.add_argument("--entity-key-columns", default=None,
                        help="comma-separated columns that together identify an entity, e.g. 'Line,Station' when a "
                             "terminal is reported once per corridor instead of once per station")
    parser.add_argument("--demand-column", default=None)
    parser.add_argument("--measure", default=None, help="canonical measure label, e.g. daily_station_entries")
    parser.add_argument("--line-column", default=None)
    parser.add_argument("--entity-attribute-columns", default=None,
                        help="comma-separated context columns recorded per entity in the sidecar (e.g. the line, the "
                             "origin, the destination and the time slot that together identify a series); the API "
                             "publishes them so a client can build dependent selectors from the data instead of a list")
    parser.add_argument("--entity-hierarchy-columns", default=None,
                        help="ordered subset of --entity-attribute-columns that forms a cascade (parent first). The "
                             "frontend renders one select per level and resolves it to a single entity id, which is "
                             "how a slot-based or direction-segmented family exposes its supported choices without any "
                             "per-city code")
    parser.add_argument("--entity-hierarchy-labels", default=None,
                        help="display labels for --entity-hierarchy-columns, comma-separated and in the same order "
                             "(e.g. 'Line,From,Towards,Time slot'). The client renders these, so a file whose column "
                             "is named Destination_Station can still be presented as the journey's TOWARDS")
    parser.add_argument("--route-group-column", default=None,
                        help="column naming a route/corridor, used with --route-station-column and "
                             "--route-position-column to derive the ordered station list and the two endpoints "
                             "from the data itself (no route table is written into this repository)")
    parser.add_argument("--route-station-column", default=None, help="station column for the route context")
    parser.add_argument("--route-position-column", default=None,
                        help="numeric position of the station along its route; ordering and endpoints come from it")
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
    parser.add_argument("--serve-as", default="auto", choices=("auto", "production", "demo", "internal"),
                        help="how the family may be used: 'production' = verified observed data, every gate "
                             "criterion; 'demo' = a non-observed dataset (synthetic/simulated/modelled) that IS "
                             "served, with a synthetic disclosure on every response and every metric labelled a "
                             "demonstration result; 'internal' = loaded by tooling, never served. 'auto' picks "
                             "production for an observed class and internal otherwise.")
    parser.add_argument("--print-audit", action="store_true",
                        help="run the full read-only audit (inventory, grid, slots, duplicates, precomputed-target "
                             "verification) on the raw file and stop - nothing is decided or written")
    parser.add_argument("--exclude-unobserved-future", action="store_true",
                        help="drop rows whose timestamp is later than today before anything else happens. A file "
                             "that publishes the rest of the current year (a projection, or a synthetic table built "
                             "for a whole calendar year) must not be trained on days that have not happened: it "
                             "would make every 'future' claim false and the held-out test period meaningless")
    parser.add_argument("--dry-run", action="store_true", help="profile, decide and gate without writing anything")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--install-registry", action="store_true")
    parser.add_argument("--allow-development-family", action="store_true",
                        help="register a non-production family marked development_only (never served)")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--fit-window-days", type=int, default=0,
                        help="with --train/--train-only: fit on the most recent N days only (the stored data and "
                             "the served observation history stay complete); recorded inside the model report")
    parser.add_argument("--no-inference-copy", action="store_true",
                        help="skip publishing the compressed, committed inference copy under data/inference/")
    parser.add_argument("--train-only", action="store_true",
                        help="train and persist artifacts for an already-registered family from the normalized file "
                             "its registry entry points at, without re-profiling or re-writing anything else")
    args = parser.parse_args()

    if args.train_only:
        _train_only(args)
        return

    if not args.csv.is_file():
        parser.error(f"CSV not found: {args.csv}")
    if args.print_audit:
        from ml.data_pipeline.audit import audit_frame
        import subprocess as _sp
        _sp.run([sys.executable, str(ROOT / "scripts/audit_demand_dataset.py"), "--csv", str(args.csv),
                 "--timezone", args.timezone], check=False)
        return
    frame = pd.read_csv(args.csv, encoding="utf-8-sig")
    if args.timestamp_columns:
        # Supplied files commonly split the moment across columns (`Date` + `Time`). Composing them is
        # a reading step, not a Mumbai exception: any file with the same shape uses the same flag.
        parts = [name.strip() for name in str(args.timestamp_columns).split(",") if name.strip()]
        missing = [name for name in parts if name not in frame.columns]
        if missing:
            raise SystemExit(f"--timestamp-columns names columns absent from the file: {missing}. "
                             f"First columns available: {list(frame.columns)[:24]}")
        if args.timestamp_column:
            raise SystemExit("use either --timestamp-column or --timestamp-columns, not both")
        joined = frame[parts[0]].astype(str)
        for extra in parts[1:]:
            joined = joined + " " + frame[extra].astype(str)
        frame["_composed_timestamp"] = joined
        args.timestamp_column = "_composed_timestamp"
    excluded_future_rows = 0
    if args.exclude_unobserved_future:
        moment = pd.to_datetime(frame[args.timestamp_column or profile_timestamp_guess(frame)],
                                errors="coerce").dt.tz_localize(args.timezone)
        today = pd.Timestamp.now(tz=args.timezone).normalize()
        keep = moment.lt(today)
        excluded_future_rows = int((~keep & moment.notna()).sum())
        if excluded_future_rows:
            frame = frame.loc[keep | moment.isna()].copy()
            print(f"[future] excluded {excluded_future_rows:,} row(s) dated on or after {today.date()} - the "
                  "series is usable only through "
                  f"{moment[moment.lt(today)].max().date() if (~keep & moment.notna()).any() else 'the source end'}")
    profile = profile_dataset(frame, timezone=args.timezone, dataset_class=args.dataset_class,
                              timestamp_column=args.timestamp_column)
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

    attribute_columns = [name.strip() for name in str(args.entity_attribute_columns or "").split(",") if name.strip()]
    hierarchy_columns = [name.strip() for name in str(args.entity_hierarchy_columns or "").split(",") if name.strip()]
    unknown = [name for name in attribute_columns + hierarchy_columns if name not in frame.columns]
    if unknown:
        raise SystemExit(f"--entity-attribute-columns/--entity-hierarchy-columns name missing columns: {unknown}")
    if hierarchy_columns and set(hierarchy_columns) - set(attribute_columns):
        raise SystemExit("--entity-hierarchy-columns must be a subset of --entity-attribute-columns")
    entity_attributes: dict[str, dict[str, str]] = {}
    if attribute_columns:
        # Rebuild the composite id exactly as normalize() composes it, so the attributes attach to the
        # same keys the service will be asked about. Vectorised: these files reach hundreds of thousands
        # of rows and a row-wise apply would cost more than the analysis it describes.
        key_columns = [name.strip() for name in str(args.entity_key_columns or "").split(",") if name.strip()]
        base = key_columns or [decisions["mapping"]["entity"]]
        composed = frame[base[0]].astype(str).str.strip()
        for extra in base[1:]:
            composed = composed + " / " + frame[extra].astype(str).str.strip()
        keyed = pd.DataFrame({"_entity_id": composed.astype(str)})
        for name in attribute_columns:
            keyed[name] = frame[name].astype(str).str.strip()
        for row in keyed.drop_duplicates("_entity_id").to_dict("records"):
            # The canonical id in the normalized file is the slug of that composition, so the attributes
            # are keyed the same way - otherwise a client asking about an entity finds nothing on it.
            entity_attributes[_slug(row["_entity_id"])] = {name: row[name] for name in attribute_columns}
        print(f"[attributes] recorded {len(entity_attributes):,} entity attribute sets over columns "
              f"{', '.join(attribute_columns)}")

    hierarchy_labels = [name.strip() for name in str(args.entity_hierarchy_labels or "").split(",") if name.strip()]
    if hierarchy_labels and len(hierarchy_labels) != len(hierarchy_columns):
        raise SystemExit("--entity-hierarchy-labels must give exactly one label per --entity-hierarchy-columns entry")

    # Route context, derived from the file's own ordering columns. A corridor's station order and its two
    # endpoints are facts in this data (Station_Position), so the choices a rider can be offered are computed
    # here instead of being retyped into a client. Where the file has no destination-specific counts, this is
    # journey context only - the forecast remains the one the series actually measures, and nothing invents a
    # directional number.
    route_context: dict[str, Any] = {}
    if args.route_group_column and args.route_station_column and args.route_position_column:
        missing = [name for name in (args.route_group_column, args.route_station_column, args.route_position_column)
                   if name not in frame.columns]
        if missing:
            raise SystemExit(f"--route-*-column names missing columns: {missing}")
        ordered = pd.DataFrame({"_group": frame[args.route_group_column].astype(str).str.strip(),
                                "_station": frame[args.route_station_column].astype(str).str.strip(),
                                "_position": pd.to_numeric(frame[args.route_position_column], errors="coerce")})
        routes: dict[str, list[str]] = {}
        for group, group_rows in ordered.dropna().drop_duplicates(["_group", "_station"]).groupby("_group"):
            stations = group_rows.sort_values("_position")["_station"].tolist()
            if len(stations) > 1:
                routes[str(group)] = [str(name) for name in stations]
        towards_for: dict[str, list[str]] = {}
        if key_columns:
            positions = {(str(group), str(station)): order for group, order in routes.items() for station in order}
            composed_rows = pd.DataFrame({"_entity": composed, "_group": frame[args.route_group_column].astype(str).str.strip(),
                                          "_station": frame[args.route_station_column].astype(str).str.strip()})
            for row in composed_rows.drop_duplicates("_entity").to_dict("records"):
                order = routes.get(row["_group"]) or []
                if not order:
                    continue
                endpoints = [order[0], order[-1]]
                towards = [f"Towards {name}" for name in endpoints if name != row["_station"]]
                if towards:
                    towards_for[_slug(row["_entity"])] = towards
        route_context = {
            "group_column": args.route_group_column, "station_column": args.route_station_column,
            "position_column": args.route_position_column,
            "routes": {group: {"ordered_stations": order, "endpoints": [order[0], order[-1]]}
                       for group, order in sorted(routes.items())},
            "towards_for_entity": towards_for,
            "towards_kind": ("route context derived from station ordering; this dataset publishes no "
                             "destination-specific passenger counts, so no directional demand figure is claimed"),
        }
        print(f"[routes] derived {len(routes)} route(s) and {len(towards_for)} towards-choice set(s) from "
              f"{args.route_position_column} ordering within {args.route_group_column}")

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
        "rows_excluded_as_unobserved_future": int(excluded_future_rows),
        # What each series actually is, straight from the file's own columns, so a client can build
        # dependent selectors (line -> origin -> destination -> time slot) from the data instead of a
        # hand-written city list. Empty for families whose entity id is a single station.
        "entity_attributes": entity_attributes,
        "entity_hierarchy": [{"column": name,
                              "label": hierarchy_labels[index] if hierarchy_labels
                              else name.replace("_", " ").title()}
                             for index, name in enumerate(hierarchy_columns)],
        "route_context": route_context,
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

    serve_as = args.serve_as
    if serve_as == "auto":
        serve_as = "production" if args.dataset_class in PRODUCTION_CLASSES else "internal"
    if args.dataset_class in DEVELOPMENT_CLASSES and not args.allow_development_family and serve_as != "demo":
        print("\nThis dataset is classified as development/test data, so it was not registered as a served "
              "family. Re-run with --allow-development-family to register it as development_only (the API will "
              "still refuse to serve it), and never present its numbers as observed passengers.")
        raise SystemExit(0)
    # The gate is a conjunction: the report also names the critical subset for triage, but a
    # family is promoted only when every criterion passes - with one declared exception below.
    failed_criteria = [name for name, result in report["criteria"].items() if not result.get("pass")]
    if serve_as == "demo":
        blocking = [name for name in failed_criteria if name != OBSERVED_TARGET_CRITERION]
        if blocking:
            print(f"\nNot registered as a demonstration: {passed}/{len(report['criteria'])} criteria pass and "
                  f"{len(blocking)} failure(s) are not the one a non-observed dataset can be excused for: "
                  f"{', '.join(blocking)}. Fix the data and re-run.")
            raise SystemExit(1)
        if not failed_criteria:
            print("\nNot registered as a demonstration: this dataset passed "
                  f"'{OBSERVED_TARGET_CRITERION}', so its values are treated as observed ground truth. Register it "
                  "with --serve-as production instead of hiding it behind a demo label.")
            raise SystemExit(1)
        print(f"\nGate: {passed}/{len(report['criteria'])} criteria pass; '{OBSERVED_TARGET_CRITERION}' is the only "
              "failure, which is expected and honest for a synthetic/demonstration dataset. Every other criterion "
              "(grid, coverage, chronology, leakage probe, horizon, entity integrity) is met.")
    elif failed_criteria:
        print(f"\nNot registered: {passed}/{len(report['criteria'])} criteria pass and the gate is a conjunction, "
              "not a score. Fix the data (or document why a criterion cannot be met) and re-run.")
        raise SystemExit(1)

    # A registry entry must resolve in a fresh clone, not only in the workspace that produced it. The
    # development copy under data/development/ stays git-ignored (it is derived from a source this project
    # may not redistribute), and a compressed inference copy of the same rows is published under
    # data/inference/ for the registry to point at: same content, portable path, no 140 MB raw parse at
    # every service start.
    inference_paths: dict[str, str] = {}
    if args.write and not args.no_inference_copy:
        inference_dir = ROOT / "data/inference"
        inference_dir.mkdir(parents=True, exist_ok=True)
        gz_path = inference_dir / f"{_slug(args.system_id)}_demand_timeseries.csv.gz"
        with open(csv_path, "rb") as source, gzip.open(gz_path, "wb", compresslevel=9) as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
        metadata["normalized_gz_sha256"] = _sha256(gz_path)
        metadata["inference_copy"] = {"dataset_relative_path": _rel(gz_path), "rows": int(len(cleaned)),
                                      "note": "gzip of the identical normalized file; the service verifies this "
                                              "container's own checksum, so a packaged family cannot silently "
                                              "drift from the rows it was trained on"}
        sidecar = json.dumps(metadata, indent=2) + "\n"
        sidecar_path.write_text(sidecar, encoding="utf-8")
        inference_sidecar = inference_dir / f"{_slug(args.system_id)}_demand_timeseries.metadata.json"
        inference_sidecar.write_text(sidecar, encoding="utf-8")
        inference_paths = {"dataset_relative_path": _rel(gz_path), "metadata_relative_path": _rel(inference_sidecar)}
        print(f"[inference] packaged {gz_path.name} ({gz_path.stat().st_size:,} bytes) for portable serving "
              f"({len(cleaned):,} rows)")

    family = {
        "system_id": args.system_id, "city": args.city, "mode": args.mode, "operator": args.operator,
        "timezone": args.timezone, "entity_type": args.entity_type, "measure": metadata["measure"],
        "artifact_subdirectory": args.system_id, "source_id": args.source_id,
        "granularity": decisions["granularity"], "target": f"target_next_{_slug(str(decisions['granularity']))}_demand",
        "feature_period_seconds": decisions["period_seconds"],
        "label_unit": "entries" if "entries" in metadata["measure"] else "passengers",
        "dataset_relative_path": inference_paths.get("dataset_relative_path", str(csv_path.relative_to(ROOT))),
        "metadata_relative_path": inference_paths.get("metadata_relative_path", str(sidecar_path.relative_to(ROOT))),
        "training_dataset_relative_path": str(csv_path.relative_to(ROOT)),
        # Recorded so a checkout without the (deliberately uncommitted) development copy can be repaired by
        # reading the registry alone: the entry says which command rebuilds what it points away from.
        "development_rebuild_command": "python3 scripts/fetch_lfs_object.py --all --under data/development",
        "max_recursive_horizon_days": 60 if decisions["granularity"] == "day" else 336,
        "dataset_class": args.dataset_class,
        "served_as": serve_as,
        "development_only": serve_as == "internal",
        "registered_at_utc": datetime.now(dt_timezone.utc).isoformat(timespec="seconds"),
    }
    if args.install_registry:
        path = register_family(family, REGISTRY_PATH)
        suffix = {"internal": " (internal: loaded by tooling, never served)",
                  "demo": " (DEMO: served with a synthetic disclosure on every response)",
                  "production": " (production: verified observed data)"}[serve_as]
        print(f"[registry] family '{args.system_id}' written to {path.relative_to(ROOT)}" + suffix)
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
            result = train_daily(cleaned, dataset_metadata=metadata, tz=args.timezone,
                                 fit_window_days=args.fit_window_days or None)
            directory = ROOT / "backend/models" / args.system_id
            save_artifacts(result, directory)
            print(f"[train] day-granularity family trained and saved to {_rel(directory)}")
        else:
            command = [sys.executable, str(ROOT / "scripts/train_models.py"), "--data", str(csv_path),
                       "--metadata", str(sidecar_path), "--output-dir", str(ROOT / "backend/models" / args.system_id),
                       "--fit-window-days", str(args.fit_window_days or 0)]
            print("[train] " + " ".join(str(part) for part in command))
            subprocess.run([str(part) for part in command], check=True)


if __name__ == "__main__":
    main()
