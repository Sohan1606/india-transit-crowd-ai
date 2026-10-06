from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
from ml.data_pipeline.source import BMRCL_SYSTEM_ID
from ml.features.forecasting import FEATURE_COLUMNS, TARGET, build_supervised_frame, features_for_target


def series_frame(periods: int = 420) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=periods, freq="h", tz="Asia/Kolkata")
    return pd.DataFrame({
        "system_id": BMRCL_SYSTEM_ID, "city": "Bengaluru", "mode": "METRO", "operator": "BMRCL",
        "entity_id": "test-station", "entity_name": "Test Station", "entity_type": "STATION",
        "timestamp": index, "demand_count": np.arange(periods, dtype=float),
        "measure": "hourly_station_boardings", "source_id": "synthetic-test-only",
    })


def test_lag_and_rolling_values_are_target_relative_and_correct_in_ist():
    hourly = series_frame()
    frame = build_supervised_frame(hourly)
    target = pd.Timestamp("2025-01-08 00:00:00", tz="Asia/Kolkata")
    row = frame.loc[frame["timestamp"].eq(target)].iloc[0]
    assert row["lag_1"] == 167
    assert row["lag_24"] == 144
    assert row["lag_168"] == 0
    assert row["same_hour_previous_day"] == 144
    assert row["same_hour_previous_week"] == 0
    assert row["rolling_mean_3"] == pytest.approx(np.mean([165, 166, 167]))
    assert row["rolling_mean_24"] == pytest.approx(np.mean(np.arange(144, 168)))
    assert row["rolling_mean_168"] == pytest.approx(np.mean(np.arange(168)))
    assert row[TARGET] == 168
    assert row["hour"] == 0
    assert str(row["timestamp"].tz) == "Asia/Kolkata"


def test_feature_schema_excludes_target_and_is_reproducible():
    assert len(FEATURE_COLUMNS) == 18
    assert TARGET not in FEATURE_COLUMNS
    assert "entity_id" in FEATURE_COLUMNS
    assert all(column in build_supervised_frame(series_frame()).columns for column in FEATURE_COLUMNS)


def test_future_perturbation_cannot_change_earlier_forecast_features():
    hourly = series_frame()
    target = pd.Timestamp("2025-01-15 12:00:00", tz="Asia/Kolkata")
    original = features_for_target(hourly, "test-station", target)
    mutated = hourly.copy()
    mutated.loc[mutated["timestamp"] >= target, "demand_count"] += 1_000_000
    after = features_for_target(mutated, "test-station", target)
    pd.testing.assert_frame_equal(original[FEATURE_COLUMNS], after[FEATURE_COLUMNS])
    assert original["timestamp"].iloc[0] == target


def test_feature_engineering_drops_windows_around_missing_hours_instead_of_fabricating():
    hourly = series_frame(600).drop(index=300).reset_index(drop=True)
    frame = build_supervised_frame(hourly)
    missing = pd.Timestamp("2025-01-13 12:00:00", tz="Asia/Kolkata")
    assert not frame["timestamp"].between(missing, missing + pd.Timedelta(hours=167)).any()
    assert frame["timestamp"].min() == pd.Timestamp("2025-01-08 00:00:00", tz="Asia/Kolkata")
    assert not frame.isna().any().any()
