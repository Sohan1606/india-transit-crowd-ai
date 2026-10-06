from __future__ import annotations
import joblib
import pandas as pd
from fastapi.testclient import TestClient

from backend.app.inference.service import TransitInferenceService
from backend.app.main import create_app
from ml.data_pipeline.source import BMRCL_SYSTEM_ID
from ml.features.forecasting import FEATURE_COLUMNS, TARGET
from ml.training.risk import RISK_ORDER, classify_demand, fit_risk_thresholds
from ml.training.registry import UnsupportedModelFamilyError
from ml.training.train import train_and_save
import pytest


@pytest.fixture(scope="module")
def client(training_fixture):
    return TestClient(create_app(service=training_fixture["service"]))


def test_model_registry_rejects_schedule_only_or_unverified_families(training_fixture, tmp_path):
    data = training_fixture["hourly"].copy()
    data["system_id"] = "delhi-dmrc-metro"
    with pytest.raises(UnsupportedModelFamilyError, match="No verified observed-demand model family"):
        train_and_save(data, tmp_path / "unverified")


def test_risk_boundaries_and_system_fallback_follow_training_only_percentiles():
    sample_values = list(range(600))
    frame = pd.DataFrame({
        "system_id": [BMRCL_SYSTEM_ID] * 602,
        "entity_id": ["sampled"] * 600 + ["sparse"] * 2,
        "target_next_hour_demand": sample_values + [50, 200],
    })
    thresholds = fit_risk_thresholds(frame, min_entity_targets=500, min_system_targets=500)
    sampled = thresholds["entities"]["sampled"]
    sparse = thresholds["entities"]["sparse"]
    assert sampled["source"] == "entity_training_distribution"
    assert sparse["source"] == "system_training_fallback"
    assert classify_demand(sampled["q50"], "sampled", BMRCL_SYSTEM_ID, thresholds)[0] == "LOW"
    assert classify_demand(sampled["q80"], "sampled", BMRCL_SYSTEM_ID, thresholds)[0] == "MODERATE"
    assert classify_demand(sampled["q95"], "sampled", BMRCL_SYSTEM_ID, thresholds)[0] == "HIGH"
    assert classify_demand(sampled["q95"] + 1e-6, "sampled", BMRCL_SYSTEM_ID, thresholds)[0] == "SEVERE"
    assert thresholds["fitted_on"].startswith("training partition only")

    global_fallback = fit_risk_thresholds(frame, min_entity_targets=900, min_system_targets=900)
    assert global_fallback["entities"]["sparse"]["source"] == "global_training_fallback"


def test_all_benchmarks_train_and_report_champions_from_chronological_validation(training_fixture):
    report = training_fixture["report"]
    assert len(report["regression"]["models"]) == 6
    assert len(report["classification"]["models"]) == 6
    assert report["regression"]["champion_key"] == report["regression"]["ranking_by_validation"][0]
    assert report["classification"]["champion_key"] == report["classification"]["ranking_by_validation"][0]
    assert report["split"]["train"]["rows"] + report["split"]["validation"]["rows"] + report["split"]["test"]["rows"] == report["dataset"]["supervised_rows"]
    assert "chronological" in report["split"]["strategy"].lower()
    assert report["demand_risk"]["fitted_on"].startswith("training partition only")
    assert report["feature_schema"]["feature_count"] == len(FEATURE_COLUMNS)
    assert report["station_analytics"]["pca"]["components"] == 2
    assert report["station_analytics"]["dbscan"]["min_samples"] == 3
    assert report["dataset"]["entity_count"] == 4  # The explicitly zero-only synthetic test entity is not discarded.
    assert report["dataset"]["explicit_zero_observations"] > 0
    assert report["dataset"]["missing_observations_filled"] == 0
    assert report["cross_validation"]["n_splits"] == 3
    assert report["split"]["train"]["end"] < report["split"]["validation"]["start"]
    assert report["split"]["validation"]["end"] < report["split"]["test"]["start"]
    classifier = next(model for model in report["classification"]["models"] if model["key"] == report["classification"]["champion_key"])
    assert classifier["test"]["confusion_matrix"]
    assert "classification_report" in classifier["test"]


def test_artifact_round_trip_predictions_explanations_and_recommendations(training_fixture):
    service = training_fixture["service"]
    path = training_fixture["root"] / "models" / BMRCL_SYSTEM_ID / "transitcrowd.joblib"
    bundle = joblib.load(path)
    last = pd.Timestamp(training_fixture["hourly"]["timestamp"].max())
    target = last + pd.Timedelta(hours=1)
    result = service.predict(BMRCL_SYSTEM_ID, "test-station-1", target.date().isoformat(), target.hour)
    assert result["system_id"] == BMRCL_SYSTEM_ID
    assert result["station_id"] == "test-station-1"
    assert result["predicted_boardings"] >= 0
    assert result["risk"] in RISK_ORDER
    assert result["classification_check"] in RISK_ORDER
    assert result["classification_agrees"] == (result["risk"] == result["classification_check"])
    assert result["forecast_horizon_hours"] == 1
    assert result["forecast_kind"] == "post_snapshot_projection"
    assert len(result["explanation"]) > 0
    assert result["explanation_method"].startswith("Model-backed sensitivity")
    assert result["recommendation"]["status"] in {"available", "no_lower_demand_window", "insufficient_data"}
    assert "regression_model" in bundle and "classification_model" in bundle
    assert TARGET not in bundle["feature_columns"]
    assert "entity:test-station-4" in bundle["training_distributions"]


