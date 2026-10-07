"""Dataset profiling and semantic column mapping for arbitrary demand tables.

The pipeline must adapt to a new operator's file without becoming gullible. So nothing here
decides a column's role from its header text: names contribute a bounded prior only, and
every role also has to survive data-driven checks on type, missingness, cardinality, value
pattern, temporal structure and per-entity repetition. Ambiguity is reported, not resolved
by guesswork - if two columns could be the target, the caller is asked to choose.

Roles produced:

``timestamp``   one parseable, strictly orderable datetime column
``entity``      the grouping key with repeated observations over time
``demand``      the observed passenger-count target (never a forecast-like column)
``entity_name`` optional label column that must be 1:1 with the entity key
``categorical`` optional descriptors (direction, service type, line, measure, ...)
``numeric``     optional numeric context (scheduled services, capacity, ...)
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import re

import pandas as pd

#: Header priors. A name alone never scores above ``NAME_PRIOR_CAP``; the data decides.
DEMAND_NAME_HINTS = {
    "passengers", "passenger", "passenger_count", "passengers_count", "passenger_count_total", "ridership",
    "riders", "riders_count", "entries", "entry_count", "entrants", "boardings", "boarding", "boarding_count",
    "demand", "demand_count", "passenger_demand", "footfall", "traffic", "pax", "count", "total",
    "daily_passengers", "hourly_ridership", "alightings", "exits", "users",
}
TIME_NAME_HINTS = {"timestamp", "datetime", "date_time", "date", "day", "time", "period", "hour", "observed_at",
                   "observation_date", "report_date", "collection_date", "datehour", "samptime", "hour_start"}
ENTITY_NAME_HINTS = {"station", "station_id", "station_code", "station_name", "entity", "entity_id", "stop_id",
                     "stop", "code", "id", "name", "terminal", "depot", "location", "zone"}
#: A column named like a label is not the series: it is excluded from being the demand measure when a
#: plain series column exists, because a precomputed target must never become the thing we learn from
#: without the verification the project requires (see ml/data_pipeline/audit.py).
TARGET_SHAPE_PATTERN = ("target", "targets", "label", "next_hour", "next_day", "next_period", "future_")
#: A file that declares itself synthetic has no observed ground truth by definition, so the honesty
#: burden sits on the serving mode and the disclosure - not on refusing to model its own numbers.
DECLARED_SYNTHETIC_CLASSES = ("synthetic", "simulated", "modelled", "modeled", "development", "demo")
FORECAST_MARKERS = ("forecast", "predicted", "prediction", "model", "estimated", "estimate", "projection",
                    "scenario", "planned", "projected", "interpolated", "simulated", "synthetic", "fake", "dummy")
NAME_PRIOR_CAP = 0.30
_DT_INPUT_FORMATS = [None, "mixed", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y",
                     "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"]


def _looks_like_sequential_identifier(series: pd.Series, rows: int) -> bool:
    """A surrogate key, not a measurement: integer, unique per row, strictly rising in file order
    at a constant step. A real demand series can trend upward, but it does not increment by the
    same integer for every row of a multi-entity export - and if it somehow did, an explicit
    --demand-column override still reaches it, with the disqualifier printed as a warning."""
    if rows <= 50 or float(series.notna().mean()) < 1.0:
        return False
    if int(series.nunique()) / rows <= 0.9:
        return False
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype="float64")
    if not np.all(np.isfinite(values)) or not np.all(values == np.floor(values)):
        return False
    steps = np.diff(values)
    if steps.size < 2 or not np.all(steps > 0):
        return False
    return bool(np.std(steps) / max(float(np.mean(steps)), 1e-9) < 0.02)


def _norm(name: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in str(name).lower()).strip("_")


def _name_prior(column: str, hints: Iterable[str]) -> float:
    normalized = _norm(column)
    hints = {_norm(hint) for hint in hints}
    if normalized in hints:
        return NAME_PRIOR_CAP
    if any(hint in normalized or normalized in hint for hint in hints):
        return NAME_PRIOR_CAP / 2
    return 0.0


def _try_datetime(series: pd.Series) -> tuple[pd.Series | None, float, str]:
    """Parse with the format that maximizes coverage; report the format that actually worked."""
    if isinstance(series.dtype, pd.CategoricalDtype):
        series = series.astype(object)
    best: tuple[pd.Series | None, float, str] = (None, 0.0, "unparseable")
    for fmt in _DT_INPUT_FORMATS:
        try:
            with warnings.catch_warnings():
                # pandas raises UserWarning for per-element dateutil fallback and FutureWarning for
                # mixed-offset parsing; the profiler only needs to know whether the column parses.
                warnings.simplefilter("ignore", (UserWarning, FutureWarning))
                parsed = pd.to_datetime(series, errors="coerce", format=fmt) if fmt else pd.to_datetime(series, errors="coerce")
        except (TypeError, ValueError, OverflowError):
            continue
        rate = float(parsed.notna().mean()) if len(parsed) else 0.0
        if rate > best[1]:
            label = "ISO-8601 / pandas default" if fmt is None else ("flexible mixed" if fmt == "mixed" else fmt)
            best = (parsed, rate, label)
        if rate == 1.0:
            break
    return best


def _autocorrelation(values: np.ndarray, lag: int = 1) -> float | None:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < lag + 8 or np.allclose(values.std(), 0):
        return None
    left, right = values[:-lag], values[lag:]
    return float(np.corrcoef(left, right)[0, 1])


def profile_dataset(frame: pd.DataFrame, *, timezone: str = "Asia/Kolkata",
                    ignore_columns: Iterable[str] = (), dataset_class: str | None = None,
                    timestamp_column: str | None = None) -> dict[str, Any]:
    """`timestamp_column` forces which column carries the moment (e.g. after a file's split `Date`+`Time`
    have been joined); the grid is then measured on that column, so a forced choice cannot contradict the
    spacing the pipeline reports."""
    """Score every column and return a profile with evidence for each decision."""
    if frame is None or len(frame) == 0:
        raise ValueError("The dataset is empty; there is nothing to profile.")
    frame = frame.copy()
    # A large supplied file may arrive with text columns stored as categoricals (that is how the
    # low-memory audit read works). Categoricals have no usable min/max and compare by category
    # order, so the profiler flattens them to values first: it analyses data, not storage.
    categoricals = [name for name in frame.columns if isinstance(frame[name].dtype, pd.CategoricalDtype)]
    if categoricals:
        frame[categoricals] = frame[categoricals].astype(object)
    ignored = {_norm(name) for name in ignore_columns}
    report: dict[str, dict[str, Any]] = {}
    rows = len(frame)

    for column in frame.columns:
        if _norm(column) in ignored:
            report[str(column)] = {"role": "ignored", "reason": "listed in ignore_columns"}
            continue
        series = frame[column]
        entry: dict[str, Any] = {
            "dtype": str(series.dtype),
            "missing_share": round(float(series.isna().mean()), 4),
            "distinct": int(series.nunique(dropna=True)),
        }
        numeric = pd.to_numeric(series, errors="coerce")
        numeric_share = float(numeric.notna().mean())
        entry["numeric_share"] = round(numeric_share, 4)
        if numeric_share > 0.9:
            finite = numeric.dropna()
            integers = float(np.mean(np.isclose(finite, finite.round()))) if len(finite) else 0.0
            entry.update({
                "min": float(finite.min()) if len(finite) else None,
                "max": float(finite.max()) if len(finite) else None,
                "mean": round(float(finite.mean()), 4) if len(finite) else None,
                "negative_share": round(float((finite < 0).mean()), 4) if len(finite) else 0.0,
                "integer_share": round(integers, 4),
                "coefficient_of_variation": round(float(finite.std() / finite.mean()), 4) if len(finite) and finite.mean() else None,
                "lag1_autocorrelation": None,
            })
        parsed, rate, used_format = _try_datetime(series)
        entry["datetime_parse_share"] = round(rate, 4)
        if rate > 0.9:
            assert parsed is not None
            entry["datetime_format"] = used_format
            entry["datetime_distinct_days"] = int(parsed.dropna().dt.normalize().nunique())
            entry["datetime_first"] = str(parsed.min())
            entry["datetime_last"] = str(parsed.max())
        report[str(column)] = entry

    # --- timestamp candidates -------------------------------------------------------
    time_scores: dict[str, float] = {}
    for column, entry in report.items():
        rate = float(entry.get("datetime_parse_share") or 0.0)
        if rate < 0.95:
            continue
        span_days = 0
        try:
            parsed = pd.to_datetime(frame[column].astype(object)
                                    if isinstance(frame[column].dtype, pd.CategoricalDtype)
                                    else frame[column], errors="coerce")
            span_days = int((parsed.max() - parsed.min()).days)
        except (TypeError, ValueError):
            continue
        days = int(entry.get("datetime_distinct_days") or 0)
        score = rate * 0.45 + min(1.0, days / 30) * 0.25 + min(1.0, span_days / 60) * 0.10
        score += 0.20 * (_name_prior(column, TIME_NAME_HINTS) / NAME_PRIOR_CAP)
        time_scores[column] = round(score, 4)

    # --- entity candidates ----------------------------------------------------------
    entity_scores: dict[str, float] = {}
    for column, entry in report.items():
        distinct = int(entry["distinct"])
        if distinct < 2 or entry["missing_share"] > 0.05:
            continue
        coverage = distinct / rows
        # A column that is unique per row is a record id, not an entity: it would make
        # every series one observation long. That is the single most common false friend.
        if coverage > 0.9:
            entity_scores[column] = -1.0
            entry["rejected_as_record_identifier"] = True
            continue
        series = frame[column].astype(str)
        numeric_like = float(pd.to_numeric(series, errors="coerce").notna().mean())
        repeated = min(1.0, (rows / max(distinct, 1)) / 10)
        score = repeated * 0.45 + (1 - coverage) * 0.25 + (0.15 if numeric_like < 0.98 else 0.05)
        score += _name_prior(column, ENTITY_NAME_HINTS)
        entity_scores[column] = round(score, 4)

    # --- demand candidates ----------------------------------------------------------
    declared = str(dataset_class or "").lower()
    accepts_modelled_series = any(token in declared for token in DECLARED_SYNTHETIC_CLASSES)
    demand_scores: dict[str, dict[str, Any]] = {}
    for column, entry in report.items():
        if float(entry.get("numeric_share") or 0.0) < 0.95:
            continue
        minimum, maximum = entry.get("min"), entry.get("max")
        variation = entry.get("coefficient_of_variation")
        if minimum is None or maximum is None or maximum == 0:
            continue
        reasons: list[str] = []
        lowered = _norm(column)
        if any(marker in lowered for marker in FORECAST_MARKERS) and not accepts_modelled_series:
            reasons.append(f"header marks it as modelled/simulated output ({column})")
        if minimum < 0:
            reasons.append("contains negative counts")
        if float(entry.get("integer_share") or 0) < 0.9:
            reasons.append("mostly fractional, so it looks like a ratio or price rather than a headcount")
        if variation is None or variation <= 0.01:
            reasons.append("no usable variability over time (near-constant column)")
        if _looks_like_sequential_identifier(frame[column], rows):
            reasons.append("behaves like a sequential record identifier (one unique, evenly spaced value per row), "
                           "not a passenger count")
        if int(entry["distinct"]) <= 4 and float(maximum) <= 4:
            reasons.append(f"a small-integer code ({int(entry['distinct'])} distinct values up to {maximum}), "
                           "not a passenger count")
        score = 0.30 * (1 - min(1.0, abs(float(entry.get("negative_share") or 0)) * 4))
        score += 0.25 * min(1.0, (variation or 0) / 0.6)
        score += 0.20 * min(1.0, (maximum or 0) / 50)  # a demand count reaches tens or more
        score += 0.15 * (0 if float(entry.get("integer_share") or 0) < 0.9 else 1.0)
        score += _name_prior(column, DEMAND_NAME_HINTS)
        demand_scores[column] = {"score": round(score, 4), "disqualifiers": reasons,
                                 "min": minimum, "max": maximum, "coefficient_of_variation": variation}

    def best(mapping: dict) -> str | None:
        positive = {key: (value["score"] if isinstance(value, dict) else value) for key, value in mapping.items()}
        positive = {key: value for key, value in positive.items() if value is not None and value > 0}
        if not positive:
            return None
        return sorted(positive.items(), key=lambda item: (-item[1]["score"] if isinstance(item[1], dict) else -item[1], item[0]))[0][0]

    timestamp_column = timestamp_column if (timestamp_column and timestamp_column in frame.columns) else best(time_scores)
    entity_column = best(entity_scores)
    # A precomputed target/label column (`Target_Next_Hour_*`, `Next_Demand`, `Label_*`) describes the
    # answer, not the series. If the file also carries a plain series column, the label column is
    # excluded from being the demand measure - so the supervised target is then rebuilt from the series
    # under the project's verification rule rather than inherited from a name.
    target_shaped = [key for key in demand_scores
                      if any(token in _norm(key) for token in TARGET_SHAPE_PATTERN)]
    if target_shaped and any(key not in target_shaped and not value["disqualifiers"]
                             for key, value in demand_scores.items()):
        for key in target_shaped:
            demand_scores[key]["disqualifiers"].append(
                "is a precomputed target/label column, so it describes the answer rather than the demand series")
    eligible_demand = {key: value for key, value in demand_scores.items() if not value["disqualifiers"]}
    demand_column = best(eligible_demand) if eligible_demand else None
    # Ambiguity is a near-tie, not merely the existence of other numeric columns: a column that
    # scores far below the winner is not a competing description of the same quantity, while a
    # near-tie means two columns could each be "the passenger count" and the pipeline must ask.
    ambiguous: list[str] = []
    if demand_column is not None:
        top_score = float(demand_scores[demand_column]["score"])
        ambiguous = sorted(key for key, value in demand_scores.items()
                           if key != demand_column and not value["disqualifiers"]
                           and isinstance(value.get("score"), (int, float)) and float(value["score"]) >= top_score - 0.05)

    granularity: dict[str, Any] = {"detected": None, "evidence": {}}
    if timestamp_column and entity_column:
        parsed = pd.to_datetime(frame[timestamp_column], errors="coerce")
        from ml.features.periodic import infer_period
        try:
            period, evidence = infer_period(parsed.rename("timestamps"))
            granularity = {"detected": evidence["granularity"], "period_seconds": period, "evidence": evidence}
        except ValueError as exc:
            granularity = {"detected": None, "error": str(exc)}

    mapping = {"timestamp": timestamp_column, "entity": entity_column, "demand": demand_column}
    entity_name_column = None
    if entity_column:
        # Hard requirement: exactly one label per entity key. The header only breaks ties.
        entity_cardinality = int(report[entity_column]["distinct"])
        provenance_like = re.compile(r"^(data_type|source_type|provenance|is_\w+|.*_flag)$")
        labels = [column for column in report
                  if column != entity_column and 2 <= report[column]["distinct"]
                  and int(entity_cardinality) * (0.5 if entity_cardinality > 3 else 1)
                  <= report[column]["distinct"] <= max(2, int(1.4 * entity_cardinality))
                  and report[column]["numeric_share"] < 0.5
                  and not provenance_like.match(_norm(column))]
        scored = []
        for candidate in labels:
            pairs = frame[[entity_column, candidate]].dropna()
            if len(pairs) and int(pairs.groupby(entity_column)[candidate].nunique().max()) == 1:
                scored.append((_name_prior(candidate, ENTITY_NAME_HINTS), candidate))
        entity_name_column = max(scored)[1] if scored else None
    mapping["entity_name"] = entity_name_column
    mapping["categorical"] = sorted(
        column for column, entry in report.items()
        if column not in (timestamp_column, entity_column, demand_column, entity_name_column)
        and entry["numeric_share"] < 0.5 and 1 < entry["distinct"] <= max(3, int(0.02 * rows))
        and not str(column).lower().startswith(("note", "comment", "source_page", "source_table"))
    )
    mapping["numeric_optional"] = sorted(
        column for column, entry in report.items()
        if column not in (timestamp_column, entity_column, demand_column, entity_name_column)
        and entry["numeric_share"] >= 0.95 and column not in demand_scores
    )

    return {
        "rows": int(rows),
        "columns": report,
        "scores": {"timestamp": time_scores, "entity": entity_scores, "demand": demand_scores},
        "mapping": mapping,
        "ambiguous_demand_columns": ambiguous,
        "granularity": granularity,
        "timezone_requested": timezone,
        "unmapped_columns": sorted(column for column in report
                                   if column not in {timestamp_column, entity_column, demand_column, entity_name_column}
                                   | set(mapping["categorical"]) | set(mapping["numeric_optional"])),
    }


def measure_relations(frame: pd.DataFrame, candidates: list[str], *, tolerance: float = 0.15) -> dict[str, Any]:
    """Do two 'demand-like' columns add up to a third? Then they are not interchangeable."""
    numbers = frame[candidates].apply(pd.to_numeric, errors="coerce")
    findings: dict[str, Any] = {"sum_matches": [], "ratio_summary": {}}
    for first in candidates:
        for second in candidates:
            if first >= second:
                continue
            total = numbers[first] + numbers[second]
            for third in candidates:
                if third in (first, second):
                    continue
                reference = numbers[third]
                ok = float((abs(total - reference) / reference.replace(0, np.nan)).dropna().mean() if reference.notna().any() else 1.0)
                if ok <= tolerance:
                    findings["sum_matches"].append({"relation": f"{first} + {second} == {third}", "mean_relative_difference": round(ok, 4)})
    for column in candidates:
        reference = numbers.drop(columns=[column]).max(axis=1).replace(0, np.nan)
        ratio = (numbers[column] / reference).replace([np.inf, -np.inf], np.nan).dropna()
        if len(ratio):
            findings["ratio_summary"][column] = {
                "mean": round(float(ratio.mean()), 4), "min": round(float(ratio.min()), 4), "max": round(float(ratio.max()), 4),
                "interpretation": ("consistent with one counting event per journey" if 0.8 <= float(ratio.mean()) <= 1.25 else
                                   "roughly double, consistent with entries+exits" if 1.7 <= float(ratio.mean()) <= 2.3 else
                                   "no simple additive relation to the other measures"),
            }
    return findings


def profile_csv(path: "str | Path", **kwargs: Any) -> dict[str, Any]:
    frame = pd.read_csv(path)
    profile = profile_dataset(frame, **kwargs)
    profile["source_file"] = str(path)
    return profile
