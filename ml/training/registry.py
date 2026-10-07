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
#: Where a registered family is allowed to appear.
#:  ``production`` - verified observed data, full gate, normal labelling.
#:  ``demo``       - a family whose data is not observed ground truth (synthetic / simulated /
#:                   modelled / undeclared). It IS served, because a demonstration has to run to
#:                   be useful, but every response carries its data class and a disclosure, and its
#:                   metrics are demonstration results, not real-world accuracy claims.
#:  ``internal``   - fixtures and development data; loaded by tooling, never served.
SERVED_AS_VALUES = ("production", "demo", "internal")
OBSERVED_CLASSES = ("observed", "verified_project_source", "documented_observed_source")
OBSERVED_TARGET_CRITERION = "target_values_are_actual_observations"


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
        # ``development_only`` is the older flag for "never served"; a registry file written before
        # served_as existed must keep behaving exactly as it did.
        declared = str(entry.get("served_as") or ("internal" if entry.get("development_only") else "production"))
        if declared not in SERVED_AS_VALUES:
            raise ValueError(
                f"Registry entry '{system_id}' declares served_as '{declared}'; expected one of "
                f"{', '.join(SERVED_AS_VALUES)}."
            )
        entry["served_as"] = declared
        entry["development_only"] = declared == "internal"
        entry.setdefault("dataset_class", "verified_project_source" if declared == "production" else "undeclared")
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
        "served_as": "production",
        "dataset_class": "verified_project_source",
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
        "served_as": "production",
        # Its normalized extract is copyright CMRL and is deliberately not committed, so a checkout or image
        # that has not fetched it must be told what produces the file rather than returning an unexplained 503.
        "data_preparation_command": "python3 scripts/prepare_chennai_data.py",
        "data_preparation_note": ("Operator-copyrighted ticket-count extract; fetched on demand and "
                                  "checksum-verified, never redistributed by this project."),
        "dataset_class": "verified_project_source",
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


def effective_served_as(entry: dict[str, Any]) -> str:
    """The serving mode an entry means, including entries written before ``served_as`` existed.

    ``development_only: true`` with no ``served_as`` still means "never served", so an in-memory or
    hand-edited registry entry cannot become public by omitting the newer key.
    """
    declared = str(entry.get("served_as") or ("internal" if entry.get("development_only") else "production"))
    return declared


def normalize_served_as(family: dict[str, Any]) -> dict[str, Any]:
    """Fill in / validate the ``served_as`` flag, keeping the older ``development_only`` flag coherent.

    An entry written before ``served_as`` existed (or by hand) with ``development_only: true`` still
    means "never served", so it normalizes to ``internal`` rather than silently becoming public.
    """
    entry = dict(family)
    declared = effective_served_as(entry)
    if declared not in SERVED_AS_VALUES:
        raise ValueError(f"served_as must be one of {', '.join(SERVED_AS_VALUES)}; got '{declared}'.")
    dataset_class = str(entry.get("dataset_class") or "")
    if declared == "production" and dataset_class and dataset_class not in OBSERVED_CLASSES:
        raise ValueError(
            f"Refusing to serve '{entry.get('system_id')}' as production: its dataset class '{dataset_class}' does "
            f"not claim observed ground truth (expected one of {', '.join(OBSERVED_CLASSES)})."
        )
    if declared == "demo" and dataset_class in OBSERVED_CLASSES:
        raise ValueError(
            f"'{entry.get('system_id')}' claims observed ground truth ('{dataset_class}'); register it as "
            "production and pass every gate criterion instead of labelling it a demonstration."
        )
    if declared == "demo":
        entry.setdefault("dataset_class", "synthetic")
        entry.setdefault("disclosure", SYNTHETIC_DISCLOSURE)
    elif declared == "production":
        entry.setdefault("dataset_class", "verified_project_source")
    entry["served_as"] = declared
    entry["development_only"] = declared == "internal"
    return entry


SYNTHETIC_DISCLOSURE = (
    "SYNTHETIC DEMONSTRATION FORECAST - modelled data supplied to exercise and demonstrate the "
    "forecasting pipeline. NOT live passenger ridership, NOT an operator measurement, NOT a "
    "real-world Mumbai crowd estimate."
)


def register_family(family: dict[str, Any], registry_path: Path = REGISTRY_PATH) -> Path:
    """Add or replace a gate-passed family in the JSON registry (never in code)."""
    missing = [key for key in REQUIRED_KEYS if not family.get(key)]
    if missing:
        raise ValueError(f"Registry entry for {family.get('system_id') or '<blank>'} is missing required keys: {missing}")
    if family["granularity"] not in PERIOD_SECONDS:
        raise ValueError(f"granularity must be one of {sorted(PERIOD_SECONDS)}")
    family = normalize_served_as(family)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else {"families": []}
    families = [item for item in payload.get("families", []) if item.get("system_id") != family["system_id"]]
    families.append(dict(family))
    payload["families"] = families
    payload["note"] = ("Families here passed scripts/validate_demand_dataset.py through "
                       "scripts/register_demand_dataset.py. served_as=production needs every criterion; "
                       "served_as=demo is served with a synthetic disclosure and needs every criterion except "
                       "target_values_are_actual_observations; served_as=internal is never served (see "
                       "backend/app/main.py._build_services).")
    registry_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if registry_path == REGISTRY_PATH:
        # The file is the source of truth, and this module's view of it is a cache. A registration that
        # is followed by training in the same process must see the family it just wrote, so the cache is
        # refreshed rather than left to the next interpreter.
        MODEL_FAMILIES.clear()
        MODEL_FAMILIES.update(_load_registered_families())
    return registry_path


def serving_families() -> dict[str, dict[str, Any]]:
    """Families the API may serve: production families, plus demo families under their disclosure."""
    return {system_id: family for system_id, family in MODEL_FAMILIES.items()
            if effective_served_as(family) in {"production", "demo"}}


def demo_families() -> dict[str, dict[str, Any]]:
    """Families served under a synthetic/demonstration label."""
    return {system_id: family for system_id, family in MODEL_FAMILIES.items()
            if effective_served_as(family) == "demo"}


def family_metadata() -> list[dict[str, Any]]:
    """Public family descriptions: the system list, UI routing and training CLI metadata."""
    rows: list[dict[str, Any]] = []
    for entry in MODEL_FAMILIES.values():
        row = {key: value for key, value in entry.items() if not str(key).startswith("_")}
        row["training_supported"] = entry["granularity"] in TRAINING_GRANULARITIES
        row["served_as"] = effective_served_as(entry)
        row["dataset_class"] = entry.get("dataset_class")
        row["observed_ground_truth"] = str(entry.get("dataset_class")) in OBSERVED_CLASSES
        rows.append(row)
    return rows
