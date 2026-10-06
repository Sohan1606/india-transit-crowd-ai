"""Explicit mode/operator model-family registry.

A model family is added only after an observed-demand source adapter and its
licensing/provenance have been verified. Schedule feeds do not register here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ml.data_pipeline.cmrl import CMRL_SYSTEM_ID
from ml.data_pipeline.source import BMRCL_SYSTEM_ID
from ml.features.periodic import PERIOD_SECONDS

ROOT = Path(__file__).resolve().parents[2]
#: Families registered by ``scripts/register_demand_dataset.py`` after a dataset passes the
#: gate. Code-defined families below always win on a key collision, so a downloaded registry
#: file cannot silently replace a verified production family.
REGISTRY_PATH = ROOT / "data/registry/model_families.json"
REQUIRED_KEYS = ("system_id", "city", "mode", "operator", "timezone", "entity_type", "measure",
                 "artifact_subdirectory", "source_id", "granularity", "target")
TRAINING_GRANULARITIES = ("day", "hour")


def _load_registered_families() -> dict[str, dict[str, Any]]:
    if not REGISTRY_PATH.is_file():
        return {}
    try:
        payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{REGISTRY_PATH} exists but cannot be read as JSON: {exc}") from exc
    families: dict[str, dict[str, Any]] = {}
    for entry in payload.get("families", []):
        system_id = str(entry.get("system_id", "")).strip()
        missing = [key for key in REQUIRED_KEYS if not entry.get(key)]
        if not system_id or missing:
            raise ValueError(f"Registry entry for {system_id or '<blank>'} is missing required keys: {missing}")
        if entry["granularity"] not in PERIOD_SECONDS:
            raise ValueError(
                f"Registry entry '{system_id}' declares granularity '{entry['granularity']}', which the feature "
                f"builders do not define (supported: {', '.join(sorted(PERIOD_SECONDS))})."
            )
        entry.setdefault("feature_period_seconds", PERIOD_SECONDS[str(entry["granularity"])])
        entry.setdefault("label_unit", "observed count")
        families[system_id] = entry
    return families

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
        "granularity": "hour",
        "target": "target_next_hour_demand",
    },
    CMRL_SYSTEM_ID: {
        "system_id": CMRL_SYSTEM_ID,
        "city": "Chennai",
        "mode": "METRO",
        "operator": "CMRL",
        "timezone": "Asia/Kolkata",
        "entity_type": "STATION",
        "measure": "daily_station_entries",
        "artifact_subdirectory": CMRL_SYSTEM_ID,
        "source_id": "cmrl-passenger-flow-daily",
        "granularity": "day",
        "target": "target_next_day_demand",
    },
}


_REGISTERED = _load_registered_families()
for _system_id, _family in _REGISTERED.items():
    MODEL_FAMILIES.setdefault(_system_id, _family)


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


def register_family(family: dict[str, Any], registry_path: Path = REGISTRY_PATH) -> Path:
    """Add or replace a gate-passed family in the JSON registry (never in code)."""
    missing = [key for key in REQUIRED_KEYS if not family.get(key)]
    if missing:
        raise ValueError(f"Registry entry for {family.get('system_id') or '<blank>'} is missing required keys: {missing}")
    if family["granularity"] not in PERIOD_SECONDS:
        raise ValueError(f"granularity must be one of {sorted(PERIOD_SECONDS)}")
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else {"families": []}
    families = [item for item in payload.get("families", []) if item.get("system_id") != family["system_id"]]
    families.append(dict(family))
    payload["families"] = families
    payload["note"] = ("Families here passed scripts/validate_demand_dataset.py through "
                       "scripts/register_demand_dataset.py. Development-only (synthetic) families are loaded by the "
                       "tooling but never served: see backend/app/main.py._build_services.")
    registry_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return registry_path


def serving_families() -> dict[str, dict[str, Any]]:
    """Families the API may serve: registered, gate-passed and not development-only."""
    return {system_id: family for system_id, family in MODEL_FAMILIES.items() if not family.get("development_only")}
