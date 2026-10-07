"""A synthetic family can be served - only under a label that cannot be mistaken for measurement.

The project's rule is that modelled data may demonstrate and test the forecasting architecture but is
never presented as real-world ridership. These tests pin the whole chain that makes that true: the
registry mode, the trainer propagating it into the saved bundle, the service stamping it onto every
answer, and the hour gate that refuses a clock time the family's data never observed.

The fixture below is a generated test fixture, not data from any operator.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.inference.daily_service import DailyDemandInferenceService  # noqa: E402
from backend.app.inference.service import TransitInferenceService, UnsupportedTimeSlot, provenance_for  # noqa: E402
from ml.training import registry  # noqa: E402

TZ = "Asia/Kolkata"
DEMO_SYSTEM = "synthetic-demo-metro"


def synthetic_daily_frame(days: int = 150, entities: int = 4) -> pd.DataFrame:
    """Station-day counts with integer values, a consistent next-day target and a bogus target."""
    rng = np.random.default_rng(11)
    dates = pd.date_range("2026-01-01", periods=days, freq="D")
    rows = []
    for index in range(entities):
        station = f"STN{index:02d}"
        base = 1200.0 * (index + 1)
        level = base * (1 + 0.2 * np.sin(np.arange(days) / 7 * 2 * np.pi)) + rng.normal(0, base * 0.05, days)
        level = np.maximum(level, 1)
        for day_index, stamp in enumerate(dates):
            following = level[day_index + 1] if day_index + 1 < days else np.nan
            rows.append({"Date": stamp.strftime("%Y-%m-%d"), "Line": f"L{(index % 2) + 1}", "Station": station,
                         "Passengers": int(round(level[day_index])),
                         "Peak_Direction": "INBOUND" if day_index % 2 else "OUTBOUND",
                         "Data_Type": "Synthetic",
                         "Target_Next_Day_Passengers": int(round(following)) if not np.isnan(following) else "",
                         "Target_Next_Hour_Passengers": int(round(level[day_index] * 3.7 + 91))})
    return pd.DataFrame(rows)


FAMILY = {"system_id": DEMO_SYSTEM, "city": "Nowhere", "mode": "METRO", "operator": "Fixture",
          "timezone": TZ, "entity_type": "STATION", "measure": "daily_station_entries",
          "artifact_subdirectory": DEMO_SYSTEM, "source_id": "synthetic-fixture", "granularity": "day",
          "target": "target_next_day_demand", "dataset_class": "synthetic", "served_as": "demo",
          "feature_period_seconds": 86400, "label_unit": "passengers"}


@pytest.fixture(scope="module")
def demo_bundle(tmp_path_factory):
    """Train the real day pipeline on the synthetic fixture and save a real bundle for it.

    The family is registered only for this module, exactly the way ``--serve-as demo`` would
    register it, so the service resolves the same metadata a running API would.
    """
    from ml.data_pipeline.cleaning import clean_normalized_demand
    from ml.training.train_daily import save_artifacts, train_daily

    patcher = pytest.MonkeyPatch()
    patcher.setattr(registry, "MODEL_FAMILIES", {**registry.MODEL_FAMILIES, DEMO_SYSTEM: FAMILY})

    frame = synthetic_daily_frame()
    stamps = pd.to_datetime(frame["Date"]).dt.tz_localize(TZ)
    canonical = pd.DataFrame({
        "system_id": DEMO_SYSTEM, "city": "Nowhere", "mode": "METRO", "operator": "Fixture",
        "entity_id": frame["Line"].astype(str) + "-" + frame["Station"].str.lower(),
        "entity_name": frame["Station"], "entity_type": "STATION", "timestamp": stamps,
        "demand_count": frame["Passengers"].astype(float), "measure": "daily_station_entries",
        "source_id": "synthetic-fixture", "line_id": frame["Line"].astype(str), "services_provided": 1.0,
    })
    cleaned, _ = clean_normalized_demand(canonical, timezone=TZ, period_seconds=86400)
    result = train_daily(cleaned, dataset_metadata={"source_id": "synthetic-fixture",
                                                    "dataset_class": "synthetic"}, tz=TZ)
    directory = Path(tmp_path_factory.mktemp("demo-artifacts")) / DEMO_SYSTEM
    save_artifacts(result, directory)
    csv_path = directory.parent / "synthetic.csv"
    cleaned.to_csv(csv_path, index=False)
    try:
        yield {"artifact": directory / "transitcrowd.joblib", "data": csv_path, "family": FAMILY}
    finally:
        patcher.undo()


# ------------------------------------------------------------------ registry mode
def test_demo_mode_is_a_real_registry_state(tmp_path: Path):
    entry = {"system_id": DEMO_SYSTEM, "city": "Nowhere", "mode": "METRO", "operator": "Fixture",
             "timezone": TZ, "entity_type": "STATION", "measure": "daily_station_entries",
             "artifact_subdirectory": DEMO_SYSTEM, "source_id": "synthetic-fixture",
             "granularity": "day", "target": "target_next_day_demand",
             "dataset_class": "synthetic", "served_as": "demo"}
    path = registry.register_family(dict(entry), tmp_path / "model_families.json")
    saved = __import__("json").loads(path.read_text(encoding="utf-8"))["families"][0]
    assert saved["served_as"] == "demo" and saved["dataset_class"] == "synthetic"
    assert saved["development_only"] is False
    assert saved["disclosure"].startswith("SYNTHETIC DEMONSTRATION FORECAST")


def test_registering_observed_data_as_a_demo_is_refused():
    with pytest.raises(ValueError, match="claims observed ground truth"):
        registry.normalize_served_as({"system_id": "x", "dataset_class": "verified_project_source",
                                      "served_as": "demo"})


def test_serving_mode_and_development_flag_stay_coherent():
    normalized = registry.normalize_served_as({"system_id": "x", "served_as": "internal"})
    assert normalized["development_only"] is True and registry.effective_served_as(normalized) == "internal"
    legacy = registry.normalize_served_as({"system_id": "y", "development_only": True})
    assert legacy["served_as"] == "internal"  # an entry that predates served_as stays unserved
    with pytest.raises(ValueError, match="served_as must be one of"):
        registry.normalize_served_as({"system_id": "z", "served_as": "spotlight"})
    with pytest.raises(ValueError, match="does not claim observed ground truth"):
        registry.normalize_served_as({"system_id": "w", "dataset_class": "synthetic", "served_as": "production"})


def test_provenance_falls_back_to_the_registry_when_an_older_bundle_is_silent():
    provenance = provenance_for({}, {"served_as": "demo", "dataset_class": "synthetic"})
    assert provenance["data_class"] == "synthetic_development"
    assert provenance["metrics_are_demonstration_only"] is True
    assert "NOT live passenger ridership" in provenance["disclosure"]
    # A verified family gets no disclosure: the absence is what makes the label meaningful.
    assert provenance_for({}, {"served_as": "production", "dataset_class": "verified_project_source"})["disclosure"] is None


# ------------------------------------------------------------------ trainer propagation
def test_the_trainer_stores_the_serving_mode_and_data_class_in_the_bundle(demo_bundle: dict[str, Path]):
    bundle = joblib.load(demo_bundle["artifact"])
    assert bundle["granularity"] == "day"
    # the trainer writes the family's serving mode into the artifact itself, so a reloaded bundle
    # cannot lose the label even when the registry file is absent
    assert bundle["served_as"] == "demo" and bundle["dataset_class"] == "synthetic"
    service = DailyDemandInferenceService(demo_bundle["artifact"], demo_bundle["data"], None)
    metadata = service.metadata()
    assert metadata["served_as"] == "demo" and metadata["dataset_class"] == "synthetic"
    assert metadata["data_class"] == "synthetic_development"
    assert metadata["metrics_are_demonstration_only"] is True
    assert metadata["supported_time_slots"] is None  # a day family has no clock times to offer


def test_a_demo_answer_carries_the_disclosure_and_is_never_called_observed(demo_bundle: dict[str, Path]):
    service = DailyDemandInferenceService(demo_bundle["artifact"], demo_bundle["data"], None)
    entity = sorted(service.bundle["entity_ids"])[0]
    frontier = pd.Timestamp(service.bundle["data_end"]).date()
    answer = service.predict(DEMO_SYSTEM, entity, str(frontier + pd.Timedelta(days=1)))
    assert answer["data_class"] == "synthetic_development"
    assert answer["disclosure"].startswith("SYNTHETIC DEMONSTRATION FORECAST")
    assert "NOT live passenger ridership" in answer["disclosure"]
    # the answer is still a forecast from the persisted model, not an echo of a stored row
    assert answer["is_model_forecast"] is True and answer["actual_observed_demand"] is None
    assert answer["observation_status"] == "OBSERVED VALUE UNAVAILABLE"


# ------------------------------------------------------------------ hour gate
class _HourStub(TransitInferenceService):
    """Only the target-timestamp path is under test, so only the bundle is real."""

    def __init__(self, slots: list[int] | None):
        self.bundle = {"supported_time_slots": slots}
        self.source_metadata = {}
        self.timezone = TZ

    def _registry_family(self) -> dict:
        return {}


@pytest.mark.parametrize("slots, hour, allowed", [
    ([8, 9, 13, 16, 18, 20], 8, True),
    ([8, 9, 13, 16, 18, 20], 10, False),   # a slot the family never observed
    ([8, 9, 13, 16, 18, 20], 20, True),
    (list(range(24)), 3, True),             # a complete hourly file imposes nothing
    (None, 3, True),                        # an older bundle without the field keeps working
])
def test_an_hour_that_the_data_never_contained_is_refused_with_the_supported_list(slots, hour, allowed):
    service = _HourStub(slots)
    if allowed:
        stamp = service._target_timestamp("2026-05-10", hour)
        assert int(stamp.hour) == hour
        return
    with pytest.raises(UnsupportedTimeSlot) as excinfo:
        service._target_timestamp("2026-05-10", hour)
    message = str(excinfo.value)
    assert "08:00, 09:00, 13:00, 16:00, 18:00, 20:00" in message and "10:00" in message


def test_the_synthetic_fixture_target_columns_are_audited_not_assumed():
    """The fixture deliberately carries one honest and one dishonest precomputed target."""
    from ml.data_pipeline.audit import audit_frame

    report = audit_frame(synthetic_daily_frame(days=150), timezone=TZ)
    verdicts = {name: entry["verdict"] for name, entry in report["precomputed_targets"]["per_target"].items()}
    assert verdicts["Target_Next_Day_Passengers"] == "CONSISTENT"
    assert verdicts["Target_Next_Hour_Passengers"] == "INCONSISTENT"
    assert report["precomputed_targets"]["usable_as_ground_truth"] == ["Target_Next_Day_Passengers"]
    assert report["provenance"]["classification"] == "synthetic_development"
    assert report["temporal"]["period"]["seconds"] == 86400
