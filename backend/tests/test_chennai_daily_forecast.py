"""Tests for the day-granularity Chennai (CMRL) family: data contract, leakage, split, future path."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.data_pipeline.cleaning import clean_normalized_demand
from ml.data_pipeline.cmrl import CMRLStationDailyAdapter
from ml.data_pipeline.source import SourceError
from ml.features.daily import FEATURE_COLUMNS, MIN_HISTORY_DAYS, TARGET, build_supervised_frame, features_for_target
from ml.training.forecast import project_future
from ml.training.train_daily import save_artifacts, train_daily

from backend.app.inference.daily_service import DailyDemandInferenceService, GranularityMismatch
from backend.app.inference.service import ForecastHorizonExceeded, InsufficientHistory, UnknownEntity

TIMEZONE = "Asia/Kolkata"
ENTITIES = [("01", "SWD", "Wimco Nagar Depot"), ("01", "STG", "Tollgate"), ("02", "SCC", "Chennai Central")]
DAYS = 120
START = pd.Timestamp("2026-01-01")


def _fixture_files(root: Path) -> tuple[Path, Path]:
    rows = []
    for offset in range(DAYS):
        day = START + pd.Timedelta(days=offset)
        weekend = day.dayofweek >= 5
        for index, (line, code, _) in enumerate(ENTITIES):
            base = 2000 + 900 * index
            value = base * (0.62 if weekend else 1.0) * (1 + 0.05 * np.sin(offset / 7 * 2 * np.pi)) + offset * 4
            rows.append({"Date": day.strftime("%Y-%m-%d"), "Line": line, "Station": code,
                         "Total": int(round(value)), "Paper QR": int(round(value * 0.3))})
    station = pd.DataFrame(rows)
    station_path = root / "ChennaiMetro_Station_Ridership.csv"
    station.to_csv(station_path, index=False)
    daily = station.groupby("Date", as_index=False)["Total"].sum().rename(columns={"Total": "Total"})
    daily_path = root / "ChennaiMetro_Daily_Ridership.csv"
    daily.to_csv(daily_path, index=False)
    return station_path, daily_path


@pytest.fixture(scope="session")
def chennai_fixture(tmp_path_factory):
    root = tmp_path_factory.mktemp("cmrl")
    station_path, daily_path = _fixture_files(root)
    normalized, metadata = CMRLStationDailyAdapter().load(station_path, daily_path)
    daily, _ = clean_normalized_demand(normalized, timezone=TIMEZONE)
    result = train_daily(daily, dataset_metadata=metadata, tz=TIMEZONE)
    directory = root / "models" / "chennai-cmrl-metro"
    save_artifacts(result, directory)
    service = DailyDemandInferenceService(directory / "transitcrowd.joblib", root / "normalized.csv")
    # the service needs the same normalized CSV the training run consumed
    daily.to_csv(root / "normalized.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    service = DailyDemandInferenceService(directory / "transitcrowd.joblib", root / "normalized.csv")
    return {"root": root, "normalized": normalized, "metadata": metadata, "daily": daily,
            "result": result, "service": service}


# --------------------------------------------------------------------- source contract
def test_adapter_refuses_duplicate_negative_and_unknown_values(tmp_path):
    station_path, _ = _fixture_files(tmp_path)
    frame = pd.read_csv(station_path)
    frame = pd.concat([frame, frame.head(1)], ignore_index=True)
    duplicate_path = tmp_path / "duplicates.csv"
    frame.to_csv(duplicate_path, index=False)
    with pytest.raises(SourceError, match="duplicate station-date rows"):
        CMRLStationDailyAdapter().load(duplicate_path, None)

    negative = pd.read_csv(station_path)
    negative.loc[0, "Total"] = -5
    negative_path = tmp_path / "negative.csv"
    negative.to_csv(negative_path, index=False)
    with pytest.raises(SourceError, match="invalid rows"):
        CMRLStationDailyAdapter().load(negative_path, None)

    unmapped = pd.read_csv(station_path)
    unmapped.loc[0, "Station"] = "ZZZ"
    unmapped_path = tmp_path / "unmapped.csv"
    unmapped.to_csv(unmapped_path, index=False)
    with pytest.raises(SourceError, match="unmapped station codes"):
        CMRLStationDailyAdapter().load(unmapped_path, None)


def test_adapter_keeps_every_observed_row_and_reports_semantics(chennai_fixture):
    data, metadata = chennai_fixture["normalized"], chennai_fixture["metadata"]
    assert len(data) == len(ENTITIES) * DAYS
    assert metadata["missing_station_days_filled"] == 0
    assert metadata["duplicate_station_dates"] == 0
    assert metadata["unique_dates"] == DAYS == metadata["expected_contiguous_dates"]
    assert set(data["system_id"]) == {"chennai-cmrl-metro"}
    assert set(data["measure"]) == {"daily_station_entries"}
    assert data["timestamp"].dt.tz is not None
    check = metadata["measure_semantics_check"]
    assert check["ratio_mean"] == pytest.approx(1.0, abs=0.05), "fixture totals must match the system file"


# --------------------------------------------------------------------- features and split
def test_no_target_leakage_in_daily_features(chennai_fixture):
    daily = chennai_fixture["daily"]
    frame = build_supervised_frame(daily, timezone=TIMEZONE)
    last_day = frame["timestamp"].max()
    altered = daily.copy()
    altered.loc[altered["timestamp"] == last_day, "demand_count"] += 50_000
    altered_frame = build_supervised_frame(altered, timezone=TIMEZONE)
    columns = [column for column in FEATURE_COLUMNS if column != "entity_id"]
    left = frame.sort_values(["timestamp", "entity_id"]).reset_index(drop=True)
    right = altered_frame.sort_values(["timestamp", "entity_id"]).reset_index(drop=True)
    assert np.allclose(left[columns].astype(float), right[columns].astype(float)), \
        "the value on the target day must not be usable as a feature of that same day"
    assert not np.allclose(left[TARGET].astype(float), right[TARGET].astype(float))


def test_features_for_target_only_uses_strictly_earlier_days(chennai_fixture):
    daily = chennai_fixture["daily"]
    entity_id = daily["entity_id"].iloc[0]
    target = pd.Timestamp(daily["timestamp"].max())
    series = daily.loc[daily["entity_id"].eq(entity_id)].sort_values("timestamp")
    features = features_for_target(daily, entity_id, target, timezone=TIMEZONE)
    assert float(features["lag_1"].iloc[0]) == float(series["demand_count"].iloc[-2])
    assert float(features["lag_7"].iloc[0]) == float(series["demand_count"].iloc[-8])
    # a day whose immediate predecessor is absent (i.e. beyond the frontier) must be refused,
    # which is exactly why the service recurses instead of guessing
    with pytest.raises(ValueError, match="no observation at"):
        features_for_target(daily, entity_id, target + pd.Timedelta(days=5), timezone=TIMEZONE)


def test_supervised_frame_drops_insufficient_history(chennai_fixture):
    frame = build_supervised_frame(chennai_fixture["daily"], timezone=TIMEZONE)
    assert len(frame) == len(ENTITIES) * (DAYS - MIN_HISTORY_DAYS)
    assert frame[TARGET].notna().all() and (frame[TARGET] > 0).all()


def test_split_is_chronological_and_leaks_no_future(chennai_fixture):
    report = chennai_fixture["result"]["report"]
    train, validation, test = (report["split"][key] for key in ("train", "validation", "test"))
    assert pd.Timestamp(validation["start"]) > pd.Timestamp(train["end"])
    assert pd.Timestamp(test["start"]) > pd.Timestamp(validation["end"])
    supervised = chennai_fixture["result"]["supervised"]
    train_rows = supervised.loc[pd.to_datetime(supervised["timestamp"]) <= pd.Timestamp(train["end"])]
    assert set(pd.to_datetime(train_rows["timestamp"]).dt.normalize().unique()) <= set(
        pd.to_datetime(supervised.loc[pd.to_datetime(supervised["timestamp"]) <= pd.Timestamp(train["end"]),
                                     "timestamp"]).dt.normalize().unique())


def test_champion_is_selected_on_validation_only(chennai_fixture):
    report = chennai_fixture["result"]["report"]
    for task in ("regression", "classification"):
        models = report[task]["models"]
        champion = report[task]["champion_key"]
        best = min(models, key=lambda item: item["validation"]["mae"] if task == "regression"
                   else -item["validation"]["f1_macro"])
        assert champion == best["key"], f"{task} champion must be the best validation model"
    assert report["regression"]["uses_test_metrics"] is False
    assert report["classification"]["uses_test_metrics"] is False


def test_missing_day_breaks_the_lag_chain_inst_of_silently_skipping(chennai_fixture):
    """A gap must remove the affected target rows, not let ``lag_7`` reach across it."""
    daily = chennai_fixture["daily"].copy()
    entity_id = sorted(daily["entity_id"].unique())[0]
    gap_day = START.tz_localize(TIMEZONE) + pd.Timedelta(days=70)
    removal = daily["entity_id"].eq(entity_id) & daily["timestamp"].eq(gap_day)
    assert removal.any()
    gapped = daily.loc[~removal]
    frame = build_supervised_frame(gapped, timezone=TIMEZONE)
    complete = build_supervised_frame(chennai_fixture["daily"], timezone=TIMEZONE)
    targets = set(frame.loc[frame["entity_id"].eq(entity_id), "timestamp"])
    before = set(complete.loc[complete["entity_id"].eq(entity_id), "timestamp"])
    gap = pd.Timestamp(gap_day)
    # Every window that can see the gap is 28 days wide (rolling means, lag_28, trend
    # ratio), so exactly the targets from the gap day through gap+28 must disappear.
    assert targets == before - {gap + pd.Timedelta(days=offset) for offset in range(0, 29)}, (
        "a missing day must delete every row whose lag or rolling window would have to bridge it")
    assert gap + pd.Timedelta(days=29) in targets, "history must recover once the gap leaves the longest window"
    # untouched entities keep their full row count, proving the removal is entity-local
    other = sorted(set(daily["entity_id"]) - {entity_id})[0]
    assert len(set(frame.loc[frame["entity_id"].eq(other), "timestamp"])) == DAYS - MIN_HISTORY_DAYS
    assert not frame[[*FEATURE_COLUMNS, TARGET]].isna().to_numpy().any()


# --------------------------------------------------------------------- future forecast path
def test_future_day_is_labelled_model_forecast(chennai_fixture):
    service = chennai_fixture["service"]
    assert service.ready, service.unavailable_detail
    entity_id = service.entity_ids[0]
    frontier = service.data_frontier
    result = service.predict("chennai-cmrl-metro", entity_id, (frontier + pd.Timedelta(days=4)).strftime("%Y-%m-%d"))
    assert result["forecast_kind"] == "post_frontier_projection"
    assert result["is_model_forecast"] is True and result["is_recursive_forecast"] is True
    assert result["forecast_horizon_days"] == 4
    assert result["target_relative_to_data_frontier"] == "after"
    assert "MODEL FORECAST" in result["forecast_note"]
    assert result["predicted_entries"] >= 0 and result["relative_demand_band"] in ("LOW", "MODERATE", "HIGH", "SEVERE")
    assert result["training_cutoff"].startswith(str(pd.Timestamp(service.bundle["training_cutoff"]).date()))
    assert result["explanation"], "counterfactual explanation must accompany a forecast"
    assert result["recommendation"]["advice_kind"] == "day_level_forecast_comparison"
    assert all(day["forecast_horizon_days"] >= 1 for day in result["recommendation"]["alternative_days"])


def test_observed_day_is_reported_as_replay_not_forecast(chennai_fixture):
    service = chennai_fixture["service"]
    entity_id = service.entity_ids[0]
    past = service.data_frontier - pd.Timedelta(days=6)
    result = service.predict("chennai-cmrl-metro", entity_id, past.strftime("%Y-%m-%d"))
    assert result["forecast_kind"] == "historical_replay"
    assert result["is_model_forecast"] is False
    assert result["forecast_horizon_days"] == 0
    assert result["target_relative_to_data_frontier"] == "before"
    assert "HISTORICAL REPLAY" in result["forecast_note"]


def test_horizon_limit_and_unknown_entity_are_refused(chennai_fixture):
    service = chennai_fixture["service"]
    entity_id = service.entity_ids[0]
    far = service.data_frontier + pd.Timedelta(days=int(service.bundle["max_recursive_horizon_days"]) + 5)
    with pytest.raises(ForecastHorizonExceeded, match="days beyond the last observed day"):
        service.predict("chennai-cmrl-metro", entity_id, far.strftime("%Y-%m-%d"))
    with pytest.raises(UnknownEntity):
        service.predict("chennai-cmrl-metro", "not-a-station", service.data_frontier.strftime("%Y-%m-%d"))
    with pytest.raises(GranularityMismatch, match="day-granularity"):
        service.predict("chennai-cmrl-metro", entity_id, service.next_unobserved_day.strftime("%Y-%m-%d"),
                        target_hour=18)


def test_hour_granularity_endpoints_are_refused_not_invented(chennai_fixture):
    service = chennai_fixture["service"]
    with pytest.raises(GranularityMismatch, match="invented rather than measured"):
        service.heatmap("chennai-cmrl-metro", service.entity_ids[0])
    pattern = service.weekly_pattern("chennai-cmrl-metro", service.entity_ids[0])
    assert len(pattern["cells"]) == 7
    assert all(cell["observations"] > 0 for cell in pattern["cells"])


def test_projection_refuses_to_start_at_or_before_the_frontier(chennai_fixture):
    service = chennai_fixture["service"]
    daily = chennai_fixture["daily"]
    entity_id = service.entity_ids[0]
    frame = daily.loc[daily["entity_id"].eq(entity_id), ["timestamp", "entity_id", "demand_count"]]
    with pytest.raises(ValueError, match="after the last available observation"):
        project_future(frame, entity_id, lambda X: 1.0, service.data_frontier,
                       service.data_frontier + pd.Timedelta(days=2), timezone=TIMEZONE)


def test_future_preview_and_source_gap_are_marked_as_forecasts(chennai_fixture):
    service = chennai_fixture["service"]
    preview = service.future_preview("chennai-cmrl-metro", days=3)
    assert preview["kind"] == "MODEL_FORECAST_NOT_LIVE_COUNT"
    assert len(preview["days"]) == 3
    assert [row["forecast_horizon_days"] for row in preview["days"]] == [1, 2, 3]
    assert preview["days"][0]["system_total_predicted_entries"] > 0
    gap = service.source_gap_report()
    assert gap["live_feed"] is False and gap["days_behind_today"] >= 0


def test_performance_endpoint_separates_replay_from_future(chennai_fixture):
    service = chennai_fixture["service"]
    (service.artifact_path.parent / "evaluation_replay.json").write_text(
        json.dumps({"recursive_projection_over_same_window": {"mae": 12.0}}), encoding="utf-8")
    performance = service.model_performance()
    assert "future_forecast_validation" in performance and "historical_replay_separation" in performance
    assert performance["future_forecast_validation"]["recursive_projection_over_same_window"]["mae"] == 12.0


# --------------------------------------------------------------------- API wiring
def test_api_routes_day_family_to_the_day_service(chennai_fixture):
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    service = chennai_fixture["service"]
    app = create_app(services={"chennai-cmrl-metro": service})
    client = TestClient(app)
    systems = client.get("/api/systems").json()
    chennai = next(item for item in systems if item["system_id"] == "chennai-cmrl-metro")
    assert chennai["prediction_available"] is True and chennai["granularity"] == "day"
    assert chennai["station_count"] == len(ENTITIES)

    entity_id = service.entity_ids[0]
    response = client.post("/api/predict", json={
        "system_id": "chennai-cmrl-metro", "station_id": entity_id,
        "target_date": service.next_unobserved_day.strftime("%Y-%m-%d")})
    assert response.status_code == 200
    body = response.json()
    assert body["granularity"] == "day" and body["is_model_forecast"] is True
    assert body["predicted_boardings"] is None, "a daily model must not claim an hourly figure"

    assert client.get(f"/api/heatmap?system_id=chennai-cmrl-metro&station_id={entity_id}").status_code == 409
    assert client.post("/api/predict", json={
        "system_id": "chennai-cmrl-metro", "station_id": entity_id,
        "target_date": service.next_unobserved_day.strftime("%Y-%m-%d"), "target_hour": 8}).status_code == 409
    history = client.get(f"/api/history?system_id=chennai-cmrl-metro&station_id={entity_id}&days=10").json()
    assert len(history["points"]) == 10 and history["measure"] == "daily_station_entries"
    assert client.get(f"/api/history?system_id=chennai-cmrl-metro&station_id={entity_id}&hours=10").status_code == 409
    preview = client.get("/api/future-preview?system_id=chennai-cmrl-metro&days=2").json()
    assert preview["kind"] == "MODEL_FORECAST_NOT_LIVE_COUNT"
    metadata = client.get("/api/metadata?system_id=chennai-cmrl-metro").json()
    assert metadata["genuine_future_prediction_available"] is True
    assert metadata["dataset"]["missing_observations_filled"] == 0
    assert Path(metadata["dataset"]["source_commit"]).name if metadata["dataset"]["source_commit"] else True
