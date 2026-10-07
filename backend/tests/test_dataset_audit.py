"""Tests for the pre-registration audit (ml/data_pipeline/audit.py).

Every fixture here is a test fixture: it exists to prove the audit tool behaves correctly, is
clearly named as such, and is never presented as data from a real operator. The important
behaviour under test is §3 of the project brief - a precomputed target column has to reproduce
the demand series shifted forward, or it loses the right to be used as ground truth.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.data_pipeline.audit import audit_csv, audit_frame, target_like_columns  # noqa: E402

TZ = "Asia/Kolkata"


def _hourly_fixture(*, correct_target: bool) -> pd.DataFrame:
    """A station-hour grid where the target column is either exactly next-hour demand or not."""
    rng = np.random.default_rng(7)
    stamps = pd.date_range("2026-01-01", periods=24 * 40, freq="h", tz=TZ)
    rows = []
    for station, base in (("CSMT", 900.0), ("DOMBIVLI", 1400.0), ("KALYAN", 1100.0)):
        values = (base * (1 + 0.25 * np.sin(np.arange(len(stamps)) / 24 * 2 * np.pi))
                  + rng.normal(0, 30, len(stamps))).round()
        for index, stamp in enumerate(stamps):
            following = values[index + 1] if index + 1 < len(values) else np.nan
            rows.append({"Date_Time": stamp.strftime("%Y-%m-%d %H:%M:%S"), "Station": station,
                         "Passengers": int(values[index]),
                         "Corridor": "Central Main",
                         "Peak_Direction": "UP" if stamp.hour < 12 else "DOWN",
                         "Data_Type": "Synthetic",
                         "Target_Next_Hour_Passengers": int(following) if correct_target and not np.isnan(following)
                         else (int(values[index] * 1.31 + 40) if not np.isnan(following) else 0)})
    return pd.DataFrame(rows)


def _slot_fixture() -> pd.DataFrame:
    """Six recurring clock times per day - deliberately not a continuous hourly series.

    Three station pairs, so each source station carries exactly one observation per slot per day.
    The 'next hour' target the fixture carries really points at the next *slot*, and at the last
    slot of a day it has no next hour inside that day: the audit has to notice that.
    """
    slots = [8, 9, 13, 16, 18, 20]
    pairs = (("VERSOVA", "DADAR"), ("DADAR", "GHATKOPAR"), ("GHATKOPAR", "VERSOVA"))
    rows = []
    for day in pd.date_range("2026-01-01", periods=30, freq="D"):
        for index, hour in enumerate(slots):
            stamp = day + pd.Timedelta(hours=hour)
            for source, destination in pairs:
                rows.append({"Timestamp": stamp.strftime("%Y-%m-%d %H:%M:%S"), "Line": "Line 1",
                             "Source_Station": source, "Destination_Station": destination,
                             "Travel_Direction": "EAST" if source < destination else "WEST",
                             "Operational_Status": "OPEN" if hour != 18 else "CROWDED",
                             "Passenger_Count": 300 + index * 10 + int(day.dayofyear),
                             "Data_Type": "Synthetic",
                             "Target_Next_Hour_Passengers": 300 + (index + 1) * 10 + int(day.dayofyear)})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ synthetic provenance
def test_a_self_declared_synthetic_file_is_reported_as_such_before_anything_else():
    report = audit_frame(_hourly_fixture(correct_target=True), timezone=TZ)
    provenance = report["provenance"]
    assert provenance["classification"] == "synthetic_development"
    column = provenance["declared_class_columns"][0]
    assert column["column"] == "Data_Type" and column["synthetic_share"] == 1.0
    assert "never be described as measured" in provenance["note"]


def test_an_observed_declaring_file_is_not_marked_synthetic():
    frame = _hourly_fixture(correct_target=True).drop(columns=["Data_Type"])
    assert audit_frame(frame, timezone=TZ)["provenance"]["classification"] == "undeclared"


# ------------------------------------------------------------------ §3 target audit
def test_a_precomputed_target_is_accepted_only_when_it_reproduces_next_period_demand():
    good = audit_frame(_hourly_fixture(correct_target=True), timezone=TZ)
    verdict = good["precomputed_targets"]["per_target"]["Target_Next_Hour_Passengers"]
    assert verdict["verdict"] == "CONSISTENT"
    assert verdict["best_alignment"] == "entity@+1"
    assert verdict["evidence"]["exact_or_within_tolerance"] == 1.0
    assert good["precomputed_targets"]["usable_as_ground_truth"] == ["Target_Next_Hour_Passengers"]

    bad = audit_frame(_hourly_fixture(correct_target=False), timezone=TZ)
    verdict = bad["precomputed_targets"]["per_target"]["Target_Next_Hour_Passengers"]
    assert verdict["verdict"] == "INCONSISTENT"
    assert bad["precomputed_targets"]["usable_as_ground_truth"] == []
    assert "NOT usable as a ground-truth label" in verdict["decision"]
    assert "Target_Next_Hour_Passengers" in bad["readiness"]["ignored_precomputed_targets"]


def test_a_target_defined_on_a_different_alignment_is_not_mistaken_for_next_hour():
    """The slot file's 'next hour' is really the next slot, and the next slot of the last hour of a
    day is tomorrow's first slot - so the claim must be judged, not assumed."""
    report = audit_frame(_slot_fixture(), timezone=TZ)
    verdict = report["precomputed_targets"]["per_target"]["Target_Next_Hour_Passengers"]
    assert verdict["verdict"] in {"INCONSISTENT", "PARTIALLY_CONSISTENT"}
    assert report["precomputed_targets"]["usable_as_ground_truth"] == []