def test_service_exposes_only_trained_observed_station_entities(training_fixture):
    service = training_fixture["service"]
    assert len(service.stations) == 4
    assert len(service.station_summaries(BMRCL_SYSTEM_ID)) == 4
    assert any(item["station_id"] == "test-station-4" for item in service.station_summaries(BMRCL_SYSTEM_ID))


def test_health_catalog_prediction_history_heatmap_analytics_and_model_api(client, training_fixture):
    health = client.get("/api/health")
    assert health.status_code == 200 and health.json()["model_ready"] is True
    catalog = client.get("/api/systems").json()
    bmrcl = next(item for item in catalog if item["system_id"] == BMRCL_SYSTEM_ID)
    delhi = next(item for item in catalog if item["system_id"] == "delhi-dmrc-metro")
    assert bmrcl["prediction_available"] is True and bmrcl["station_count"] == 4
    assert delhi["prediction_available"] is False and "GTFS" in delhi["prediction_unavailable_reason"]
    assert len(client.get(f"/api/stations?system_id={BMRCL_SYSTEM_ID}").json()) == 4
    assert len(client.get("/api/demand-sources").json()["additional_observed_demand_candidates"]) >= 3

    last = pd.Timestamp(training_fixture["hourly"]["timestamp"].max()) + pd.Timedelta(hours=1)
    payload = {"system_id": BMRCL_SYSTEM_ID, "station_id": "test-station-1", "target_date": last.date().isoformat(), "target_hour": last.hour}
    prediction = client.post("/api/predict", json=payload)
    assert prediction.status_code == 200
    assert prediction.json()["station_id"] == "test-station-1"
    assert prediction.json()["relative_demand_band"] in RISK_ORDER
    params = f"system_id={BMRCL_SYSTEM_ID}&station_id=test-station-1"
    history = client.get(f"/api/history?{params}&hours=12")
    assert len(history.json()["points"]) == 12
    assert history.json()["points"][-1]["observation_type"] == "observed"
    assert len(client.get(f"/api/heatmap?{params}").json()["cells"]) == 168
    assert len(client.get("/api/station-analytics").json()["entities"]) == 4
    assert len(client.get("/api/model-performance").json()["regression"]["models"]) == 6
    comparison = client.get(
        f"/api/station-comparison?system_id={BMRCL_SYSTEM_ID}&target_date={last.date()}&target_hour={last.hour}&selected_station_id=test-station-1"
    )
    assert len(comparison.json()["stations"]) == 4


def test_api_explicitly_rejects_unsupported_unknown_station_bad_input_and_missing_history(client):
    unsupported = {"system_id": "delhi-dmrc-metro", "station_id": "any-station", "target_date": "2025-02-01", "target_hour": 8}
    response = client.post("/api/predict", json=unsupported)
    assert response.status_code == 409
    assert "Prediction unavailable" in response.json()["detail"]
    assert "Static DMRC GTFS" in response.json()["detail"]
    assert client.get("/api/stations?system_id=delhi-dmrc-metro").status_code == 409

    unknown_system = {**unsupported, "system_id": "unlisted-system"}
    assert client.post("/api/predict", json=unknown_system).status_code == 404
    payload = {"system_id": BMRCL_SYSTEM_ID, "station_id": "not-a-real-station", "target_date": "2025-04-01", "target_hour": 8}
    assert client.post("/api/predict", json=payload).status_code == 404
    payload["station_id"] = "test-station-1"
    payload["target_hour"] = 25
    assert client.post("/api/predict", json=payload).status_code == 422
    payload["target_hour"] = 8
    payload["unexpected"] = "reject-me"
    assert client.post("/api/predict", json=payload).status_code == 422
    too_early = {"system_id": BMRCL_SYSTEM_ID, "station_id": "test-station-1", "target_date": "2025-01-02", "target_hour": 2}
    assert client.post("/api/predict", json=too_early).status_code == 422


def test_service_unavailable_is_503_not_a_false_unavailable_system(training_fixture, tmp_path):
    broken = TransitInferenceService(tmp_path / "missing.joblib", training_fixture["data_path"])
    client = TestClient(create_app(service=broken))
    assert client.get("/api/health").json()["status"] == "degraded"
    response = client.post("/api/predict", json={
        "system_id": BMRCL_SYSTEM_ID, "station_id": "test-station-1", "target_date": "2025-02-01", "target_hour": 8,
    })
    assert response.status_code == 503
    assert "traceback" not in response.text.lower()


def test_system_model_registry_is_operator_specific(training_fixture):
    bundle = joblib.load(training_fixture["root"] / "models" / BMRCL_SYSTEM_ID / "transitcrowd.joblib")
    assert bundle["model_family"]["city"] == "Bengaluru"
    assert bundle["model_family"]["mode"] == "METRO"
    assert bundle["model_family"]["operator"] == "BMRCL"
    assert set(bundle["model_family"]) >= {"system_id", "city", "mode", "operator", "timezone"}
    assert bundle["model_family"]["timezone"] == "Asia/Kolkata"
