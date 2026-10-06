"""Leakage-safe one-day-ahead features for canonical entity-day demand.

The day-granularity counterpart of :mod:`ml.features.forecasting`. Every demand
history feature for a target day T is computed only from observations strictly
before T (latest allowed origin is T-1 day), and an entity-day window is dropped
rather than bridged when the source is missing a day.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

TARGET = "target_next_day_demand"
ENTITY_COLUMN = "entity_id"
DEMAND_COLUMN = "demand_count"
TIME_FEATURES = ["day_of_week", "day_of_month", "month", "week_of_year", "is_weekend", "is_month_start"]
HISTORY_FEATURES = [
    "lag_1", "lag_7", "lag_14", "lag_28",
    "rolling_mean_7", "rolling_mean_28", "rolling_std_7", "rolling_std_28",
    "same_weekday_mean_4wk", "trend_ratio_7_28",
]
FEATURE_COLUMNS = [ENTITY_COLUMN, *TIME_FEATURES, *HISTORY_FEATURES]
MIN_HISTORY_DAYS = 28
GROUP_COLUMNS = ["system_id", "city", "mode", "operator", "entity_name", "entity_type", "measure", "source_id"]


def _calendar(index: pd.DatetimeIndex) -> pd.DataFrame:
    values = pd.DataFrame(index=index)
    values["day_of_week"] = index.dayofweek
    values["day_of_month"] = index.day
    values["month"] = index.month
    values["week_of_year"] = index.isocalendar().week.to_numpy(dtype=int)
    values["is_weekend"] = (index.dayofweek >= 5).astype(int)
    values["is_month_start"] = (index.day == 1).astype(int)
    return values


def _entity_daily_series(group: pd.DataFrame) -> pd.Series:
    series = group.set_index("timestamp")[DEMAND_COLUMN].sort_index()
    series = series[~series.index.duplicated(keep="last")]
    grid = pd.date_range(series.index.min(), series.index.max(), freq="D")
    return series.reindex(grid).astype(float)


def build_supervised_frame(daily: pd.DataFrame, min_history_days: int = MIN_HISTORY_DAYS,
                           timezone: str = "Asia/Kolkata") -> pd.DataFrame:
    """One row per (entity, target day) using only strictly earlier observations."""
    required = {"timestamp", ENTITY_COLUMN, DEMAND_COLUMN}
    if not required.issubset(daily.columns):
        raise ValueError(f"Demand input must contain columns: {sorted(required)}")
    if min_history_days < MIN_HISTORY_DAYS:
        raise ValueError(f"The daily feature schema requires at least {MIN_HISTORY_DAYS} days of history.")
    data = daily.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce").dt.normalize()
    if data["timestamp"].isna().any():
        raise ValueError("Demand timestamps must be valid dates.")
    if data["timestamp"].dt.tz is None:
        data["timestamp"] = data["timestamp"].dt.tz_localize(timezone)
    else:
        data["timestamp"] = data["timestamp"].dt.tz_convert(timezone).dt.normalize()
    data[ENTITY_COLUMN] = data[ENTITY_COLUMN].astype(str).str.strip()
    data[DEMAND_COLUMN] = pd.to_numeric(data[DEMAND_COLUMN], errors="coerce")
    data = data.dropna(subset=["timestamp", ENTITY_COLUMN, DEMAND_COLUMN])
    if (data[DEMAND_COLUMN] < 0).any():
        raise ValueError("Observed demand counts must be non-negative.")
    if data.duplicated([ENTITY_COLUMN, "timestamp"]).any():
        raise ValueError("Input must have one observed record per entity-day before feature generation.")

    outputs: list[pd.DataFrame] = []
    for entity_id, raw_group in data.groupby(ENTITY_COLUMN, sort=True):
        group = raw_group.sort_values("timestamp", kind="stable")
        y = _entity_daily_series(group)
        if len(y) <= min_history_days:
            continue
        # Rows are indexed by the TARGET day. Every history column therefore uses
        # shift(k>=1) or a rolling window that ends the day before the target, so
        # nothing on target day T is visible to the model.
        feat = pd.DataFrame(index=y.index)
        for lag in (1, 7, 14, 28):
            feat[f"lag_{lag}"] = y.shift(lag)
        mean7 = y.rolling(7, min_periods=7).mean().shift(1)
        mean28 = y.rolling(28, min_periods=28).mean().shift(1)
        feat["rolling_mean_7"], feat["rolling_mean_28"] = mean7, mean28
        feat["rolling_std_7"] = y.rolling(7, min_periods=7).std(ddof=0).shift(1)
        feat["rolling_std_28"] = y.rolling(28, min_periods=28).std(ddof=0).shift(1)
        feat["same_weekday_mean_4wk"] = pd.concat(
            [y.shift(7 * k) for k in range(1, 5)], axis=1).mean(axis=1, skipna=False)
        feat["trend_ratio_7_28"] = mean7 / mean28.replace(0, np.nan)
        for column in TIME_FEATURES:
            feat[column] = _calendar(pd.DatetimeIndex(y.index))[column].to_numpy()
        feat[TARGET] = y.to_numpy()
        feat[ENTITY_COLUMN] = str(entity_id)
        feat = feat.iloc[min_history_days:]
        feat = feat.reset_index().rename(columns={"index": "timestamp"})
        for column in GROUP_COLUMNS:
            if column in group.columns:
                feat[column] = group[column].iloc[0]
        outputs.append(feat)
    if not outputs:
        raise ValueError("No entities have enough contiguous daily history for supervised training.")
    result = pd.concat(outputs, ignore_index=True)
    result = result.dropna(subset=[*FEATURE_COLUMNS, TARGET])
    result = result.loc[result[TARGET].ge(0)]
    if result.empty:
        raise ValueError("No supervised samples remain after requiring complete daily history.")
    metadata_columns = [column for column in GROUP_COLUMNS if column in result.columns]
    columns = ["timestamp", *metadata_columns, ENTITY_COLUMN, *[c for c in FEATURE_COLUMNS if c != ENTITY_COLUMN], TARGET]
    return result[columns].sort_values(["timestamp", ENTITY_COLUMN], kind="stable").reset_index(drop=True)


def features_for_target(history: pd.DataFrame, entity_id: str, target_date: pd.Timestamp,
                        timezone: str = "Asia/Kolkata",
                        min_history_days: int = MIN_HISTORY_DAYS) -> pd.DataFrame:
    """Build exactly one inference row for ``target_date`` from earlier observations."""
    target = pd.Timestamp(target_date)
    target = target.tz_localize(timezone) if target.tzinfo is None else target.tz_convert(timezone)
    target = target.normalize()
    normalized_id = str(entity_id).strip()
    before = history.loc[history[ENTITY_COLUMN].astype(str).eq(normalized_id)].copy()
    if before.empty:
        raise ValueError(f"No historical demand is available for {normalized_id}.")
    before["timestamp"] = pd.to_datetime(before["timestamp"], errors="coerce").dt.normalize()
    if before["timestamp"].dt.tz is None:
        before["timestamp"] = before["timestamp"].dt.tz_localize(timezone)
    else:
        before["timestamp"] = before["timestamp"].dt.tz_convert(timezone).dt.normalize()
    before[DEMAND_COLUMN] = pd.to_numeric(before[DEMAND_COLUMN], errors="coerce")
    before = before.loc[before["timestamp"] < target, ["timestamp", ENTITY_COLUMN, DEMAND_COLUMN]]
    before = before.dropna(subset=["timestamp", DEMAND_COLUMN]).sort_values("timestamp", kind="stable")
    if before["timestamp"].duplicated().any():
        raise ValueError(f"Duplicate observed days are present for {normalized_id}; aggregate explicitly before inference.")
    origin = target - pd.Timedelta(days=1)
    if before.empty or before["timestamp"].max() != origin:
        raise ValueError(
            f"Insufficient contiguous history: {normalized_id} has no observation at {origin.date()}, the day "
            "immediately before the requested target."
        )
    series = before.set_index("timestamp")[DEMAND_COLUMN].sort_index()
    grid = pd.date_range(end=origin, periods=min_history_days, freq="D")
    past = series.reindex(grid)
    if past.isna().any():
        raise ValueError(f"Insufficient contiguous {min_history_days}-day history for {normalized_id} before {target.date()}.")
    values = past.to_numpy(dtype=float)
    mean7, mean28 = float(np.mean(values[-7:])), float(np.mean(values))
    same_weekday = float(np.mean([values[-7 * k] for k in range(1, 5)]))
    row: dict[str, object] = {ENTITY_COLUMN: normalized_id}
    row.update({column: _calendar(pd.DatetimeIndex([target])).iloc[0][column] for column in TIME_FEATURES})
    row.update({
        "lag_1": float(values[-1]), "lag_7": float(values[-7]),
        "lag_14": float(values[-14]), "lag_28": float(values[0]),
        "rolling_mean_7": mean7, "rolling_mean_28": mean28,
        "rolling_std_7": float(np.std(values[-7:], ddof=0)), "rolling_std_28": float(np.std(values, ddof=0)),
        "same_weekday_mean_4wk": same_weekday,
        "trend_ratio_7_28": mean7 / mean28 if mean28 else np.nan,
        "timestamp": target,
    })
    return pd.DataFrame([row], columns=["timestamp", *FEATURE_COLUMNS])


def assert_no_future_features(frame: pd.DataFrame) -> None:
    if TARGET in FEATURE_COLUMNS:
        raise AssertionError("Target leaked into the daily model feature columns.")
    if "origin_timestamp" in frame.columns:
        origin = pd.to_datetime(frame["origin_timestamp"])
        if (origin >= pd.to_datetime(frame["timestamp"])).any():
            raise AssertionError("Feature origin must be strictly earlier than the forecast target day.")
