"""Frozen, training-only historical-relative demand risk thresholds."""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd

RISK_ORDER = ["LOW", "MODERATE", "HIGH", "SEVERE"]
MIN_ENTITY_TRAIN_TARGETS = 500
MIN_SYSTEM_TRAIN_TARGETS = 500


def _quantiles(values: pd.Series | np.ndarray) -> dict[str, Any]:
    clean = pd.to_numeric(pd.Series(values), errors="coerce").dropna().to_numpy(float)
    q50, q80, q95 = np.quantile(clean, [0.50, 0.80, 0.95]).astype(float).tolist()
    return {"q50": q50, "q80": q80, "q95": q95, "sample_count": int(len(clean))}


def fit_risk_thresholds(train: pd.DataFrame, min_entity_targets: int = MIN_ENTITY_TRAIN_TARGETS,
                         min_system_targets: int = MIN_SYSTEM_TRAIN_TARGETS,
                         target_column: str = "target_next_hour_demand") -> dict[str, Any]:
    """Fit entity cuts, then city/mode/operator system cuts, then global cuts.

    All values are estimated exclusively from the chronological training
    partition. The returned maps are frozen before validation/test inference.
    """
    required = {"entity_id", target_column}
    if not required.issubset(train.columns):
        raise ValueError(f"Training data must contain {sorted(required)}.")
    values = pd.to_numeric(train[target_column], errors="coerce").dropna().to_numpy(float)
    if not len(values):
        raise ValueError("Cannot fit historical-relative demand thresholds without training targets.")
    global_thresholds = _quantiles(values)
    systems: dict[str, dict[str, Any]] = {}
    system_col = "system_id" if "system_id" in train.columns else None
    if system_col:
        for system_id, part in train.groupby(system_col, sort=True):
            fitted = _quantiles(part[target_column])
            source = "system_training_distribution" if fitted["sample_count"] >= min_system_targets else "global_training_fallback"
            systems[str(system_id)] = {**(fitted if source == "system_training_distribution" else global_thresholds), "source": source}

    entities: dict[str, dict[str, Any]] = {}
    for entity_id, part in train.groupby("entity_id", sort=True):
        fitted = _quantiles(part[target_column])
        if fitted["sample_count"] >= min_entity_targets:
            entities[str(entity_id)] = {**fitted, "source": "entity_training_distribution"}
            continue
        system_id = str(part[system_col].iloc[0]) if system_col else ""
        fallback = systems.get(system_id, {**global_thresholds, "source": "global_training_fallback"})
        source = "system_training_fallback" if fallback.get("source") == "system_training_distribution" else "global_training_fallback"
        entities[str(entity_id)] = {**fallback, "source": source, "entity_sample_count": fitted["sample_count"]}

    return {
        "method": "Historical-relative q50/q80/q95, fit on the chronological training targets only: entity when adequately sampled, then its city/mode/operator system, then global.",
        "definitions": {
            "LOW": "demand <= q50",
            "MODERATE": "q50 < demand <= q80",
            "HIGH": "q80 < demand <= q95",
            "SEVERE": "demand > q95",
        },
        "minimum_entity_training_targets": int(min_entity_targets),
        "minimum_system_training_targets": int(min_system_targets),
        "global": global_thresholds,
        "systems": systems,
        "entities": entities,
        "fitted_on": "training partition only; frozen before validation/test/production inference",
    }


def resolve_thresholds(entity_id: str, system_id: str, thresholds: dict[str, Any]) -> tuple[dict[str, Any], str]:
    entity = thresholds.get("entities", {}).get(str(entity_id))
    if entity and entity.get("source") == "entity_training_distribution":
        return entity, "entity_training_distribution"
    system = thresholds.get("systems", {}).get(str(system_id))
    if system and system.get("source") == "system_training_distribution":
        return system, "system_training_fallback"
    global_thresholds = thresholds["global"]
    return global_thresholds, "global_training_fallback"


def classify_demand(demand: float, entity_id: str, system_id: str, thresholds: dict[str, Any]) -> tuple[str, str]:
    cuts, source = resolve_thresholds(entity_id, system_id, thresholds)
    if demand <= cuts["q50"]:
        label = "LOW"
    elif demand <= cuts["q80"]:
        label = "MODERATE"
    elif demand <= cuts["q95"]:
        label = "HIGH"
    else:
        label = "SEVERE"
    return label, source


def historical_percentile(demand: float, entity_id: str, system_id: str,
                          training_distributions: dict[str, list[float]]) -> float:
    values = training_distributions.get(f"entity:{entity_id}")
    if not values:
        values = training_distributions.get(f"system:{system_id}")
    if not values:
        values = training_distributions.get("__global__", [])
    if not values:
        return float("nan")
    sorted_values = np.asarray(values, dtype=float)
    lo = int(np.searchsorted(sorted_values, demand, side="left"))
    hi = int(np.searchsorted(sorted_values, demand, side="right"))
    return round(100.0 * ((lo + hi) / 2) / len(sorted_values), 1)
