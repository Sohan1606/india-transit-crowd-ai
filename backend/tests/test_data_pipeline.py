from __future__ import annotations
import hashlib
from pathlib import Path
import pandas as pd
import pytest

from ml.data_pipeline.cleaning import DataValidationError, clean_normalized_demand
from ml.data_pipeline.source import (
    BMRCL_DATA_SHA256, BMRCL_SYSTEM_ID, BMRCLRidershipAdapter, SourceError,
)

ROOT = Path(__file__).resolve().parents[2]


def source_record(date: str, hour: int, station: str, ridership: int) -> str:
    return f"{date};{hour};{station};{ridership}\n"


def test_pinned_bmrcl_archive_hash_coverage_and_license_are_preserved():
    path = ROOT / "data/raw/india/bmrcl-station-hourly.csv.zip"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == BMRCL_DATA_SHA256
    normalized, metadata = BMRCLRidershipAdapter().load(path)
    assert len(normalized) == 92_280
    assert normalized["system_id"].unique().tolist() == [BMRCL_SYSTEM_ID]
    assert normalized["entity_id"].nunique() == 83
    assert normalized["timestamp"].min() == pd.Timestamp("2025-08-01 00:00", tz="Asia/Kolkata")
    assert normalized["timestamp"].max() == pd.Timestamp("2025-09-30 23:00", tz="Asia/Kolkata")
    assert int(normalized["demand_count"].eq(0).sum()) == 18_200
    assert metadata["source_periods"] == [
        {"start_inclusive": "2025-08-01", "end_inclusive": "2025-08-18"},
        {"start_inclusive": "2025-09-01", "end_inclusive": "2025-09-30"},
    ]
    assert metadata["missing_hours_filled"] == 0
    assert metadata["license"] == "ODbL-1.0"
    assert "Vonter" in metadata["attribution"]
    assert (ROOT / "data/licenses/ODbL-1.0.txt").is_file()
    assert (ROOT / "data/licenses/BMRCL-ATTRIBUTION.md").is_file()


def test_adapter_keeps_reported_zero_and_does_not_fill_absent_station_hours(tmp_path):
    path = tmp_path / "tiny.csv"
    path.write_text(
        "Date;Hour;Station;Ridership\n"
        + source_record("2025-08-01", 0, "Central", 0)
        + source_record("2025-08-01", 2, "Central", 11),
        encoding="utf-8",
    )
    normalized, metadata = BMRCLRidershipAdapter().load(path)
    assert normalized["demand_count"].tolist() == [0, 11]
    assert normalized["timestamp"].dt.tz is not None
    assert normalized["timestamp"].dt.tz_convert("Asia/Kolkata").dt.hour.tolist() == [0, 2]
    assert len(normalized) == 2  # 01:00 remains absent; it is not turned into a zero row.
    assert metadata["missing_hours_filled"] == 0


def test_adapter_fails_closed_on_schema_invalid_values_and_duplicate_keys(tmp_path):
    bad_schema = tmp_path / "bad-schema.csv"
    bad_schema.write_text("Date,Hour,Station,Ridership\n2025-08-01,8,Central,1\n", encoding="utf-8")
    with pytest.raises(SourceError, match="schema changed"):
        BMRCLRidershipAdapter().load(bad_schema)

    negative = tmp_path / "negative.csv"
    negative.write_text("Date;Hour;Station;Ridership\n" + source_record("2025-08-01", 8, "Central", -1), encoding="utf-8")
    with pytest.raises(SourceError, match="invalid rows"):
        BMRCLRidershipAdapter().load(negative)

    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text(
        "Date;Hour;Station;Ridership\n"
        + source_record("2025-08-01", 8, "Central", 1)
        + source_record("2025-08-01", 8, "Central", 2),
        encoding="utf-8",
    )
    with pytest.raises(SourceError, match="duplicate station-hour"):
        BMRCLRidershipAdapter().load(duplicate)


def test_normalized_validation_preserves_gaps_zeros_and_local_timezone():
    path = ROOT / "data/processed/namma_metro_station_hourly.csv"
    normalized, quality = clean_normalized_demand(pd.read_csv(path))
    assert len(normalized) == 92_280
    assert normalized["timestamp"].dt.tz is not None
    assert normalized["timestamp"].dt.tz_convert("Asia/Kolkata").dt.hour.between(0, 23).all()
    assert int(normalized["demand_count"].eq(0).sum()) == 18_200
    assert quality["missing_observations_filled"] == 0
    assert not normalized.duplicated(["system_id", "entity_id", "timestamp"]).any()


def test_normalized_validation_rejects_bad_time_negative_demand_and_duplicate_keys():
    base = {
        "system_id": BMRCL_SYSTEM_ID, "city": "Bengaluru", "mode": "METRO", "operator": "BMRCL",
        "entity_id": "central", "entity_name": "Central", "entity_type": "STATION",
        "timestamp": pd.Timestamp("2025-01-01 08:00", tz="Asia/Kolkata"),
        "demand_count": 0, "measure": "hourly_station_boardings", "source_id": "test",
    }
    assert clean_normalized_demand(pd.DataFrame([base]))[0]["demand_count"].iloc[0] == 0
    with pytest.raises(DataValidationError, match="aligned to the start of a clock hour"):
        clean_normalized_demand(pd.DataFrame([{**base, "timestamp": pd.Timestamp("2025-01-01 08:30", tz="Asia/Kolkata")}]))
    with pytest.raises(DataValidationError, match="non-negative"):
        clean_normalized_demand(pd.DataFrame([{**base, "demand_count": -3}]))
    with pytest.raises(DataValidationError, match="Duplicate entity-hour"):
        clean_normalized_demand(pd.DataFrame([base, base]))
    with pytest.raises(DataValidationError, match="empty"):
        clean_normalized_demand(pd.DataFrame())
