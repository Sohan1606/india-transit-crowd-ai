"""Leakage-safe one-hour-ahead feature generation for canonical entity-hour demand."""
from __future__ import annotations
from typing import Iterable
import numpy as np
import pandas as pd

from ml.data_pipeline.source import BMRCL_TIMEZONE

TARGET = "target_next_hour_demand"
ENTITY_COLUMN = "entity_id"
DEMAND_COLUMN = "demand_count"
TIME_FEATURES = ["hour", "day_of_week", "day_of_month", "month", "week_of_year", "is_weekend", "is_peak_hour"]
HISTORY_FEATURES = [
    "lag_1", "lag_24", "lag_168", "rolling_mean_3", "rolling_mean_24", "rolling_mean_168",
    "rolling_std_24", "rolling_std_168", "same_hour_previous_day", "same_hour_previous_week",
]
FEATURE_COLUMNS = [ENTITY_COLUMN, *TIME_FEATURES, *HISTORY_FEATURES]
GROUP_COLUMNS = ["system_id", "city", "mode", "operator", "entity_name", "entity_type", "measure", "source_id"]


def _local_timestamp(value: object, timezone: str = BMRCL_TIMEZONE) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize(timezone) if timestamp.tzinfo is None else timestamp.tz_convert(timezone)


def _calendar_features(target_timestamps: pd.DatetimeIndex) -> pd.DataFrame:
    values = pd.DataFrame(index=target_timestamps)
    values["hour"] = target_timestamps.hour
    values["day_of_week"] = target_timestamps.dayofweek
    values["day_of_month"] = target_timestamps.day
    values["month"] = target_timestamps.month
    values["week_of_year"] = target_timestamps.isocalendar().week.to_numpy(dtype=int)
    values["is_weekend"] = (target_timestamps.dayofweek >= 5).astype(int)
    values["is_peak_hour"] = (
        (target_timestamps.dayofweek < 5)
        & (((target_timestamps.hour >= 7) & (target_timestamps.hour <= 10))
           | ((target_timestamps.hour >= 16) & (target_timestamps.hour <= 19)))
    ).astype(int)
    return values


def _entity_hourly_series(group: pd.DataFrame) -> pd.Series:
    series = group.set_index("timestamp")[DEMAND_COLUMN].sort_index()
    # Missing source timestamps remain NaN; observed zero counts remain zero.
    grid = pd.date_range(series.index.min(), series.index.max(), freq="h")
    return series.reindex(grid).astype(float)


def build_supervised_frame(hourly: pd.DataFrame, min_history_hours: int = 168,
                           timezone: str = BMRCL_TIMEZONE) -> pd.DataFrame:
    """Build features available before target T; predict an observed count at T.

    The origin is T−1 hour. Calendar features describe T; all demand history is
    strictly before T. Missing source-hours are exposed by reindexing and cause
    affected training windows to be dropped rather than bridged or zero-filled.
    """
    required = {"timestamp", ENTITY_COLUMN, DEMAND_COLUMN}
    if not required.issubset(hourly.columns):
        raise ValueError(f"Demand input must contain columns: {sorted(required)}")
    if min_history_hours < 168:
        raise ValueError("The requested feature schema requires at least 168 history hours.")
    data = hourly.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce")
    if data["timestamp"].isna().any():
        raise ValueError("Demand timestamps must be valid.")
    if data["timestamp"].dt.tz is None:
        data["timestamp"] = data["timestamp"].dt.tz_localize(timezone)
    else:
        data["timestamp"] = data["timestamp"].dt.tz_convert(timezone)
    data[ENTITY_COLUMN] = data[ENTITY_COLUMN].astype(str).str.strip()
    data[DEMAND_COLUMN] = pd.to_numeric(data[DEMAND_COLUMN], errors="coerce")
    data = data.dropna(subset=["timestamp", ENTITY_COLUMN, DEMAND_COLUMN])
    if (data[DEMAND_COLUMN] < 0).any():
        raise ValueError("Observed demand counts must be non-negative.")
    if data.duplicated([ENTITY_COLUMN, "timestamp"]).any():
        raise ValueError("Input must have one observed record per entity-hour before feature generation.")

    outputs: list[pd.DataFrame] = []
    for entity_id, raw_group in data.groupby(ENTITY_COLUMN, sort=True):
        group = raw_group.sort_values("timestamp", kind="stable")
        y = _entity_hourly_series(group)
        target_index = y.index + pd.Timedelta(hours=1)
        feat = _calendar_features(target_index)
        feat[ENTITY_COLUMN] = str(entity_id)
        feat["lag_1"] = y.to_numpy()
        feat["lag_24"] = y.shift(23).to_numpy()
        feat["lag_168"] = y.shift(167).to_numpy()
        feat["rolling_mean_3"] = y.rolling(3, min_periods=3).mean().to_numpy()
        feat["rolling_mean_24"] = y.rolling(24, min_periods=24).mean().to_numpy()
        feat["rolling_mean_168"] = y.rolling(168, min_periods=168).mean().to_numpy()
        feat["rolling_std_24"] = y.rolling(24, min_periods=24).std(ddof=0).to_numpy()
        feat["rolling_std_168"] = y.rolling(168, min_periods=168).std(ddof=0).to_numpy()
        feat["same_hour_previous_day"] = y.shift(23).to_numpy()
        feat["same_hour_previous_week"] = y.shift(167).to_numpy()
        feat["timestamp"] = target_index
        feat[TARGET] = y.shift(-1).to_numpy()
        for column in GROUP_COLUMNS:
            if column in group.columns:
                feat[column] = group[column].iloc[0]
        outputs.append(feat.reset_index(drop=True))

    if not outputs:
        raise ValueError("No entities were available for supervised feature generation.")
    result = pd.concat(outputs, ignore_index=True)
    result = result.dropna(subset=[*FEATURE_COLUMNS, TARGET])
    result = result.loc[result[TARGET].ge(0)].copy()
    result = result.sort_values(["timestamp", ENTITY_COLUMN], kind="stable").reset_index(drop=True)
    if result.empty:
        raise ValueError("No supervised samples remain after requiring complete hourly history.")
    metadata_columns = [column for column in GROUP_COLUMNS if column in result.columns]
    return result[["timestamp", *metadata_columns, ENTITY_COLUMN, *FEATURE_COLUMNS[1:], TARGET]]


