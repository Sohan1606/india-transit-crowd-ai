"""Horizon validation and empirical forecast bands for the day-granularity trainer.

Two questions have to be answered from data before a product may project a date that has not
happened yet:

1. **How far can the projection be trusted?**  The champion is re-run the way the API runs it -
   recursively, re-feeding its own forecasts - over the *validation* partition, and the error is
   measured per horizon day. The largest day whose mean absolute error is still smaller than the
   dispersion of the values being predicted is the horizon at which a forecast still beats the
   trivial "predict the average" baseline; past that, a projection is not a forecast of anything.
2. **How wide is the plausible range at each horizon?**  From the same run: empirical quantiles of
   absolute error. These are honest residual bands, not a calibrated prediction interval - the
   response says so, and no confidence percentage is attached.

Only validation data is used here. The test partition stays untouched for the single final report,
so horizon policy is selected the same way the champion is.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

from ml.training.forecast import project_future


def horizon_bands(daily: pd.DataFrame, *, history: pd.DataFrame, predict_fn: Callable[[pd.DataFrame], float],
                  start: pd.Timestamp, end: pd.Timestamp, timezone: str = "Asia/Kolkata",
                  min_history_days: int = 28, entities: list[str] | None = None,
                  max_entities: int | None = None,
                  max_horizon: int = 45) -> dict[str, Any]:
    """Recursive multi-day projection error per horizon, measured on held-out validation days."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if max_horizon:
        end = min(end, start + pd.Timedelta(days=int(max_horizon) - 1))
    if end <= start:
        raise ValueError("Horizon validation needs a non-empty evaluation window.")
    observations = daily.loc[pd.to_datetime(daily["timestamp"]).between(start, end)]
    if observations.empty:
        raise ValueError("No observed target days fall inside the horizon-validation window.")
    truth = (observations.assign(timestamp=pd.to_datetime(observations["timestamp"]).dt.normalize())
             .groupby(["entity_id", "timestamp"])["demand_count"].last())
    reference = history.loc[pd.to_datetime(history["timestamp"]).dt.normalize() < start]
    dispersion = float(reference["demand_count"].astype(float).std())
    targets = truth.astype(float)
    target_dispersion = float(targets.std()) if len(targets) > 2 else dispersion
    rows: list[dict[str, float]] = []
    failures = 0
    universe = sorted(entities if entities is not None else truth.index.get_level_values(0).unique())
    # A family with two thousand entities does not need two thousand recursive projections to
    # establish how error grows with horizon; every tenth entity, evenly spaced, measures the same
    # curve - and the sample is reported so the evidence is never overstated.
    sampled = universe
    if max_entities is not None and len(universe) > int(max_entities):
        positions = np.linspace(0, len(universe) - 1, int(max_entities), dtype=int)
        sampled = sorted({universe[int(position)] for position in positions})
    entities_note = {"entities_total": len(universe), "entities_sampled": len(sampled)}
    for entity_id in sampled:
        entity_history = history.loc[history["entity_id"].astype(str).eq(str(entity_id))]
        if entity_history.empty:
            continue
        frontier = pd.Timestamp(pd.to_datetime(entity_history["timestamp"]).max())
        if pd.Timestamp(start) <= frontier.normalize():
            continue
        try:
            projected = project_future(entity_history, str(entity_id), predict_fn, start, end,
                                       timezone=timezone, min_history_days=min_history_days)
        except (ValueError, KeyError, AttributeError, IndexError):
            # A degenerate entity series must not abort horizon measurement; it is reported as
            # unprojectable so the shortfall is visible in the report.
            failures += 1
            continue
        for row in projected.to_dict("records"):
            forecast = row.get("forecast_demand")
            if forecast is None or pd.isna(forecast):
                failures += 1
                continue
            horizon = row.get("horizon_days")
            if horizon is None:
                continue
            key = (str(entity_id), pd.Timestamp(row["timestamp"]).normalize())
            if key not in truth.index:
                continue
            actual = float(truth.loc[key])
            rows.append({"entity_id": str(entity_id), "horizon_days": int(horizon),
                         "actual": actual, "forecast": float(forecast),
                         "absolute_error": abs(float(forecast) - actual),
                         "squared_error": (float(forecast) - actual) ** 2,
                         "relative_error": (abs(float(forecast) - actual) / actual if actual else np.nan)})
    if not rows:
        raise ValueError("The recursive projection produced no comparable (entity, day) pairs inside the window.")
    frame = pd.DataFrame(rows)
    per_horizon: dict[str, dict[str, Any]] = {}
    for horizon, part in frame.groupby("horizon_days"):
        errors = part["absolute_error"].to_numpy(dtype=float)
        relative = part["relative_error"].replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
        per_horizon[str(int(horizon))] = {
            "samples": int(len(part)),
            "mae": round(float(errors.mean()), 4),
            "rmse": round(float(np.sqrt((part["squared_error"].mean()))), 4),
            "median_absolute_error": round(float(np.median(errors)), 4),
            "p90_absolute_error": round(float(np.quantile(errors, 0.90)), 4),
            "p95_absolute_error": round(float(np.quantile(errors, 0.95)), 4),
            "p90_relative_error": round(float(np.quantile(relative, 0.90)), 4) if relative.size else None,
            "p95_relative_error": round(float(np.quantile(relative, 0.95)), 4) if relative.size else None,
        }
    horizons = sorted(int(key) for key in per_horizon)
    # A projection is only worth returning while its error stays below the spread of the values
    # themselves; beyond that point the model is reproducing the average, not the day.
    ceiling = target_dispersion if target_dispersion and np.isfinite(target_dispersion) else dispersion
    usable = 0
    for horizon in horizons:
        if per_horizon[str(horizon)]["mae"] <= ceiling:
            usable = horizon
        else:
            break
    return {
        "method": ("recursive multi-day-ahead projection re-feeding its own forecasts, evaluated on the validation "
                   "partition only; the same code path the API uses (ml.training.forecast.project_future)"),
        "evaluation_window": {"start": str(pd.Timestamp(start).date()), "end": str(end.date()),
                              "days": int((pd.Timestamp(end).normalize() - pd.Timestamp(start).normalize()).days + 1)},
        "evaluated_pairs": int(len(frame)), "entities": int(frame["entity_id"].nunique()),
        **({"entities_total": entities_note["entities_total"],
            "entities_sampled": entities_note["entities_sampled"]} if entities_note else {}),
        "entities_unprojectable": int(failures),
        "reference_dispersion": {
            "validation_target_standard_deviation": round(float(target_dispersion), 4) if np.isfinite(target_dispersion) else None,
            "history_standard_deviation": round(float(dispersion), 4) if np.isfinite(dispersion) else None,
            "rule": f"a horizon is serviceable while its MAE stays at or below {round(float(ceiling), 2)} (the spread of the values being predicted)",
        },
        "max_measured_horizon_days": max(horizons) if horizons else 0,
        "usable_horizon_days": int(usable),
        "per_horizon": per_horizons_sorted(per_horizon),
        "note": ("Quantiles are empirical absolute-error bands at each horizon, not a calibrated prediction interval. "
                 "Beyond max_measured_horizon_days the product reuses the widest measured band and labels the answer "
                 "beyond_validated_range; it never claims an accuracy it has not measured."),
    }


def per_horizons_sorted(per_horizon: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {key: per_horizon[key] for key in sorted(per_horizon, key=lambda value: int(value))}


__all__ = ["horizon_bands"]
