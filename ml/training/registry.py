"""Explicit mode/operator model-family registry.

A model family is added only after an observed-demand source adapter and its
licensing/provenance have been verified. Schedule feeds do not register here.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any

from ml.data_pipeline.source import BMRCL_SYSTEM_ID

MODEL_FAMILIES: dict[str, dict[str, Any]] = {
    BMRCL_SYSTEM_ID: {
        "system_id": BMRCL_SYSTEM_ID,
        "city": "Bengaluru",
        "mode": "METRO",
        "operator": "BMRCL",
        "timezone": "Asia/Kolkata",
        "entity_type": "STATION",
        "measure": "hourly_station_boardings",
        "artifact_subdirectory": BMRCL_SYSTEM_ID,
        "source_id": "bmrcl-ridership-hourly",
    },
}


class UnsupportedModelFamilyError(ValueError):
    """Raised when a training request has no verified observed-demand family."""


def get_model_family(system_id: str) -> dict[str, Any]:
    family = MODEL_FAMILIES.get(str(system_id))
    if family is None:
        raise UnsupportedModelFamilyError(
            f"No verified observed-demand model family is registered for '{system_id}'. "
            "Static or schedule-only GTFS data cannot be used as a demand target."
        )
    return dict(family)


def model_family_directory(models_root: Path, system_id: str) -> Path:
    family = get_model_family(system_id)
    return models_root / str(family["artifact_subdirectory"])
