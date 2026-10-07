"""What the Mumbai demonstration families must actually answer like.

These assertions exist because the earlier pass described this behaviour without observing it. They exercise
the same service objects backend/app/main.py builds per registered family, so a regression here means a
rider-facing flow is broken, not just a document out of date. Memory is bounded deliberately: only the two
Mumbai families are loaded, never the whole registry.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.app.inference.daily_service import DailyDemandInferenceService
from backend.app.inference.service import TransitInferenceService
from backend.app.schemas.api import PredictionRequest
from ml.training.registry import model_family_directory, serving_families

ROOT = Path(__file__).resolve().parents[2]
FAMILIES = serving_families()


def _load(system_id: str):
    assert system_id in FAMILIES, f"{system_id} is not a served family: {sorted(FAMILIES)}"
    family = FAMILIES[system_id]
    service_class = TransitInferenceService if family["granularity"] == "hour" else DailyDemandInferenceService
    service = service_class(
        model_family_directory(ROOT / "backend/models", system_id) / "transitcrowd.joblib",
        ROOT / family["dataset_relative_path"],
        ROOT / family["metadata_relative_path"] if family.get("metadata_relative_path") else None,
    )
    if not service.ready:
        pytest.skip(f"{system_id} artifacts are not built in this checkout "
                    f"({service.unavailable_detail or 'run scripts/run_mumbai_registration.sh'})")
    return service, family


LOCAL = "mumbai-local-central"
METRO = "mumbai-metro"


def test_registered_family_paths_resolve_inside_the_repository():
    """§2: a registry entry must never point at a file that only existed in some developer's workspace."""
    for system_id, family in FAMILIES.items():
        for key in ("dataset_relative_path", "metadata_relative_path"):
            relative = family.get(key)
            if not relative:
                continue
            path = ROOT / relative
            assert path.exists(), f"{system_id}.{key} -> {relative} does not exist in this checkout"
            assert path.stat().st_size > 0, f"{system_id}.{key} -> {relative} is empty"
            assert ".git/lfs" not in str(path), "registry points at an LFS object file, not materialized data"


def test_local_publishes_corridor_from_towards_as_derived_context():
    service, _ = _load(LOCAL)
    meta = service.metadata()
    labels = [level["label"] for level in meta["entity_hierarchy"]]
    assert labels == ["Corridor", "From"], labels
    context = meta["route_context"]
    assert len(context["routes"]) == 3, sorted(context["routes"])
    assert len(context["towards_for_entity"]) == 53, len(context["towards_for_entity"])
    main = context["routes"]["Central Main"]
    assert main["endpoints"] == [main["ordered_stations"][0], main["ordered_stations"][-1]]
    assert main["ordered_stations"][0] == "CSMT" and "Kalyan" in main["ordered_stations"]
    # A station's TOWARDS set is the two ends of its own corridor, and never the station itself.
    # Kalyan is the terminus of Central Main in this file, so it has exactly one end to travel towards -
    # a mid-line station has two, and no station is ever offered a direction towards itself.
    assert context["towards_for_entity"]["central-main-kalyan"] == ["Towards CSMT"]
    assert context["towards_for_entity"]["central-main-dadar"] == ["Towards CSMT", "Towards Kalyan"]
    for entity_id, options in context["towards_for_entity"].items():
        station = entity_id.rsplit("-", 1)[-1]
        assert options and all(option.startswith("Towards ") for option in options)
        assert f"Towards {station}" not in options, (entity_id, options)
    assert "no destination-specific passenger counts" in context["towards_kind"]


def test_local_responds_to_any_hour_and_labels_future_as_projection():
    service, _ = _load(LOCAL)
    meta = service.metadata()
    # An hourly family with a complete 24-hour grid publishes no restricted slot list: every hour is valid.
    assert not meta.get("supported_time_slots"), meta.get("supported_time_slots")
    entity = sorted(service.entity_ids)[0]
    # Two days past the frontier: inside the family's recursive limit, but unambiguously not observed yet.
    horizon = date(2026, 10, 6) + timedelta(days=2)
    future = service.predict(LOCAL, entity, horizon.isoformat(), 8)
    # An unobserved date is answered by inference: no actual, no error, and it is labelled as a projection
    # made past the snapshot rather than presented as something the dataset recorded.
    assert future["forecast_kind"] == "post_snapshot_projection", future["forecast_kind"]
    assert future["absolute_error"] is None and future.get("actual_observed_demand") in (None, 0, False)
    assert str(future["data_frontier"])[:10] < horizon.isoformat()
    history = service.predict(LOCAL, entity, "2026-08-15", 8)
    # A date the dataset holds is answered with Actual + Prediction + Error side by side.
    assert history["forecast_kind"] == "historical_replay", history["forecast_kind"]
    assert history["actual_observed_demand"] is not None
    assert isinstance(history["absolute_error"], (int, float)) and history["absolute_error"] >= 0


