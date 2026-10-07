"""Read-only audit of a candidate demand table, before anything is registered or trusted.

Why this exists separately from the profiler and the gate: a supplied file can be perfectly
normalizable and still be unusable for forecasting, because the things that decide whether a
supervised task is real are not schema facts. This module answers exactly the questions the
project must be able to cite:

* what is actually in the file (rows, columns, dtypes, cardinality, missingness, duplicates);
* is there one timestamp grid, per entity, with a measurable period - or several;
* which columns are demand-like, which are segmentation-like (line/corridor/direction),
  and whether a segmentation column merely labels rows or genuinely partitions the demand;
* what the file says about its own provenance (a `Data_Type`-style column declaring
  Synthetic/Simulated/Modelled is surfaced first, not discovered after a model is trained);
* **is a precomputed target column what it claims to be** - compared against the demand series
  itself at every plausible offset, per entity and per direction group. A `Target_*` column that
  does not reproduce `demand(t + k)` for a verified offset is not ground truth and is reported as
  unusable, so a model can never quietly learn from it.

Nothing here writes to or mutates the dataset; the audit is safe to run twice.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ml.data_pipeline.profile import profile_dataset
from ml.features.periodic import SECONDS_PER_DAY, infer_period

TARGET_NAME_RE = re.compile(r"(^|_)(target|targets|label|next|future|forecast|predicted|expected)(_|$)", re.I)
SYNTHETIC_MARKERS = ("synthetic", "simulat", "modelled", "modeled", "artificial", "fabricat", "dummy", "demo")
OBSERVED_MARKERS = ("observed", "actual", "measured", "counted", "recorded", "survey", "gate_line", "afc")
OFFSET_CANDIDATES = (1, 2, 3, 4, 6, 8, 12, 24, 48, 72, 96, 168)


def _text(values: Iterable[Any]) -> str:
    return " ".join(str(value).lower() for value in values if value is not None)


def _compact(values: pd.Series, limit: int = 14) -> list[str]:
    unique = [str(value) for value in pd.Series(values.dropna().astype(str).unique()).sort_values()]
    return unique[:limit] + ([f"+{len(unique) - limit} more"] if len(unique) > limit else [])


# --------------------------------------------------------------------------- inventory
def inventory(frame: pd.DataFrame) -> dict[str, Any]:
    rows = int(len(frame))
    columns: dict[str, dict[str, Any]] = {}
    for name in frame.columns:
        series = frame[name]
        numeric = pd.to_numeric(series, errors="coerce")
        integers = numeric.dropna()
        entry: dict[str, Any] = {
            "dtype": str(series.dtype),
            "missing": int(series.isna().sum()),
            "missing_share": round(float(series.isna().mean()), 4) if rows else 0.0,
            "distinct": int(series.nunique(dropna=True)),
            "constant": bool(series.nunique(dropna=True) <= 1),
            "numeric_share": round(float(numeric.notna().mean()), 4) if rows else 0.0,
        }
        if entry["numeric_share"] > 0.9 and integers.size:
            entry["min"] = float(integers.min())
            entry["max"] = float(integers.max())
            entry["integer_share"] = round(float((integers % 1 == 0).mean()), 4)
            entry["mean"] = round(float(integers.mean()), 3)
        if entry["numeric_share"] < 0.9:
            entry["sample_values"] = _compact(series.astype(str))
        columns[str(name)] = entry
    return {"rows": rows, "columns": len(frame.columns), "column_report": columns,
            "fully_duplicated_rows": int(frame.duplicated().sum()),
            "memory_mb": round(float(frame.memory_usage(deep=True).sum() / 1_048_576), 2)}


def provenance_flags(frame: pd.DataFrame) -> dict[str, Any]:
    """What the file declares about itself. A synthetic label outranks everything else here."""
    findings: list[dict[str, Any]] = []
    for name in frame.columns:
        series = frame[name]
        if pd.api.types.is_datetime64_any_dtype(series):
            continue
        values = series.dropna().astype(str)
        if values.empty:
            continue
        distinct = int(values.nunique())
        lowered_name = str(name).lower()
        text = _text(values.unique())
        synthetic = any(marker in text or marker in lowered_name for marker in SYNTHETIC_MARKERS)
        observed = any(marker in text or marker in lowered_name for marker in OBSERVED_MARKERS)
        flag_like = distinct <= 24 and bool(re.search(r"data[_ -]?type|source[_ -]?type|class|kind|category|type", lowered_name))
        if synthetic or (flag_like and (observed or distinct <= 4)):
            findings.append({
                "column": str(name), "distinct": distinct, "values": _compact(values, 8),
                "reads_as": "synthetic_or_simulated" if synthetic else "declared_observed",
                "synthetic_share": round(float(values.str.lower().str.contains("|".join(SYNTHETIC_MARKERS), regex=True).mean()), 4),
            })
    classification = "synthetic_development" if any(item["reads_as"] == "synthetic_or_simulated" for item in findings) else "undeclared"
    if findings and all(item["reads_as"] == "declared_observed" for item in findings):
        classification = "declared_observed_unverified"
    return {"declared_class_columns": findings, "classification": classification,
            "note": ("A file that labels itself synthetic stays synthetic: it can exercise and demonstrate the "
                     "pipeline, and can never be described as measured passenger data. A declared 'observed' "
                     "label is a claim to verify against provenance, not proof.")}


# --------------------------------------------------------------------------- temporal
def temporal_structure(frame: pd.DataFrame, profile: dict[str, Any], timezone: str) -> dict[str, Any]:
    timestamp_column = (profile.get("mapping") or {}).get("timestamp")
    entity_column = (profile.get("mapping") or {}).get("entity")
    if not timestamp_column or timestamp_column not in frame.columns:
        return {"error": "no timestamp column could be identified from the data"}
    raw = frame[timestamp_column]
    try:
        stamps = pd.to_datetime(raw, errors="coerce", format="mixed" if not pd.api.types.is_datetime64_any_dtype(raw) else None)
    except (TypeError, ValueError):
        stamps = pd.to_datetime(raw, errors="coerce")
    out: dict[str, Any] = {"timestamp_column": timestamp_column, "unparseable_rows": int(stamps.isna().sum())}
    if stamps.dt.tz is None:
        stamps = stamps.dt.tz_localize(timezone, ambiguous="NaT", nonexistent="NaT")
        out["timezone_applied"] = timezone
    elif str(stamps.dt.tz) != timezone:
        out["timezone_in_source"] = str(stamps.dt.tz)
        out["timezone_note"] = "source stamps carry their own offset; the audit keeps it rather than shifting the grid"
    if stamps.notna().any():
        out["min"] = str(stamps.min())
        out["max"] = str(stamps.max())
    out["distinct_timestamps"] = int(stamps.dropna().nunique())
    out["distinct_days"] = int(stamps.dropna().dt.normalize().nunique())
    slot_pattern = _slot_pattern(stamps)
    if slot_pattern:
        out["time_slots_present"] = slot_pattern
    try:
        period, evidence = infer_period(stamps.dropna().rename("timestamps"))
    except ValueError as exc:
        out["period"] = None
        out["period_error"] = str(exc)
        grid = _day_grid(frame, stamps, entity_column)
        if grid:
            out["candidate_grid"] = grid
            out["time_slot_note"] = ("only these clock times occur in the file; a product offering any other time would be "
                                     "prompting for a period with no observed series behind it")
            out["note"] = ("the intra-day spacing is not modal, so no single sub-day period can be claimed; the "
                           "recurring day x slot structure above is what the file actually supports")
        return out
    out["period"] = {"seconds": int(period), "granularity": evidence["granularity"], **evidence}
    step = pd.Timedelta(seconds=int(period))
    grid = stamps.dropna().dt.normalize() if period >= SECONDS_PER_DAY else stamps.dropna().dt.floor(step)
    out["distinct_periods"] = int(grid.nunique())
    if period < SECONDS_PER_DAY:
        grid = _day_grid(frame, stamps, entity_column)
        if grid and grid["slots_per_day"] <= 12:
            out["candidate_grid"] = grid
            out["time_slot_note"] = ("only these clock times occur in the file; a product offering any other time would be "
                                     "prompting for a period with no observed series behind it")
    if entity_column:
        keyed = frame.assign(_stamp=stamps).dropna(subset=["_stamp"])
        entity_key = keyed[entity_column].astype(str)
        per_entity = keyed.groupby(entity_key)["_stamp"].agg(["size", "nunique", "min", "max"])
        out["entities"] = {
            "column": entity_column, "count": int(len(per_entity)),
            "rows_per_entity": {"min": int(per_entity["size"].min()), "median": float(per_entity["size"].median()),
                                "max": int(per_entity["size"].max())},
            "distinct_timestamps_per_entity": {"min": int(per_entity["nunique"].min()), "max": int(per_entity["nunique"].max())},
            "span_days": {"min": int((per_entity["max"] - per_entity["min"]).dt.days.min()),
                          "max": int((per_entity["max"] - per_entity["min"]).dt.days.max())},
        }
        steps = keyed.assign(_entity=entity_key).sort_values(["_entity", "_stamp"]).groupby("_entity", sort=False)["_stamp"].diff().dropna()
        seconds = steps.dt.total_seconds()
        counts = seconds.value_counts()
        out["within_entity_spacing"] = {str(int(spacing)): int(count) for spacing, count in counts.head(6).items()}
        out["off_grid_steps"] = int((seconds != period).sum())
        out["off_grid_step_share"] = round(float((seconds != period).mean()), 4) if len(seconds) else 0.0
        expected_cells = 0
        for _, row in per_entity.iterrows():
            expected_cells += int(len(pd.date_range(row["min"], row["max"], freq=step)))
        observed_cells = int(keyed.assign(_entity=entity_key).drop_duplicates(["_entity", "_stamp"]).shape[0])
        out["grid_cells"] = {"expected_over_entity_spans": expected_cells, "observed": observed_cells,
                             "missing": max(0, expected_cells - observed_cells),
                             "coverage_ratio": round(observed_cells / expected_cells, 4) if expected_cells else None}
        # Is the sequence contiguous hour-by-hour, or slot-based (sparse clock times per day)?
        if period < SECONDS_PER_DAY and len(counts):
            per_day_slots = keyed.assign(_stamp=stamps).dropna(subset=["_stamp"]).groupby(
                [keyed[entity_column].astype(str), stamps.dropna().dt.normalize() if stamps.notna().any() else 0]).size()
            out["slots_per_entity_day"] = {"min": int(per_day_slots.min()), "median": float(per_day_slots.median()),
                                           "max": int(per_day_slots.max()),
                                           "continuous_hours": bool(int(per_day_slots.max()) >= 20)}
    return out


def _slot_pattern(stamps: pd.Series) -> dict[str, Any] | None:
    clean = pd.to_datetime(stamps, errors="coerce").dropna()
    if clean.empty:
        return None
    counts = clean.dt.strftime("%H:%M").value_counts().sort_index()
    if len(counts) < 2:
        return None
    return {"count": int(len(counts)), "slots": {str(key): int(value) for key, value in counts.items()}}


def _day_grid(frame: pd.DataFrame, stamps: pd.Series, entity_column: str | None) -> dict[str, Any] | None:
    """Is the file really a day grid whose days carry a handful of recurring slots?

    This is the difference between 'six observations a day per station' and 'a broken hourly file':
    the first supports next-day, same-slot forecasting, the second supports nothing honest.
    """
    clean = pd.to_datetime(stamps, errors="coerce")
    dates = clean.dropna().dt.normalize()
    if dates.nunique() < 3:
        return None
    steps = dates.sort_values().drop_duplicates().diff().dropna().dt.total_seconds()
    modal = steps.mode().iloc[0] if len(steps) else None
    if modal is None or int(modal) != SECONDS_PER_DAY:
        return None
    share = float((steps == SECONDS_PER_DAY).mean())
    slots = _slot_pattern(clean)
    if not slots or slots["count"] > 16:
        return None
    keyed = frame.assign(_date=dates.dt.date, _slot=clean.dt.strftime("%H:%M"))
    per_day = keyed.dropna(subset=["_date"]).groupby([entity_column, "_date"]).size() if entity_column else keyed.groupby("_date").size()
    cells_expected = int(len(keyed.groupby([entity_column, "_date", "_slot"]).size()) if entity_column else 0)
    return {"daily_contiguous_share": round(share, 4), "distinct_days": int(dates.nunique()),
            "slots_per_day": int(slots["count"]), "slots": list(slots["slots"]),
            "observations_per_entity_day": {"min": int(per_day.min()), "median": float(per_day.median()),
                                            "max": int(per_day.max())},
            "distinct_entity_day_slot_series": cells_expected or None,
            "implied_formulation": ("predict the same slot on a later day (demand(station, slot, d) -> "
                                    "demand(station, slot, d + k)) rather than the next clock hour")}


# --------------------------------------------------------------------------- segments
def segmentation_columns(frame: pd.DataFrame, *, entity_column: str | None, demand_column: str | None,
                         timestamp_column: str | None = None) -> dict[str, Any]:
    """Line / corridor / direction / status fields: what they hold, and how they relate to demand."""
    rows = int(len(frame))
    found: dict[str, dict[str, Any]] = {}
    skip = {str(entity_column), str(demand_column), str(timestamp_column)}
    for name in frame.columns:
        if str(name) in skip:
            continue
        if pd.api.types.is_datetime64_any_dtype(frame[name]):
            continue
        series = frame[name]
        distinct = int(series.nunique(dropna=True))
        if distinct > max(80, int(0.05 * rows)):
            continue
        lowered = str(name).lower()
        numeric_share = float(pd.to_numeric(series, errors="coerce").notna().mean())
        if numeric_share > 0.95 and distinct > 40:
            continue
        role = ("direction" if re.search(r"direction|towards|destination|origin|from_st|to_st|source_st", lowered)
                else "line_or_corridor" if re.search(r"line|corridor|route|branch|section|path|railway|zone", lowered)
                else "status" if re.search(r"status|state|condition|operational|open", lowered)
                else "time_like" if re.search(r"time|hour|slot|period", lowered)
                else "other_categorical")
        entry: dict[str, Any] = {"distinct": distinct, "role_guess": role, "values": _compact(series.astype(str))}
        if distinct < 2:
            # A corridor/line field that never varies cannot drive a selection control; saying so
            # is more useful than silently dropping the column from the report.
            entry["constant"] = True
            entry["relation"] = "single value across the whole file: cannot be a selection dimension"
            found[str(name)] = entry
            continue
        if demand_column and role in {"direction", "line_or_corridor", "other_categorical"} and entity_column:
            keyed = frame.assign(_entity=frame[entity_column].astype(str))
            per_segment = keyed.groupby([series.astype(str), keyed["_entity"]])[demand_column].apply(
                lambda values: float(pd.to_numeric(values, errors="coerce").sum()))
            entity_total = keyed.groupby("_entity")[demand_column].apply(lambda values: float(pd.to_numeric(values, errors="coerce").sum()))
            parts = per_segment.groupby(level=1).sum()
            ratio = float((parts / entity_total.replace(0, np.nan)).median()) if len(parts) else None
            entry["segments_per_entity_median"] = float(keyed.groupby("_entity")[series.name].nunique().median())
            entry["sum_of_parts_over_entity_total"] = round(ratio, 4) if ratio is not None and np.isfinite(ratio) else None
            entry["relation"] = ("each entity appears under ~1 value, so this labels entities rather than splitting rows"
                                 if entry["segments_per_entity_median"] <= 1.2
                                 else f"each entity appears under ~{round(entry['segments_per_entity_median'], 1)} values, so rows are split by it")
        found[str(name)] = entry
    return {"candidates": found, "count": len(found)}


def duplicate_key_analysis(frame: pd.DataFrame, *, entity_column: str | None, timestamp_column: str | None) -> dict[str, Any]:
    if not (entity_column and timestamp_column):
        return {"error": "needs both an entity and a timestamp column"}
    raw = frame[timestamp_column]
    stamps = pd.to_datetime(raw, errors="coerce", format="mixed" if not pd.api.types.is_datetime64_any_dtype(raw) else None)
    keyed = frame.assign(_stamp=stamps)
    duplicated = keyed.duplicated([entity_column, "_stamp"], keep=False)
    unique_rows = int(len(keyed) - keyed.drop_duplicates([entity_column, "_stamp"]).shape[0])
    out: dict[str, Any] = {"duplicate_entity_timestamp_rows": int(duplicated.sum()), "redundant_rows": unique_rows}
    if unique_rows:
        disambiguators: dict[str, int] = {}
        sample = keyed.loc[duplicated]
        for name in frame.columns:
            if str(name) in {str(entity_column), str(timestamp_column)}:
                continue
            spread = sample.groupby([entity_column, "_stamp"])[name].nunique()
            if float(spread.max()) > 1:
                disambiguators[str(name)] = int(spread.max())
        # Numeric measure columns vary inside every key trivially (they hold the values themselves),
        # so they cannot be the key. Rank the categorical candidates that can actually be it.
        categorical = {name: spread for name, spread in disambiguators.items()
                       if not pd.api.types.is_numeric_dtype(frame[name])
                       or int(pd.to_numeric(frame[name], errors="coerce").nunique(dropna=True)) <= 60}
        out["columns_that_disambiguate_repeated_keys"] = categorical or disambiguators
        out["every_column_that_varies"] = len(disambiguators)
        out["suggestion"] = ("repeated (entity, timestamp) keys are legitimate when a column such as "
                             f"{list(disambiguators)[:3]} varies within them; register a composite entity key "
                             "(--entity-key-columns) so those rows stay separate series and are never summed together")
    return out


# --------------------------------------------------------------------------- demand
def demand_candidates(profile: dict[str, Any]) -> dict[str, Any]:
    scores = (profile.get("scores") or {}).get("demand") or {}
    ranked = sorted(scores.items(), key=lambda item: -(item[1].get("score") if isinstance(item[1], dict) else -9))
    return {"chosen": (profile.get("mapping") or {}).get("demand"),
            "ambiguous": list(profile.get("ambiguous_demand_columns") or []),
            "table": {name: {"score": value.get("score"), "disqualifiers": value.get("disqualifiers")}
                      for name, value in ranked[:14] if isinstance(value, dict)},
            "name_hint_columns": sorted(str(name) for name in profile.get("columns", {})
                                        if any(hint in str(name).lower() for hint in DEMAND_HINTS))}


DEMAND_HINTS = ("passenger", "ridership", "rider", "board", "entry", "entries", "demand", "count", "volume", "traffic")


def target_like_columns(frame: pd.DataFrame) -> list[str]:
    return [str(name) for name in frame.columns if TARGET_NAME_RE.search(str(name))]


# --------------------------------------------------------------------------- §3 target audit
def _aligned_target(tests: pd.DataFrame, group_keys: list[str], order: str, shift: int,
                    demand: str, target: str, tolerance: float) -> dict[str, Any] | None:
    work = tests.sort_values(group_keys + [order]).copy()
    for key in group_keys:
        if work[key].isna().all():
            return None
    shifted = work.groupby(group_keys, sort=False)[demand].shift(-int(shift))
    work["_expected"] = shifted
    valid = work.dropna(subset=["_expected", target])
    if len(valid) < 30:
        return None
    observed = pd.to_numeric(valid[target], errors="coerce")
    expected = pd.to_numeric(valid["_expected"], errors="coerce")
    finite = observed.notna() & expected.notna()
    if int(finite.sum()) < 30:
        return None
    observed, expected = observed[finite].astype(float), expected[finite].astype(float)
    difference = (observed - expected).abs()
    exact = float((difference <= tolerance).mean())
    relative = float((difference / expected.where(expected != 0)).replace([np.inf, -np.inf], np.nan).median())
    correlation = float(observed.corr(expected)) if observed.std() > 0 and expected.std() > 0 else None
    return {"compared_rows": int(len(observed)), "exact_or_within_tolerance": round(exact, 4),
            "median_relative_difference": round(relative, 4) if np.isfinite(relative) else None,
            "mean_absolute_difference": round(float(difference.mean()), 3),
            "correlation": round(correlation, 4) if correlation is not None and np.isfinite(correlation) else None,
            "verdict": ("CONSISTENT" if exact >= 0.999 else "PARTIALLY_CONSISTENT" if exact >= 0.9 else "INCONSISTENT")}


def target_column_audit(frame: pd.DataFrame, *, timestamp_column: str | None, entity_column: str | None,
                        demand_column: str | None, period_seconds: int | None, target_columns: list[str] | None = None,
                        segment_columns: list[str] | None = None, tolerance: float = 0.5) -> dict[str, Any]:
    """Does a precomputed target column reproduce the demand series at some future offset?

    Tested at every plausible offset, both per entity and per (entity, segment) group so that a
    target defined on a direction-segmented series is not wrongly judged against station totals.
    ``UNVERIFIABLE`` is a real answer: when the file's own key structure does not allow the shift to
    be aligned, the column must not be used as a label either.
    """
    if not demand_column or demand_column not in frame.columns:
        return {"error": "no demand column identified, so no target can be verified against it"}
    period = int(period_seconds or 0)
    explicit = list(target_columns or [])
    candidates = sorted(set(explicit) | set(target_like_columns(frame)))
    candidates = [name for name in candidates if name != demand_column and name in frame.columns]
    if not candidates:
        return {"candidates": [], "verdict_summary": "no precomputed target column present; the supervised "
                "target must be derived from the demand series itself"}
    stamps = pd.to_datetime(frame[timestamp_column], errors="coerce",
                            format="mixed" if not pd.api.types.is_datetime64_any_dtype(frame[timestamp_column])
                            else None) if timestamp_column else None
    work = frame.copy()
    if stamps is not None:
        work["_stamp"] = stamps
        order = "_stamp"
    else:
        order = str(frame.index.name or "index")
        work[order] = np.arange(len(work))
    if entity_column:
        work["_entity"] = work[entity_column].astype(str)
    base_groups = ["_entity"] if entity_column else []
    offsets = list(dict.fromkeys([*OFFSET_CANDIDATES]))
    if period and period < SECONDS_PER_DAY:
        slots = int(round(SECONDS_PER_DAY / period))
        offsets = list(dict.fromkeys([*offsets, slots, slots * 2, slots * 7]))
    summary: dict[str, Any] = {}
    for target in candidates:
        if float(pd.to_numeric(work[target], errors="coerce").notna().mean()) < 0.5:
            summary[target] = {"verdict": "UNVERIFIABLE", "reason": "column is not numeric for most rows"}
            continue
        tests: dict[str, Any] = {}
        best: tuple[float, str, dict[str, Any]] | None = None
        group_sets = {"entity": base_groups} if base_groups else {}
        for segment in (segment_columns or []):
            if segment in work.columns and str(segment) != str(entity_column):
                group_sets[f"entity+{segment}"] = base_groups + [str(segment)]
        if not group_sets:
            group_sets = {"whole_file": []}
        for label, keys in group_sets.items():
            if not keys:
                continue
            for offset in offsets:
                result = _aligned_target(work, keys, order, offset, demand_column, target, tolerance)
                if not result:
                    continue
                tests[f"{label}@+{offset}"] = result
                score = result["exact_or_within_tolerance"]
                if best is None or score > best[0]:
                    best = (score, f"{label}@+{offset}", result)
        if not tests:
            summary[target] = {"verdict": "UNVERIFIABLE",
                               "reason": ("no grouping/offset produced enough aligned rows to compare; the file's key "
                                          "structure does not allow the claim to be checked"),
                               "target_column": target}
            continue
        verdict = {"verdict": best[2]["verdict"], "best_alignment": best[1], "evidence": best[2],
                   "alignments_tested": len(tests), "all_alignments": tests}
        if verdict["verdict"] == "CONSISTENT":
            verdict["decision"] = (f"'{target}' reproduces {demand_column} shifted forward at {best[1]}; it is a derived "
                                   "duplicate of the demand series, so it may be ignored and the target rebuilt from the "
                                   "series (preferred) or reused after this check")
        else:
            verdict["decision"] = (f"'{target}' does not reproduce the demand series at any tested offset "
                                   f"(best exact match {round(best[0] * 100, 2)} % at {best[1]}); it is NOT usable as a "
                                   "ground-truth label and the supervised target must be derived from the chronological "
                                   "demand series instead")
        summary[target] = verdict
    usable = [name for name, value in summary.items() if isinstance(value, dict) and value.get("verdict") == "CONSISTENT"]
    return {"demand_column": demand_column, "candidates": candidates, "per_target": summary,
            "usable_as_ground_truth": usable,
            "policy": ("A precomputed target is accepted only if it reproduces the demand column shifted forward by a "
                       "verified offset for at least 99.9 % of aligned rows; anything else is ignored as ground truth.")}


# --------------------------------------------------------------------------- entry points
def audit_frame(frame: pd.DataFrame, *, timezone: str = "Asia/Kolkata", ignore_columns: list[str] | None = None,
                dataset_class: str | None = None) -> dict[str, Any]:
    # The audit reads the file's own provenance declaration first and profiles it under that class: a
    # table that says `Data_Type = Synthetic` has no observed column to protect, so its modelled demand
    # series is a legitimate subject - while a label-shaped column is still never mistaken for the series.
    declared = dataset_class or ("synthetic"
                                 if provenance_flags(frame)["classification"] == "synthetic_development" else None)
    profile = profile_dataset(frame, timezone=timezone, ignore_columns=list(ignore_columns or []),
                              dataset_class=declared)
    mapping = profile.get("mapping") or {}
    timestamp_column, entity_column, demand_column = mapping.get("timestamp"), mapping.get("entity"), mapping.get("demand")
    temporal = temporal_structure(frame, profile, timezone)
    period = (temporal.get("period") or {}).get("seconds")
    segments = segmentation_columns(frame, entity_column=entity_column, demand_column=demand_column,
                                     timestamp_column=timestamp_column)
    segment_names = [name for name, entry in segments["candidates"].items()
                     if entry.get("role_guess") in {"direction", "line_or_corridor", "other_categorical"}][:6]
    targets = target_column_audit(frame, timestamp_column=timestamp_column, entity_column=entity_column,
                                 demand_column=demand_column, period_seconds=period,
                                 segment_columns=segment_names)
    return {"inventory": inventory(frame), "provenance": provenance_flags(frame), "temporal": temporal,
            "profiler": {"mapping": mapping, "granularity": profile.get("granularity"),
                         "demand": demand_candidates(profile)},
            "segmentation": segments, "duplicate_keys": duplicate_key_analysis(frame, entity_column=entity_column,
                                                                              timestamp_column=timestamp_column),
            "precomputed_targets": targets,
            "readiness": _readiness(profile, temporal, targets, mapping)}


def _readiness(profile: dict[str, Any], temporal: dict[str, Any], targets: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if not mapping.get("timestamp"):
        blockers.append("no timestamp column identified")
    if not mapping.get("entity"):
        blockers.append("no entity column identified")
    if not mapping.get("demand"):
        blockers.append("no demand column identified - nothing to forecast")
    if profile.get("ambiguous_demand_columns"):
        blockers.append(f"ambiguous demand target: {profile['ambiguous_demand_columns']}")
    if temporal.get("period_error"):
        blockers.append(f"no measurable period: {temporal['period_error']}")
    elif (temporal.get("grid_cells") or {}).get("coverage_ratio") is not None and temporal["grid_cells"]["coverage_ratio"] < 0.5:
        blockers.append(f"only {round(temporal['grid_cells']['coverage_ratio'] * 100, 1)} % of the entity grid is present")
    grid = (temporal or {}).get("candidate_grid")
    if grid:
        blockers_note = (f"time slots actually present: {', '.join(grid['slots'])} - anything else has no observed "
                         f"series; formulation: {grid['implied_formulation']}")
    else:
        blockers_note = None
    unusable = [name for name, value in (targets.get("per_target") or {}).items()
                if isinstance(value, dict) and value.get("verdict") != "CONSISTENT"]
    return {"blockers": blockers, "supported_time_slots_note": blockers_note,
            "ignored_precomputed_targets": unusable,
            "can_enter_registration": not blockers,
            "note": "Registration re-runs these checks plus the ten-criterion gate; this audit never writes anything."}


def read_large_csv(path: "str | Path", nrows: int | None = None) -> pd.DataFrame:
    """Read a big table with every text column as a categorical.

    A 683k-row, 27-column supply file is a gigabyte of Python strings and this container has about a
    gigabyte of memory in total; categoricals keep the audit honest about the *whole* file instead of
    forcing a sample. Values are untouched - only the storage changes.
    """
    probe = pd.read_csv(path, nrows=0)
    dtypes = {name: "category" for name in probe.columns
              if str(probe[name].dtype) == "object"}
    return pd.read_csv(path, nrows=nrows, dtype=dtypes)


def audit_csv(path: "str | Path", *, timezone: str = "Asia/Kolkata", nrows: int | None = None,
              ignore_columns: list[str] | None = None, low_memory: bool = False,
              dataset_class: str | None = None) -> dict[str, Any]:
    frame = read_large_csv(path, nrows) if low_memory else (
        pd.read_csv(path, nrows=nrows, encoding="utf-8-sig") if nrows
        else pd.read_csv(path, encoding="utf-8-sig"))
    report = audit_frame(frame, timezone=timezone, ignore_columns=ignore_columns, dataset_class=dataset_class)
    report["source"] = {"path": str(path), "size_bytes": int(Path(path).stat().st_size),
                        "sha256": __import__("hashlib").sha256(Path(path).read_bytes()).hexdigest()}
    return report
