"""Validation for source-adapter normalized transit-demand records.

Rows are observations, never schedule rows. This function deliberately does
not fill missing station-hours or reinterpret absent records as zero.
"""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd
from pandas.api.types import is_datetime64_any_dtype

from ml.data_pipeline.source import BMRCL_TIMEZONE, CANONICAL_COLUMNS


class DataValidationError(ValueError):
    """Raised when normalized records violate the shared demand-data contract."""


def clean_normalized_demand(frame: pd.DataFrame, timezone: str = BMRCL_TIMEZONE,
                            period_seconds: int = 3600) -> tuple[pd.DataFrame, dict[str, Any]]:
    if frame.empty:
        raise DataValidationError("Normalized demand input is empty.")
    missing_columns = set(CANONICAL_COLUMNS) - set(frame.columns)
    if missing_columns:
        raise DataValidationError(f"Normalized schema mismatch; missing columns: {sorted(missing_columns)}")

    data = frame[CANONICAL_COLUMNS].copy()
    string_columns = ["system_id", "city", "mode", "operator", "entity_id", "entity_name", "entity_type", "measure", "source_id"]
    for column in string_columns:
        data[column] = data[column].astype("string").str.strip()
    numeric = pd.to_numeric(data["demand_count"], errors="coerce")
    parsed = pd.to_datetime(data["timestamp"], errors="coerce")
    if is_datetime64_any_dtype(parsed.dtype) and parsed.dt.tz is not None:
        parsed = parsed.dt.tz_convert(timezone)
    elif is_datetime64_any_dtype(parsed.dtype):
        parsed = parsed.dt.tz_localize(timezone)
    else:
        raise DataValidationError("Timestamps must use one consistent local timezone or be naive local clock values.")

    invalid = parsed.isna() | numeric.isna() | ~np.isfinite(numeric.astype(float))
    for column in string_columns:
        invalid |= data[column].isna() | data[column].eq("")
    if invalid.any():
        raise DataValidationError(f"Normalized records contain {int(invalid.sum())} invalid or missing required values.")
    if numeric.lt(0).any():
        raise DataValidationError("Observed passenger-demand counts must be non-negative.")
    if (numeric % 1 != 0).any():
        raise DataValidationError("Observed station-hour demand must be a whole count.")
    if period_seconds % 3600 == 0:
        # Hour-aligned (which also covers day-aligned frames stamped at 00:00).
        misaligned = ((parsed.dt.minute != 0) | (parsed.dt.second != 0) | (parsed.dt.microsecond != 0))
        unit = "the start of a clock hour"
    else:
        step = pd.Timedelta(seconds=int(period_seconds))
        misaligned = parsed.dt.floor(step).ne(parsed)
        unit = f"the start of a {int(period_seconds)}-second period"
    if bool(misaligned.any()):
        raise DataValidationError(
            f"Station demand timestamps must be aligned to {unit}; {int(misaligned.sum())} row(s) are not."
        )

    data["timestamp"] = parsed
    data["demand_count"] = numeric.astype(float)
    if data["system_id"].nunique() != 1:
        raise DataValidationError("Train one mode/operator system family at a time; mixed system IDs are not supported.")
    if data["city"].nunique() != 1 or data["mode"].nunique() != 1 or data["operator"].nunique() != 1:
        raise DataValidationError("A model-family dataset must have one city, mode and operator.")
    if data["entity_type"].nunique() != 1:
        raise DataValidationError("A model-family dataset must use one entity type (for example, STATION).")
    if data.duplicated(["system_id", "entity_id", "timestamp"]).any():
        raise DataValidationError("Duplicate entity-hour keys are not allowed; source aggregation must be explicit.")

    data = data.sort_values(["entity_id", "timestamp"], kind="stable").reset_index(drop=True)
    report = {
        "rows_in": int(len(frame)),
        "rows_out": int(len(data)),
        "system_id": str(data["system_id"].iloc[0]),
        "entity_count": int(data["entity_id"].nunique()),
        "timestamp_min": data["timestamp"].min().isoformat(),
        "timestamp_max": data["timestamp"].max().isoformat(),
        "explicit_zero_observations": int(data["demand_count"].eq(0).sum()),
        "missing_observations_filled": 0,
        "timezone": timezone,
    }
    return data, report


# Compatibility alias for earlier callers; current records are normalized by source adapters.
clean_and_aggregate = clean_normalized_demand