def test_direction_segmentation_is_audited_as_a_grouping_and_not_a_novel_target():
    report = audit_frame(_hourly_fixture(correct_target=True), timezone=TZ)
    segments = report["segmentation"]["candidates"]
    assert "Peak_Direction" in segments and segments["Peak_Direction"]["role_guess"] == "direction"
    assert "Corridor" in segments
    assert segments["Corridor"]["distinct"] == 1


# ------------------------------------------------------------------ temporal structure
def test_continuous_hourly_grid_and_sparse_slot_grid_are_told_apart():
    hourly = audit_frame(_hourly_fixture(correct_target=True), timezone=TZ)["temporal"]
    assert hourly["period"]["seconds"] == 3600 and hourly["period"]["granularity"] == "hour"
    assert hourly["slots_per_entity_day"]["continuous_hours"] is True
    assert hourly["grid_cells"]["missing"] == 0

    slots = audit_frame(_slot_fixture(), timezone=TZ)["temporal"]
    assert set(slots["time_slots_present"]["slots"]) == {"08:00", "09:00", "13:00", "16:00", "18:00", "20:00"}
    # No modal sub-day period can be claimed for six recurring slots - and the audit says so, then
    # describes the structure the file really has: one observation per entity, slot and day.
    assert slots["period"] is None and "period_error" in slots
    grid = slots["candidate_grid"]
    assert grid["slots"] == ["08:00", "09:00", "13:00", "16:00", "18:00", "20:00"]
    assert grid["distinct_days"] == 30 and grid["daily_contiguous_share"] == 1.0
    assert grid["observations_per_entity_day"] == {"min": 6, "median": 6.0, "max": 6}
    assert grid["distinct_entity_day_slot_series"] == 3 * 30 * 6
    assert "same slot on a later day" in grid["implied_formulation"]
    assert "no observed series behind it" in slots["time_slot_note"]


def test_a_repeated_key_points_at_the_composite_entity_instead_of_summation():
    rows = []
    for offset in range(60):
        day = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")
        for station in ("ALANDUR", "CHENNAI CENTRAL"):
            for line, value in (("1", 1000 + offset), ("2", 2000 + offset)):
                rows.append({"Date": day, "Station": station, "Line": line, "Total": value})
    report = audit_frame(pd.DataFrame(rows), timezone=TZ)
    duplicates = report["duplicate_keys"]
    assert duplicates["duplicate_entity_timestamp_rows"] == 240
    assert "Line" in duplicates["columns_that_disambiguate_repeated_keys"]
    assert "--entity-key-columns" in duplicates["suggestion"]


def test_target_like_columns_are_found_by_shape_not_by_one_exact_name():
    frame = pd.DataFrame({"Date_Time": ["2026-01-01 00:00:00"], "Passengers": [1],
                          "target_next_hour_demand": [1], "Predicted_Next_Hour": [1], "Next_Day_Total": [1]})
    assert set(target_like_columns(frame)) == {"target_next_hour_demand", "Predicted_Next_Hour", "Next_Day_Total"}


# ------------------------------------------------------------------ CLI
def test_cli_writes_a_json_report_and_refuses_a_missing_file(tmp_path: Path):
    source = tmp_path / "fixture.csv"
    _hourly_fixture(correct_target=True).to_csv(source, index=False)
    result = subprocess.run([sys.executable, str(ROOT / "scripts/audit_demand_dataset.py"), "--csv", str(source),
                             "--json", str(tmp_path / "audit.json")], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr[-800:]
    assert "SYNTHETIC" in result.stdout.upper()
    payload = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))
    assert payload["provenance"]["classification"] == "synthetic_development"
    assert payload["precomputed_targets"]["usable_as_ground_truth"] == ["Target_Next_Hour_Passengers"]
    missing = subprocess.run([sys.executable, str(ROOT / "scripts/audit_demand_dataset.py"),
                              "--csv", str(tmp_path / "nope.csv")], capture_output=True, text=True, cwd=ROOT)
    assert missing.returncode != 0 and "file not found" in missing.stderr


def test_audit_is_read_only_and_idempotent(tmp_path: Path):
    source = tmp_path / "fixture.csv"
    frame = _hourly_fixture(correct_target=True)
    frame.to_csv(source, index=False)
    before = source.read_bytes()
    first, second = audit_csv(source), audit_csv(source)
    assert source.read_bytes() == before
    assert json.dumps(first, default=str, sort_keys=True) == json.dumps(second, default=str, sort_keys=True)