def test_metro_uses_line_from_towards_slot_and_refuses_unpublished_times():
    service, _ = _load(METRO)
    meta = service.metadata()
    assert [level["label"] for level in meta["entity_hierarchy"]] == ["Line", "From", "Towards", "Time slot"]
    slots = [str(value)[:5] for value in (meta.get("supported_time_slots") or [])]
    assert slots and set(slots) <= {"08:00", "09:00", "13:00", "16:00", "18:00", "20:00"}, slots
    # The slot list the source publishes must survive into the response, or a client has nothing to offer.
    assert meta["supported_time_slots"] and len(meta["supported_time_slots"]) == 6, meta["supported_time_slots"]
    assert "time_slot_note" in meta
    # The raw direction column stays in the entity attributes; what the client renders are these level labels.
    assert "Chennai" not in meta["model_scope"], meta["model_scope"]
    assert "synthetic" in meta["model_scope"].lower(), meta["model_scope"]
    entity = sorted(service.entity_ids)[0]
    with pytest.raises(Exception) as exc:  # 07:00 is not a published slot in this source
        service.predict(METRO, entity, (date.today() + timedelta(days=30)).isoformat(), 7)
    assert "target_hour" in str(exc.value) or "day-granularity" in str(exc.value)
    result = service.predict(METRO, entity, (date(2026, 10, 6) + timedelta(days=3)).isoformat())
    assert result["is_model_forecast"] is True
    assert result["forecast_horizon_days"] > 0
    assert result["absolute_error"] is None, result["absolute_error"]


def test_prediction_request_carries_no_unused_fields():
    """§9: the request is documented by its fields - nothing may be accepted and then ignored."""
    assert set(PredictionRequest.model_fields) == {"system_id", "station_id", "target_date", "target_hour"}
    assert PredictionRequest.model_config.get("extra") == "forbid"


def test_synthetic_disclosure_is_attached_to_both_mumbai_families():
    for system_id in (LOCAL, METRO):
        service, family = _load(system_id)
        assert family.get("served_as") == "demo"
        meta = service.metadata()
        blob = str(meta).upper()
        assert "SYNTHETIC" in blob and "NOT LIVE" in blob, system_id


def test_no_registry_entry_points_at_an_absent_file_without_saying_how_to_rebuild_it():
    """§2 as an executable rule: a served family either has its data, or states the command that produces it.

    Checked for every served family through the same resolution backend/app/main.py uses - the registry entry
    first, then the legacy map for the two families that shipped before per-family paths existed. A family can
    legitimately have data that is not committed (operator-copyrighted extracts are fetched on demand, and the
    development copies of synthetic files stay out of git), but then silence is the failure mode: the entry must
    carry ``data_preparation_command`` so a fresh clone or image knows what to run rather than answering 503.
    """
    from backend.app.main import FAMILY_DATASETS

    for system_id, family in FAMILIES.items():
        data_rel = family.get("dataset_relative_path") or FAMILY_DATASETS.get(system_id, (None, None))[0]
        meta_rel = family.get("metadata_relative_path") or FAMILY_DATASETS.get(system_id, (None, None))[1]
        assert data_rel, f"{system_id} has no dataset path in the registry or the legacy map"
        for relative in (data_rel, meta_rel):
            path = ROOT / relative
            if path.exists():
                assert path.stat().st_size > 0, f"{system_id} -> {relative} is empty"
                with open(path, "rb") as handle:
                    head = handle.read(64)
                assert b"version https://git-lfs" not in head, (
                    f"{system_id} -> {relative} is an unmaterialized LFS pointer")
                continue
            rebuild = family.get("data_preparation_command")
            assert rebuild, (f"{system_id} points at {relative}, which is absent, and the entry does not say how "
                             f"to produce it (set data_preparation_command)")
            script = rebuild.split()[-1] if rebuild.split()[-1].endswith(".py") else rebuild.split()[1]
            assert (ROOT / script.removeprefix("./")).exists(), f"{system_id}: rebuild script {script} is not in the repo"
