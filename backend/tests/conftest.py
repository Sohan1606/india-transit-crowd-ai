from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
from ml.training.train import train_and_save
from backend.app.inference.service import TransitInferenceService
from ml.data_pipeline.source import BMRCL_SYSTEM_ID


@pytest.fixture(scope="session")
def training_fixture(tmp_path_factory):
    """Seeded synthetic *test-only* station series; never shipped or used as the India model."""
    root = tmp_path_factory.mktemp("india-test-model")
    index = pd.date_range("2025-01-01", periods=24 * 76, freq="h", tz="Asia/Kolkata")
    rng = np.random.default_rng(812)
    rows = []
    station_names = ["Test Station One", "Test Station Two", "Test Station Three", "Test Station Four"]
    for station_index, station_name in enumerate(station_names):
        station_id = f"test-station-{station_index + 1}"
        for timestamp in index:
            hour_wave = 42 * np.sin(2 * np.pi * (timestamp.hour - 6) / 24)
            weekly_wave = 18 * np.cos(2 * np.pi * timestamp.dayofweek / 7)
            weekend_shift = -22 if timestamp.dayofweek >= 5 else 0
            demand = 0.0 if station_index == 3 else max(0.0, 95 + 26 * station_index + hour_wave + weekly_wave + weekend_shift + rng.normal(0, 6))
            rows.append({
                "system_id": BMRCL_SYSTEM_ID,
                "city": "Bengaluru",
                "mode": "METRO",
                "operator": "BMRCL",
                "entity_id": station_id,
                "entity_name": station_name,
                "entity_type": "STATION",
                "timestamp": timestamp,
                "demand_count": int(round(demand)),
                "measure": "hourly_station_boardings",
                "source_id": "synthetic-test-only",
            })
    hourly = pd.DataFrame(rows)
    data_path = root / "synthetic_test_only_hourly.csv"
    hourly.to_csv(data_path, index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    model_dir = root / "models" / BMRCL_SYSTEM_ID
    report = train_and_save(hourly, model_dir, {
        "source_title": "Seeded synthetic test fixture only",
        "source": "test fixture; never production or shipped model data",
        "license": "test-generated",
    })
    service = TransitInferenceService(model_dir / "transitcrowd.joblib", data_path)
    return {"root": root, "hourly": hourly, "data_path": data_path, "report": report, "service": service}