def features_for_target(history: pd.DataFrame, entity_id: str, target_timestamp: pd.Timestamp,
                        timezone: str = BMRCL_TIMEZONE) -> pd.DataFrame:
    """Create one inference row from observations strictly before target T."""
    target = _local_timestamp(target_timestamp, timezone).floor("h")
    normalized_id = str(entity_id).strip()
    before = history.loc[history[ENTITY_COLUMN].astype(str).eq(normalized_id)].copy()
    before["timestamp"] = pd.to_datetime(before["timestamp"], errors="coerce")
    if before["timestamp"].dt.tz is None:
        before["timestamp"] = before["timestamp"].dt.tz_localize(timezone)
    else:
        before["timestamp"] = before["timestamp"].dt.tz_convert(timezone)
    before[DEMAND_COLUMN] = pd.to_numeric(before[DEMAND_COLUMN], errors="coerce")
    before = before.loc[before["timestamp"] < target, ["timestamp", ENTITY_COLUMN, DEMAND_COLUMN]]
    before = before.dropna(subset=["timestamp", DEMAND_COLUMN])
    if before.empty:
        raise ValueError(f"No historical demand is available for {normalized_id} before {target}.")
    before = before.sort_values("timestamp", kind="stable")
    if before["timestamp"].duplicated().any():
        raise ValueError(f"Duplicate observed hours are present for {normalized_id}; aggregate explicitly before inference.")
    origin = target - pd.Timedelta(hours=1)
    route_data = before.loc[before["timestamp"] <= origin]
    if route_data.empty or route_data["timestamp"].max() != origin:
        raise ValueError(f"Insufficient contiguous history: {normalized_id} has no observation at {origin}.")
    observed = route_data.set_index("timestamp")[DEMAND_COLUMN].sort_index()
    grid = pd.date_range(end=origin, periods=168, freq="h")
    past = observed.reindex(grid)
    if past.isna().any():
        raise ValueError(f"Insufficient contiguous 168-hour history for {normalized_id} before {target}.")
    calendar = _calendar_features(pd.DatetimeIndex([target]))
    row: dict[str, object] = {ENTITY_COLUMN: normalized_id}
    row.update({column: calendar.iloc[0][column] for column in TIME_FEATURES})
    values = past.to_numpy(dtype=float)
    row.update({
        "lag_1": values[-1],
        "lag_24": values[-24],
        "lag_168": values[0],
        "rolling_mean_3": float(np.mean(values[-3:])),
        "rolling_mean_24": float(np.mean(values[-24:])),
        "rolling_mean_168": float(np.mean(values)),
        "rolling_std_24": float(np.std(values[-24:], ddof=0)),
        "rolling_std_168": float(np.std(values, ddof=0)),
        "same_hour_previous_day": values[-24],
        "same_hour_previous_week": values[-168],
        "timestamp": target,
    })
    return pd.DataFrame([row], columns=["timestamp", *FEATURE_COLUMNS])


def assert_no_future_features(frame: pd.DataFrame) -> None:
    if "origin_timestamp" in frame.columns:
        origin = pd.to_datetime(frame["origin_timestamp"])
        target = pd.to_datetime(frame["timestamp"])
        if (origin >= target).any():
            raise AssertionError("Feature origin must be strictly earlier than forecast target.")
    if TARGET in FEATURE_COLUMNS:
        raise AssertionError("Target leaked into model feature columns.")
    if any(column not in FEATURE_COLUMNS for column in FEATURE_COLUMNS):
        raise AssertionError("Feature schema is internally inconsistent.")
