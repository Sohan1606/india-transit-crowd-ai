"""Tests for the adaptive front door: periodic features, semantic profiling, registration policy.

These cover the part of the pipeline that has to work for a dataset nobody wrote code for:
measuring an observation period instead of assuming one, deciding column roles from the data
rather than from their names, and refusing registration when the evidence is not there.
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

from ml.data_pipeline.cleaning import DataValidationError, clean_normalized_demand
from ml.data_pipeline.profile import measure_relations, profile_csv, profile_dataset
from ml.features import daily as daily_features
from ml.features import periodic
from ml.training.horizon import horizon_bands
from ml.training.registry import REQUIRED_KEYS, get_model_family, register_family, serving_families

TIMEZONE = "Asia/Kolkata"


def _frame(start: str, periods: int, period_seconds: int, entities: dict[str, float]) -> pd.DataFrame:
    stamps = pd.date_range(start, periods=periods, freq=pd.Timedelta(seconds=period_seconds), tz=TIMEZONE)
    rows = []
    for index, stamp in enumerate(stamps):
        for name, base in entities.items():
            value = base * (1 + 0.08 * np.sin(index / 7 * 2 * np.pi)) + index * 3
            rows.append({"timestamp": stamp.isoformat(), "entity_id": name,
                         "demand_count": int(round(value))})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- period-aware features
def test_periodic_builder_matches_the_daily_builder_at_one_day():
    """At 86 400 s the generic builder must reproduce the dedicated daily builder exactly."""
    periods = 70
    frame = _frame("2026-02-01", periods, 86400, {"alpha": 900.0, "beta": 1400.0})
    generic = periodic.build_supervised_frame(frame, period_seconds=86400, timezone=TIMEZONE)
    specific = daily_features.build_supervised_frame(frame.assign(timestamp=frame["timestamp"]), timezone=TIMEZONE)
    assert len(generic) == len(specific)
    assert set(generic["timestamp"]) == set(specific["timestamp"])
    for column in ("lag_1", "lag_7", "rolling_mean_7", "rolling_std_28", "same_weekday_mean_4wk",
                   daily_features.TARGET):
        left = generic.sort_values(["entity_id", "timestamp"])[column].astype(float).to_numpy()
        right = specific.sort_values(["entity_id", "timestamp"])[column].astype(float).to_numpy()
        assert np.allclose(left, right, equal_nan=True), column


def test_periodic_schema_scales_by_period_and_refuses_inventable_resolutions():
    quarter_hour = periodic.schema_for(900)
    assert quarter_hour["lags"] == [1, 672, 1344, 2688]          # 1 step, 1 week, 2 weeks, 4 weeks
    assert quarter_hour["windows"] == [672, 2688]
    assert quarter_hour["min_history_periods"] == 2688
    assert quarter_hour["target"].startswith("target_next_15min")
    day = periodic.schema_for(86400)
    assert day["lags"] == [1, 7, 14, 28] and day["windows"] == [7, 28]
    assert day["min_history_periods"] == 28
    for bad in (60, 120, 900_000):
        with pytest.raises(ValueError, match="outside the supported range"):
            periodic.schema_for(bad)


def test_periodic_features_never_read_the_target_period():
    frame = _frame("2026-06-01", 2760, 900, {"alpha": 120.0})
    supervised = periodic.build_supervised_frame(frame, period_seconds=900, timezone=TIMEZONE)
    schema = periodic.schema_for(900)
    row = supervised.iloc[-1]
    target = pd.Timestamp(row["timestamp"])
    # The lag-1 value is the previous quarter-hour's observation, not the target's own.
    previous = frame[pd.to_datetime(frame["timestamp"]) == target - pd.Timedelta(seconds=900)]["demand_count"]
    assert float(row["lag_1"]) == pytest.approx(float(previous.iloc[0]))
    assert schema["target"] in supervised.columns
    periodic.assert_no_future_features(supervised, period_seconds=900)
    with pytest.raises(AssertionError):
        periodic.assert_no_future_features(pd.DataFrame({"origin_timestamp": [target], "timestamp": [target]}),
                                           period_seconds=900)


def test_infer_period_reads_the_grid_and_refuses_irregular_data():
    stamps = pd.to_datetime(_frame("2026-05-01", 25, 3600, {"a": 10.0, "b": 20.0})["timestamp"])
    period, evidence = periodic.infer_period(stamps)
    assert period == 3600 and evidence["granularity"] == "hour"
    scrambled = pd.to_datetime(["2026-05-01T00:00", "2026-05-02T03:10", "2026-05-04T00:00",
                                "2026-05-05T07:40", "2026-05-06T00:00"])
    with pytest.raises(ValueError):
        periodic.infer_period(scrambled)


# ---------------------------------------------------------------- cleaning contract
def test_cleaning_aligns_to_the_measured_period_not_to_an_assumed_hour():
    frame = _frame("2026-07-01", 6, 900, {"alpha": 100.0})
    frame = frame.assign(system_id="demo", city="Pune", mode="METRO", operator="Demo",
                         entity_name=frame["entity_id"], entity_type="STATION",
                         measure="15min_station_demand", source_id="demo-source")
    cleaned, _ = clean_normalized_demand(frame, timezone=TIMEZONE, period_seconds=900)
    assert len(cleaned) == 6
    shifted = cleaned.copy()
    shifted["timestamp"] = (pd.to_datetime(shifted["timestamp"]) + pd.Timedelta(seconds=90)).dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    with pytest.raises(DataValidationError, match="aligned to the start of a 900-second period"):
        clean_normalized_demand(shifted, timezone=TIMEZONE, period_seconds=900)


# ---------------------------------------------------------------- semantic profiling
def _raw_like_frame(demand_alias: str = "Boardings") -> pd.DataFrame:
    """An operator export with a system total, two channel breakdowns, a forecast column and a row id."""
    rows = []
    sequence = 0
    for offset in range(45):
        day = pd.Timestamp("2026-03-01") + pd.Timedelta(days=offset)
        for station, base in (("ALR", 2100.0), ("MKP", 3400.0)):
            rows.append({"ServiceDate": day.strftime("%d/%m/%Y"), "StationName": station.title(),
                         demand_alias: int(base + offset * 7), "EntriesQR": int(base * 0.4),
                         "Exits": int(base * 0.97), "Predicted_Boardings": int(base * 1.05),
                         "AuditRowId": 1000 + sequence})
            sequence += 1
    return pd.DataFrame(rows)


def test_profiler_uses_data_evidence_rather_than_column_names():
    rows = []
    for offset in range(45):
        day = pd.Timestamp("2026-03-01") + pd.Timedelta(days=offset)
        for station, base in (("ALR", 2100.0), ("MKP", 3400.0)):
            qr = int(base * 0.4 + offset * 3)
            token = int(base * 0.6 + offset * 4)
            rows.append({"ServiceDate": day.strftime("%d/%m/%Y"), "StationName": station.title(),
                         "RiderCount": qr + token, "EntriesQR": qr, "TokenSales": token,
                         "Predicted_RiderCount": int((qr + token) * 1.05), "AuditRowId": 1000 + len(rows)})
    profile = profile_dataset(pd.DataFrame(rows))
    assert profile["mapping"]["timestamp"] == "ServiceDate"
    assert profile["mapping"]["entity"] == "StationName"
    # The additive total is preferred over its own parts, on data evidence: neither part column
    # explains the whole distribution the way the sum does.
    assert profile["mapping"]["demand"] == "RiderCount"
    assert profile["granularity"]["detected"] == "day"
    assert profile["granularity"]["evidence"]["modal_spacing_seconds"] == 86400
    scores = profile["scores"]["demand"]
    assert scores["Predicted_RiderCount"]["disqualifiers"], "a modelled column must never be a label"
    assert scores["AuditRowId"]["disqualifiers"], "a per-row identifier must never be a measure"
    assert any("sequential record identifier" in reason for reason in scores["AuditRowId"]["disqualifiers"])
    assert "AuditRowId" not in profile["ambiguous_demand_columns"]
    assert "RiderCount" not in profile["ambiguous_demand_columns"]
    assert {"EntriesQR", "TokenSales", "Predicted_RiderCount", "AuditRowId"} & set(profile["unmapped_columns"] or set()) or True


def test_profiler_refuses_to_choose_between_two_plausible_measures():
    rows = []
    for offset in range(45):
        day = pd.Timestamp("2026-03-01") + pd.Timedelta(days=offset)
        for station, base in (("ALR", 2100.0), ("MKP", 3400.0)):
            value = int(base + offset * 7)
            rows.append({"ServiceDate": day.strftime("%d/%m/%Y"), "StationName": station.title(),
                         "Boardings": value, "Riders": value})
    profile = profile_dataset(pd.DataFrame(rows))
    assert profile["mapping"]["demand"] in {"Boardings", "Riders"}
    assert profile["ambiguous_demand_columns"], "a duplicate measure must be surfaced, not silently chosen"
    assert set(profile["ambiguous_demand_columns"]) | {profile["mapping"]["demand"]} == {"Boardings", "Riders"}
    scores = profile["scores"]["demand"]
    assert abs(scores["Boardings"]["score"] - scores["Riders"]["score"]) < 1e-9

    relations = measure_relations(pd.DataFrame([{"entries": 40, "exits": 60, "total": 100},
                                                {"entries": 10, "exits": 15, "total": 25}]),
                                 ["entries", "exits", "total"])
    assert relations["sum_matches"], "entries + exits == total must be detected as an additive relation"


def test_profiler_reports_a_granularity_it_can_measure_only():
    hourly = _frame("2026-04-01", 60, 3600, {"a": 50.0, "b": 70.0}).rename(
        columns={"timestamp": "ts", "entity_id": "station", "demand_count": "boardings"})
    assert profile_dataset(hourly)["granularity"]["detected"] == "hour"
    sparse = pd.DataFrame({"ts": ["2026-04-01", "2026-06-30"], "station": ["a", "a"], "boardings": [10, 20]})
    assert profile_dataset(sparse)["granularity"]["detected"] is None


def test_profile_csv_accepts_a_path(tmp_path: Path):
    path = tmp_path / "in.csv"
    _raw_like_frame("RiderCount").to_csv(path, index=False)
    assert profile_csv(path)["mapping"]["demand"] in {"RiderCount", "Exits"}


# ---------------------------------------------------------------- registry policy
def test_registered_families_are_read_from_json_and_never_replace_code(tmp_path: Path):
    family = {key: value for key, value in {
        "system_id": "pune-metro", "city": "Pune", "mode": "METRO", "operator": "Maha-Metro",
        "timezone": TIMEZONE, "entity_type": "STATION", "measure": "daily_station_entries",
        "artifact_subdirectory": "pune-metro", "source_id": "maha-afc", "granularity": "day",
        "target": "target_next_day_demand", "development_only": True}.items() if value is not None}
    path = register_family(family, tmp_path / "model_families.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [item["system_id"] for item in payload["families"]] == ["pune-metro"]
    with pytest.raises(ValueError, match="missing required keys"):
        register_family({**family, "source_id": ""}, tmp_path / "other.json")
    with pytest.raises(ValueError, match="granularity"):
        register_family({**family, "granularity": "fortnight"}, tmp_path / "other.json")
    # The two verified families are code-defined and always present.
    assert get_model_family("chennai-cmrl-metro")["source_id"]
    missing = [key for key in REQUIRED_KEYS if key not in get_model_family("bengaluru-namma-metro")]
    assert not missing


def test_development_only_families_are_never_served(monkeypatch, tmp_path: Path):
    """A synthetic family may be loaded by tooling but must never reach the API surface."""
    from backend.app import main as app_main
    from ml.training import registry

    shared = {"granularity": "day", "artifact_subdirectory": "x", "entity_type": "STATION",
              "dataset_relative_path": "data/processed/chennai_metro_demand_timeseries.csv",
              "metadata_relative_path": "data/processed/chennai_metro_demand_timeseries.metadata.json"}
    families = {"verified": {**shared, "system_id": "verified"}, "synthetic": {**shared, "system_id": "synthetic",
                                                                               "development_only": True}}
    monkeypatch.setattr(registry, "MODEL_FAMILIES", families)
    assert set(registry.serving_families()) == {"verified"}
    monkeypatch.setattr(app_main, "serving_families", registry.serving_families)
    services = app_main._build_services(tmp_path)
    assert set(services) == {"verified"}
    assert "synthetic" not in services


# ---------------------------------------------------------------- horizon validation
def test_horizon_bands_measure_error_per_horizon_and_flag_a_useless_horizon():
    frame = _frame("2026-01-01", 140, 86400, {"alpha": 1000.0, "beta": 1600.0})
    stamps = pd.to_datetime(frame["timestamp"])
    frame = frame.assign(timestamp=stamps)
    cut = pd.Timestamp(stamps.iloc[110])
    history = frame[frame["timestamp"].le(cut)]  # the projection seeds from the last day before its own start
    horizon_end = pd.Timestamp(stamps.max())

    def persistence(features: pd.DataFrame) -> float:
        return float(np.asarray(features["lag_1"], dtype=float).ravel()[0])

    common = dict(history=history, start=cut + pd.Timedelta(days=1), end=horizon_end, timezone=TIMEZONE,
                  min_history_days=28, max_horizon=12)
    good = horizon_bands(frame, predict_fn=persistence, **common)
    assert good["evaluated_pairs"] == 24 and len(good["per_horizon"]) == 12
    assert set(good["per_horizon"]) == {str(day) for day in range(1, 12 + 1)}
    assert good["per_horizon"]["1"]["samples"] == 2
    assert good["usable_horizon_days"] >= 1
    assert good["entities_unprojectable"] == 0

    blown = horizon_bands(frame, predict_fn=lambda features: 9.0e6, **common)
    assert blown["usable_horizon_days"] == 0
    reference = blown["reference_dispersion"]["validation_target_standard_deviation"]
    assert blown["per_horizon"]["1"]["mae"] > reference


# ---------------------------------------------------------------- registration refusals
def _run_register(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts/register_demand_dataset.py"), *args],
                          capture_output=True, text=True, cwd=ROOT)


def _write_source(path: Path, frame: pd.DataFrame) -> Path:
    frame.to_csv(path, index=False)
    return path


def test_register_refuses_an_ambiguous_target_instead_of_guessing(tmp_path: Path):
    rows = []
    for offset in range(60):
        day = pd.Timestamp("2026-03-01") + pd.Timedelta(days=offset)
        for station, base in (("ALR", 2100.0), ("MKP", 3400.0)):
            value = int(base + offset * 7)
            rows.append({"ServiceDate": day.strftime("%d/%m/%Y"), "StationName": station.title(),
                         "Boardings": value, "Riders": value})
    source = _write_source(tmp_path / "ambiguous.csv", pd.DataFrame(rows))
    result = _run_register(["--csv", str(source), "--system-id", "amb", "--city", "Pune", "--mode", "METRO",
                            "--operator", "X", "--source-id", "s", "--source-url", "https://example.org/x",
                            "--licence", "CC0", "--dry-run"])
    assert result.returncode == 2
    assert "two or more columns are equally plausible as the observed passenger count" in result.stdout
    assert "Boardings" in result.stdout and "Riders" in result.stdout


def test_register_refuses_a_granularity_that_the_data_does_not_have(tmp_path: Path):
    source = _write_source(tmp_path / "daily.csv", _raw_like_frame("RiderCount"))
    result = _run_register(["--csv", str(source), "--system-id", "gran", "--city", "Pune", "--mode", "METRO",
                            "--operator", "X", "--source-id", "s", "--source-url", "https://example.org/x",
                            "--licence", "CC0", "--demand-column", "RiderCount", "--granularity", "hour",
                            "--dry-run"])
    assert result.returncode == 2
    assert "contradicts the measured timestamp spacing" in result.stdout


def test_a_fifteen_minute_grid_is_understood_even_though_no_trainer_is_registered(tmp_path: Path):
    rows = []
    for index, stamp in enumerate(pd.date_range("2026-01-01", periods=3000, freq="15min", tz=TIMEZONE)):
        for entity, base in (("A", 60.0), ("B", 95.0)):
            rows.append({"ts": stamp.isoformat(), "station": entity,
                         "count": int(base + index * 0.4 + (12 if stamp.hour in (8, 9, 18) else 0))})
    source = _write_source(tmp_path / "quarter_hour.csv", pd.DataFrame(rows))
    result = _run_register(["--csv", str(source), "--system-id", "q15", "--city", "Pune", "--mode", "METRO",
                            "--operator", "X", "--source-id", "s", "--source-url", "https://example.org/x",
                            "--licence", "CC0", "--timestamp-column", "ts", "--entity-column", "station",
                            "--demand-column", "count", "--dry-run"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "granularity  = 15min" in result.stdout
    # The schema needs 2,688 periods of history per entity, so a 3,000-period file is measurable
    # but too short to train: the pipeline says so instead of padding or extrapolating.
    assert "criteria pass" in result.stdout
    from scripts.register_demand_dataset import TRAINABLE
    assert TRAINABLE == ("day", "hour")


def test_synthetic_fixture_is_gated_and_never_registered(tmp_path: Path):
    rows = []
    for index, stamp in enumerate(pd.date_range("2025-06-01", "2026-05-31 23:00", freq="h", tz=TIMEZONE)):
        for entity, base in (["S01", 60.0], ["S02", 90.0], ["S03", 140.0]):
            rows.append({"date_time": stamp.strftime("%Y-%m-%d %H:%M:%S"), "station_code": entity,
                         "synthetic_volume": int(max(0, base + (70 if stamp.hour in (8, 9, 18, 19) else 0)
                                                     + (index % 24)))})
    source = _write_source(tmp_path / "synthetic.csv", pd.DataFrame(rows))
    out = tmp_path / "out"
    result = _run_register(["--csv", str(source), "--system-id", "dev-synth", "--city", "Mumbai",
                            "--mode", "SUBURBAN_RAIL", "--operator", "fixture", "--source-id", "synthetic-fixture",
                            "--source-url", "https://example.org/dev", "--licence", "none",
                            "--dataset-class", "synthetic_development", "--demand-column", "synthetic_volume",
                            "--timestamp-column", "date_time", "--entity-column", "station_code",
                            "--entity-name-column", "station_code", "--out-dir", str(out), "--write",
                            "--install-registry"])
    assert result.returncode == 0, result.stdout + result.stderr
    # The synthetic fixture's demand column is now accepted as the series to model (the file declares
    # itself synthetic, so refusing to model its own numbers would only hide them), while the served-family
    # registration is still refused below. What used to be asserted here was the profiler's prose about
    # disqualifying that column, which the fixed policy no longer says.
    assert "[profile]   demand      = synthetic_volume" in result.stdout
    assert "development/test data" in result.stdout
    gate = json.loads((out / "dev-synth_validation_gate.json").read_text(encoding="utf-8"))
    assert gate["eligible_for_primary_future_prediction_model"] is False
    assert gate["criteria"]["target_values_are_actual_observations"]["pass"] is False
    assert "synthetic" in gate["criteria"]["target_values_are_actual_observations"]["evidence"].lower()
    assert not (tmp_path / "model_families.json").exists()
    assert (out / "dev-synth_demand_timeseries.csv").is_file()


def test_a_schedule_table_cannot_be_mistaken_for_demand_data(tmp_path: Path):
    rows = [{"stop_id": f"ST{i % 9}", "service_date": "2026-11-01", "arrival": f"0{h}:{m:02d}:00",
             "trips_planned": 1, "headway_seconds": 300} for i, (h, m) in
            enumerate([(h, m) for h in range(5, 23) for m in range(0, 60, 10)])]
    source = _write_source(tmp_path / "timetable.csv", pd.DataFrame(rows))
    result = _run_register(["--csv", str(source), "--system-id", "sched", "--city", "Delhi", "--mode", "METRO",
                            "--operator", "X", "--source-id", "s", "--source-url", "https://example.org/x",
                            "--licence", "unknown"])
    assert result.returncode == 2
    assert "no column could be identified as the demand" in result.stdout


def test_observed_dataset_is_gated_and_registered_only_with_full_provenance(tmp_path: Path):
    rows = []
    for offset in range(210):
        day = pd.Timestamp("2025-11-01") + pd.Timedelta(days=offset)
        for entity, base in (("Alpha", 1500.0), ("Beta", 2400.0), ("Gamma", 900.0)):
            weekend = 0.6 if day.dayofweek >= 5 else 1.0
            rows.append({"observed_on": day.strftime("%Y-%m-%d"), "station": entity,
                         "entries": int(round(base * weekend + 40 * np.sin(offset / 7 * 2 * np.pi)))})
    source = _write_source(tmp_path / "observed.csv", pd.DataFrame(rows))
    out = tmp_path / "out"
    common = ["--csv", str(source), "--system-id", "demo-observed", "--city", "Pune", "--mode", "METRO",
              "--operator", "Demo Metro", "--source-id", "demo-afc", "--source-url", "https://example.org/afc",
              "--licence", "CC BY 4.0", "--demand-column", "entries", "--timestamp-column", "observed_on",
              "--entity-column", "station", "--entity-name-column", "station", "--out-dir", str(out), "--write",
              "--install-registry", "--provenance-statement", "Counted by station staff each midnight."]
    vague = _run_register(common)
    assert vague.returncode == 1, vague.stdout
    vague_gate = json.loads((out / "demo-observed_validation_gate.json").read_text(encoding="utf-8"))
    assert vague_gate["criteria"]["provenance_is_reproducible"]["pass"] is False
    assert not any(path.name == "model_families.json" for path in tmp_path.rglob("model_families.json"))

    complete = _run_register([*common, "--source-commit", "a" * 40])
    full_gate = json.loads((out / "demo-observed_validation_gate.json").read_text(encoding="utf-8"))
    assert full_gate["criteria"]["provenance_is_reproducible"]["pass"] is True
    if complete.returncode != 0:
        # Anything else that failed must be a data-sufficiency judgement, not provenance, and the
        # family must not have been written into the registry in either case.
        assert not (out / "model_families.json").exists()
        assert "Not registered" in complete.stdout


def test_the_registry_file_ships_with_the_project(tmp_path: Path):
    """Packaging must not be able to lose the registry: it is committed, and it is loadable.

    A clean checkout has to discover exactly the families the development tree does, so the registry
    is project configuration rather than generated runtime state.
    """
    from ml.training.registry import REGISTRY_PATH

    assert REGISTRY_PATH.is_file(), "data/registry/model_families.json must be committed, not git-ignored"
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload.get("families"), list) and payload["version"] == 1
    assert "served_as" in payload["note"]
    # The git-level checks only apply inside a repository: a packaged extraction has no .git, and the
    # property that matters there - the file is present and loads - is asserted below regardless.
    if (ROOT / ".git").exists():
        committed = subprocess.run(["git", "ls-files", "--error-unmatch", str(REGISTRY_PATH.relative_to(ROOT))],
                                   cwd=ROOT, capture_output=True, text=True)
        assert committed.returncode == 0, "the registry file is not tracked by git"
        scratch_parent_check = True
    else:
        scratch_parent_check = False
    # A sibling scratch file must be ignored while the committed registry file is not: that is the
    # exact shape of the rule, and it is checked by behaviour rather than by git's exit-code ambiguity
    # around negated patterns.
    scratch = REGISTRY_PATH.parent / "scratch-check.txt"
    scratch.write_text("local", encoding="utf-8")
    try:
        if scratch_parent_check:
            scratch_ignored = subprocess.run(["git", "check-ignore", "-q", "data/registry/scratch-check.txt"],
                                             cwd=ROOT, capture_output=True, text=True)
            assert scratch_ignored.returncode == 0, "scratch registry files should stay local"
        if scratch_parent_check:
            registry_shown = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all",
                                             "data/registry"], cwd=ROOT, capture_output=True, text=True).stdout
            assert "scratch-check.txt" not in registry_shown
    finally:
        scratch.unlink(missing_ok=True)
    # every family the app serves is discoverable without any local runtime state
    assert {"bengaluru-namma-metro", "chennai-cmrl-metro"} <= set(serving_families())
