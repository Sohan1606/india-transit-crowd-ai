"""Recursive multi-day-ahead projection used by both evaluation and inference.

The projection consumes only observations at or before the projection origin; days
beyond the data frontier are produced by repeated one-day-ahead model calls. The
generated values are forecasts used as *features for the next step*; they are never
written back as training labels, and callers must present them as model forecasts.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from ml.features.daily import FEATURE_COLUMNS, features_for_target


def project_future(history: pd.DataFrame, entity_id: str, predict_fn: Callable[[pd.DataFrame], float],
                   first_day: pd.Timestamp, last_day: pd.Timestamp, timezone: str = "Asia/Kolkata",
                   min_history_days: int = 28) -> pd.DataFrame:
    """Project ``first_day..last_day`` for one entity from observations only before each step."""
    working = history.loc[history["entity_id"].astype(str).eq(str(entity_id)), ["timestamp", "entity_id", "demand_count"]].copy()
    working["timestamp"] = pd.to_datetime(working["timestamp"]).dt.normalize()
    frontier = pd.Timestamp(working["timestamp"].max())
    if pd.Timestamp(first_day) <= frontier:
        raise ValueError("project_future must start after the last available observation for the entity.")
    # A caller may hand over a date stamped with the named zone while the series carries a
    # fixed offset. They denote the same wall clock, so the projection is built from naive
    # days re-stamped with the data's own tzinfo: pandas refuses to range across two zone
    # representations, and converting instead of re-stamping could shift the horizon.
    zone = frontier.tzinfo

    def as_data_day(value) -> pd.Timestamp:
        stamp = pd.Timestamp(value)
        naive = stamp.tz_localize(None) if stamp.tzinfo is not None else stamp
        normalized = pd.Timestamp(naive).normalize()
        return normalized.tz_localize(zone) if zone is not None else normalized

    rows: list[dict[str, object]] = []
    for target in pd.date_range(as_data_day(first_day), as_data_day(last_day), freq="D"):
        try:
            features = features_for_target(working, entity_id, target, timezone=timezone,
                                           min_history_days=min_history_days)
        except ValueError as exc:
            rows.append({"timestamp": target, "entity_id": str(entity_id),
                         "forecast_error": str(exc), "forecast_demand": None})
            continue
        demand = float(max(predict_fn(features[FEATURE_COLUMNS]), 0.0))
        rows.append({"timestamp": target, "entity_id": str(entity_id),
                     "forecast_demand": demand, "origin_timestamp": frontier,
                     "horizon_days": int((target.normalize() - frontier.normalize()).days),
                     "_features": features})
        working = pd.concat([working, pd.DataFrame([{"timestamp": target, "entity_id": str(entity_id),
                                                    "demand_count": demand}])], ignore_index=True)
    return pd.DataFrame(rows)
