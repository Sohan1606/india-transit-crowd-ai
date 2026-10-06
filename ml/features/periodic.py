"""Period-aware, leakage-safe supervised features for any supported observation period.

This is the generic form of :mod:`ml.features.daily` and :mod:`ml.features.forecasting`:
the same construction rules expressed against a *period* instead of a hard-coded day or
hour, so a newly ingested dataset gets features at the resolution it actually has.

Rules kept identical to the production builders:

* rows are indexed by the TARGET period;
* every history column uses ``shift(k >= 1)`` or a rolling window that ends one period
  before the target, so nothing observed at the target period is visible as a feature;
* the series is reindexed onto a dense per-entity calendar grid *before* lagging, so a
  period the source skipped deletes the affected bridging rows instead of becoming a
  zero or a carry-forward value;
* an entity contributes nothing until it has ``min_history_periods`` of contiguous
  history.

At ``period_seconds == 86400`` the column names, lag set, window set and target name are
exactly those of :mod:`ml.features.daily`; a test asserts that equality, which is what
lets a new dataset reuse the same trained-family machinery without weakening it.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

ENTITY_COLUMN = "entity_id"
DEMAND_COLUMN = "demand_count"
SECONDS_PER_DAY = 86_400

#: Resolution labels the pipeline understands, and the period they mean.
PERIOD_SECONDS = {
    "5min": 300, "10min": 600, "15min": 900, "20min": 1200, "30min": 1800,
    "hour": 3600, "2hour": 7200, "3hour": 10800, "4hour": 14400, "6hour": 21600,
    "12hour": 43200, "day": SECONDS_PER_DAY, "week": 604_800,
}
#: Only periods at or above this are considered trainable by the adaptive path, because a
#: forecast is only as useful as the operator's ability to publish at that resolution.
MIN_SUPPORTED_PERIOD_SECONDS = 300
MAX_SUPPORTED_PERIOD_SECONDS = 604_800

_DAILY_TIME_FEATURES = ["day_of_week", "day_of_month", "month", "week_of_year", "is_weekend", "is_month_start"]


def normalize_granularity_label(period_seconds: int) -> str:
    for label, seconds in PERIOD_SECONDS.items():
        if seconds == int(period_seconds):
            return label
    return f"{int(period_seconds)}s"


def assert_no_future_features(frame: pd.DataFrame, *, period_seconds: int | None = None,
                              schema: dict[str, Any] | None = None) -> None:
    """The supervised frame must never carry the target inside its own feature list.

    Mirrors ``ml.features.daily.assert_no_future_features`` for arbitrary periods, so a
    newly registered dataset is guarded by the same invariant rather than a new one.
    """
    definition = schema or schema_for(int(period_seconds))  # type: ignore[arg-type]
    if definition["target"] in definition["feature_columns"]:
        raise AssertionError(f"Target leaked into the {definition['granularity']} feature columns.")
    if "origin_timestamp" in frame.columns:
        origin = pd.to_datetime(frame["origin_timestamp"])
        if (origin >= pd.to_datetime(frame["timestamp"])).any():
            raise AssertionError("Feature origin must be strictly earlier than the forecast target period.")


def target_name_for(period_seconds: int) -> str:
    label = normalize_granularity_label(int(period_seconds))
    if label == "day":
        return "target_next_day_demand"
    if label == "hour":
        return "target_next_hour_demand"
    if label == "week":
        return "target_next_week_demand"
    return f"target_next_{label}_demand"


def schema_for(period_seconds: int) -> dict[str, Any]:
    """Deterministic feature schema for one period, scaled so a week is always a week."""
    period = int(period_seconds)
    if not MIN_SUPPORTED_PERIOD_SECONDS <= period <= MAX_SUPPORTED_PERIOD_SECONDS:
        raise ValueError(
            f"Period {period}s is outside the supported range "
            f"({MIN_SUPPORTED_PERIOD_SECONDS}s-{MAX_SUPPORTED_PERIOD_SECONDS}s); the pipeline refuses to invent "
            "features for a resolution it cannot validate."
        )
    week = max(1, round(7 * SECONDS_PER_DAY / period))
    lags = sorted({1, week, 2 * week, 4 * week})
    windows = sorted({week, 4 * week})
    if period < SECONDS_PER_DAY:
        time_features = [*_DAILY_TIME_FEATURES, "period_of_day", "hour", "minute"]
    elif period == SECONDS_PER_DAY:
        time_features = list(_DAILY_TIME_FEATURES)
    else:
        time_features = ["day_of_week", "month", "week_of_year", "is_weekend"]
    history_features = [f"lag_{lag}" for lag in lags]
    for window in windows:
        history_features += [f"rolling_mean_{window}", f"rolling_std_{window}"]
    history_features += ["same_weekday_mean_4wk", f"trend_ratio_{windows[0]}_{windows[-1]}"]
    return {
        "period_seconds": period,
        "granularity": normalize_granularity_label(period),
        "periods_per_day": max(1, round(SECONDS_PER_DAY / period)),
        "periods_per_week": week,
        "lags": lags,
        "windows": windows,
        "min_history_periods": 4 * week,
        "time_features": time_features,
        "history_features": history_features,
        "feature_columns": [ENTITY_COLUMN, *time_features, *history_features],
        "target": target_name_for(period),
    }


def infer_period(stamps: pd.Series) -> tuple[int, dict[str, Any]]:
    """Detect the observation period from modal spacing, per entity, never from column names."""
    series = pd.to_datetime(pd.Series(stamps), errors="coerce").dropna().sort_values()
    if series.empty:
        raise ValueError("No parseable timestamps were found, so the observation period cannot be inferred.")
    deltas = series.diff().dropna()
    spacings = [int(seconds) for seconds in deltas.dt.total_seconds().round().tolist() if seconds > 0]
    if not spacings:
        raise ValueError("Fewer than two distinct timestamps exist, so no temporal ordering can be established.")
    counts = pd.Series(spacings).value_counts()
    modal = int(counts.index[0])
    modal_share = float(counts.iloc[0] / len(spacings))
    nearest = min(PERIOD_SECONDS.values(), key=lambda seconds: abs(seconds - modal))
    evidence = {
        "modal_spacing_seconds": modal,
        "modal_spacing_share": round(modal_share, 4),
        "snapped_to_seconds": int(nearest),
        "granularity": normalize_granularity_label(nearest),
        "distinct_spacings": int(counts.size),
        "median_spacing_seconds": int(pd.Series(spacings).median()),
    }
    if modal_share < 0.5:
        raise ValueError(
            f"Timestamps are irregular: the modal spacing is {modal}s but accounts for only "
            f"{modal_share:.0%} of gaps, so no single forecasting period can be claimed."
        )
    return int(nearest), evidence


def _calendar(index: pd.DatetimeIndex, time_features: list[str], period: int) -> pd.DataFrame:
    values = pd.DataFrame(index=index)
    for column in time_features:
        if column == "day_of_week":
            values[column] = index.dayofweek
        elif column == "day_of_month":
            values[column] = index.day
        elif column == "month":
            values[column] = index.month
        elif column == "week_of_year":
            values[column] = index.isocalendar().week.to_numpy(dtype=int)
        elif column == "is_weekend":
            values[column] = (index.dayofweek >= 5).astype(int)
        elif column == "is_month_start":
            values[column] = (index.day == 1).astype(int)
        elif column == "hour":
            values[column] = index.hour
        elif column == "minute":
            values[column] = index.minute
        elif column == "period_of_day":
            values[column] = ((index.hour * 3600 + index.minute * 60) // period).astype(int)
    return values


def _prepare(frame: pd.DataFrame, period: int, timezone: str, *, normalize: bool) -> pd.DataFrame:
    required = {"timestamp", ENTITY_COLUMN, DEMAND_COLUMN}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Demand input is missing columns: {missing}")
    data = frame.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce")
    if data["timestamp"].isna().any():
        raise ValueError("Every demand timestamp must be a valid datetime.")
    if data["timestamp"].dt.tz is None:
        data["timestamp"] = data["timestamp"].dt.tz_localize(timezone)
    else:
        data["timestamp"] = data["timestamp"].dt.tz_convert(timezone)
    if normalize or period >= SECONDS_PER_DAY:
        # Snap to the period grid in local wall-clock time: a source that publishes 00:07
        # IST is still daily data. Flooring must happen after the timezone conversion, or a
        # +05:30 offset would silently move every label back by one day.
        data["timestamp"] = data["timestamp"].dt.normalize() if period >= SECONDS_PER_DAY \
            else data["timestamp"].dt.floor(pd.Timedelta(seconds=period))
    data[ENTITY_COLUMN] = data[ENTITY_COLUMN].astype(str).str.strip()
    data[DEMAND_COLUMN] = pd.to_numeric(data[DEMAND_COLUMN], errors="coerce")
    data = data.dropna(subset=["timestamp", ENTITY_COLUMN, DEMAND_COLUMN])
    if (data[DEMAND_COLUMN] < 0).any():
        raise ValueError("Observed demand counts must be non-negative.")
    if data.duplicated([ENTITY_COLUMN, "timestamp"]).any():
        raise ValueError("Input must have one observed record per entity-period before feature generation.")
    return data


def build_supervised_frame(frame: pd.DataFrame, *, period_seconds: int | None = None,
                           timezone: str = "Asia/Kolkata", min_history_periods: int | None = None,
                           group_columns: list[str] | None = None) -> pd.DataFrame:
    """One row per (entity, target period) built only from strictly earlier observations."""
    if period_seconds is None:
        period_seconds, _ = infer_period(frame["timestamp"])
    schema = schema_for(int(period_seconds))
    period = int(schema["period_seconds"])
    needed = int(min_history_periods if min_history_periods is not None else schema["min_history_periods"])
    if needed < schema["min_history_periods"]:
        raise ValueError(
            f"This schema requires at least {schema['min_history_periods']} periods of history "
            f"(four weeks at {schema['granularity']} resolution)."
        )
    data = _prepare(frame, period, timezone, normalize=False)
    freq = pd.Timedelta(seconds=period)
    target = str(schema["target"])
    outputs: list[pd.DataFrame] = []
    for entity_id, raw_group in data.groupby(ENTITY_COLUMN, sort=True):
        group = raw_group.sort_values("timestamp", kind="stable")
        series = group.set_index("timestamp")[DEMAND_COLUMN].sort_index()
        series = series[~series.index.duplicated(keep="last")].astype(float)
        grid = pd.date_range(series.index.min(), series.index.max(), freq=freq)
        y = series.reindex(grid)
        if len(y) <= needed:
            continue
        feat = pd.DataFrame(index=y.index)
        for lag in schema["lags"]:
            feat[f"lag_{lag}"] = y.shift(lag)
        rolling_sources: dict[int, pd.Series] = {}
        for window in schema["windows"]:
            mean = y.rolling(window, min_periods=window).mean().shift(1)
            rolling_sources[window] = mean
            feat[f"rolling_mean_{window}"] = mean
            feat[f"rolling_std_{window}"] = y.rolling(window, min_periods=window).std(ddof=0).shift(1)
        feat["same_weekday_mean_4wk"] = pd.concat(
            [y.shift(schema["periods_per_week"] * k) for k in range(1, 5)], axis=1).mean(axis=1, skipna=False)
        small, large = rolling_sources[schema["windows"][0]], rolling_sources[schema["windows"][-1]]
        feat[f"trend_ratio_{schema['windows'][0]}_{schema['windows'][-1]}"] = small / large.replace(0, np.nan)
        for column in schema["time_features"]:
            feat[column] = _calendar(pd.DatetimeIndex(y.index), schema["time_features"], period)[column].to_numpy()
        feat[target] = y.to_numpy()
        feat[ENTITY_COLUMN] = str(entity_id)
        feat = feat.iloc[needed:]
        feat = feat.reset_index().rename(columns={"index": "timestamp"})
        for column in group_columns or []:
            if column in group.columns:
                feat[column] = group[column].iloc[0]
        outputs.append(feat)
    if not outputs:
        raise ValueError("No entity has enough contiguous history for supervised training at this period.")
    result = pd.concat(outputs, ignore_index=True)
    columns = list(schema["feature_columns"]) + [target]
    result = result.dropna(subset=columns)
    result = result.loc[result[target].ge(0)]
    if result.empty:
        raise ValueError("No supervised samples remain after requiring complete history at this period.")
    metadata_columns = [column for column in (group_columns or []) if column in result.columns]
    ordered = ["timestamp", *metadata_columns, *[column for column in columns]]
    return result[ordered].sort_values(["timestamp", ENTITY_COLUMN], kind="stable").reset_index(drop=True)


def features_for_target(history: pd.DataFrame, entity_id: str, target_timestamp: pd.Timestamp, *,
                        period_seconds: int, timezone: str = "Asia/Kolkata") -> pd.DataFrame:
    """Exactly one inference row for ``target_timestamp`` from earlier observations only."""
    schema = schema_for(int(period_seconds))
    period = int(schema["period_seconds"])
    freq = pd.Timedelta(seconds=period)
    needed = int(schema["min_history_periods"])
    target = pd.Timestamp(target_timestamp)
    target = target.tz_localize(timezone) if target.tzinfo is None else target.tz_convert(timezone)
    target = target.normalize() if period >= SECONDS_PER_DAY else target.floor(pd.Timedelta(seconds=period))
    normalized_id = str(entity_id).strip()
    before = history.loc[history[ENTITY_COLUMN].astype(str).eq(normalized_id)].copy()
    if before.empty:
        raise ValueError(f"No historical demand is available for {normalized_id}.")
    prepared = _prepare(before, period, timezone, normalize=False)
    prepared = prepared.loc[prepared["timestamp"] < target]
    if prepared["timestamp"].duplicated().any():
        raise ValueError(f"Duplicate observed periods exist for {normalized_id}; aggregate explicitly before inference.")
    series = prepared.set_index("timestamp")[DEMAND_COLUMN].sort_index().astype(float)
    origin = target - freq
    if series.empty or series.index.max() != origin:
        raise ValueError(
            f"Insufficient contiguous history: {normalized_id} has no observation at {origin}, the period "
            "immediately before the requested target."
        )
    grid = pd.date_range(end=origin, periods=needed, freq=freq)
    past = series.reindex(grid)
    if past.isna().any():
        raise ValueError(f"Insufficient contiguous {needed}-period history for {normalized_id} before {target}.")
    values = past.to_numpy(dtype=float)
    row: dict[str, Any] = {ENTITY_COLUMN: normalized_id, "timestamp": target}
    for lag in schema["lags"]:
        row[f"lag_{lag}"] = float(values[-lag])
    for window in schema["windows"]:
        block = values[-window:]
        row[f"rolling_mean_{window}"] = float(np.mean(block))
        row[f"rolling_std_{window}"] = float(np.std(block, ddof=0))
    week = int(schema["periods_per_week"])
    row["same_weekday_mean_4wk"] = float(np.mean([values[-week * k] for k in range(1, 5)]))
    small = row[f"rolling_mean_{schema['windows'][0]}"]
    large = row[f"rolling_mean_{schema['windows'][-1]}"]
    row[f"trend_ratio_{schema['windows'][0]}_{schema['windows'][-1]}"] = small / large if large else np.nan
    calendar = _calendar(pd.DatetimeIndex([target]), schema["time_features"], period).iloc[0]
    row.update({column: int(calendar[column]) for column in schema["time_features"]})
    return pd.DataFrame([[row[column] for column in ["timestamp", *schema["feature_columns"]]]],
                        columns=["timestamp", *schema["feature_columns"]])
