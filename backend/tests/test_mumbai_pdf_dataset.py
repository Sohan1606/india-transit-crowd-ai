"""Tests for the Mumbai suburban-rail PDF extract: provenance, honesty of claims, and quarantine.

These tests guard three commitments made in the research brief:
1. every observed value carries a page and table citation and matches the canonical schema;
2. the extract never claims more time depth than the document actually contains;
3. the study's 2016/2021/2031 modelled forecasts are stored apart, flagged unusable as
   labels, and never read by a training or feature code path.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ml.data_pipeline.mumbai_pdf import (  # noqa: E402
    NETWORK_CONTEXT, PEAK_HOURS, SURVEY_PERIODS, PdfParseError, _close, _int, _numbers, collapsed, parse_pdf,
)

RESEARCH = ROOT / "data/research"
OBSERVED_CSV = RESEARCH / "mumbai_suburban_rail_pdf_observed.csv"
OBSERVED_META = RESEARCH / "mumbai_suburban_rail_pdf_observed.metadata.json"
MODELLED_CSV = RESEARCH / "mumbai_suburban_rail_MODELLED_od_forecast.csv"
PDF_PATH = ROOT.parent / "uploads" / "ExecutiveSummarywilber FINAL.pdf"

CANONICAL = ["system_id", "city", "mode", "operator", "line", "station_id", "station_name", "direction",
             "service_type", "survey_period_start", "survey_period_end", "time_interval", "demand_count",
             "measure", "observation_type", "source_page", "source_table", "provenance"]


def _extractor():
    path = ROOT / "scripts/extract_mumbai_pdf_surveys.py"
    spec = importlib.util.spec_from_file_location("extract_mumbai_pdf_surveys", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if not OBSERVED_CSV.exists():  # the extract is regenerable, so CI must not fail without it
    pytest.skip(
        "data/research/mumbai_suburban_rail_pdf_observed.csv is absent; regenerate it with "
        "python3 scripts/extract_mumbai_pdf_surveys.py --pdf <path to the MRVC executive summary>",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def observed() -> pd.DataFrame:
    return pd.read_csv(OBSERVED_CSV)


@pytest.fixture(scope="module")
def metadata() -> dict:
    return json.loads(OBSERVED_META.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ canonical contract
def test_observed_extract_carries_the_canonical_columns_and_citations(observed):
    assert set(CANONICAL).issubset(observed.columns)
    assert len(observed) > 0
    assert set(observed["system_id"]) == {"mumbai-suburban-railway"}
    assert set(observed["city"]) == {"Mumbai"}
    assert set(observed["mode"]) == {"SUBURBAN_RAIL"}
    assert observed["source_page"].between(1, 38).all()
    citations = observed["source_table"].astype(str)
    assert citations.str.match(r"((Table|Figure) E-\d+|Narrative [ivx]+)$").all(), \
        "citations must be one controlled form so rows group by source table"
    assert (pd.to_numeric(observed["demand_count"], errors="coerce") > 0).all()
    assert observed["measure"].notna().all() and observed["observation_type"].notna().all()


def test_absent_fields_stay_null_instead_of_being_invented(observed):
    station_rows = observed[observed["measure"].eq("station_entries_plus_exits_14h")]
    # A station 14-hour total is a whole-day, both-direction figure: the report prints no
    # service-type split and no per-train direction for it, so those fields stay NULL while
    # direction is stated as BOTH because that is what the measure counts.
    assert set(station_rows["direction"]) == {"BOTH"}
    assert set(station_rows["service_type"]) == {"ALL"}
    # Controlled vocabularies, with the report's own wording preserved beside them.
    assert set(observed["direction"]) <= {"UP", "DOWN", "BOTH"}
    assert set(observed["service_type"].dropna()) <= {"ALL", "SLOW", "FAST", "SLOW_AND_FAST",
                                                     "MAIN_HARBOUR", "TRANS_HARBOUR"}
    free_text = observed.loc[observed["direction_source_label"].notna(), "direction"]
    assert set(free_text) <= {"UP", "DOWN"}
    assert observed["time_interval"].notna().all()


def test_survey_periods_are_recorded_as_periods_not_single_days(metadata):
    periods = metadata["survey_periods"]
    assert len(periods) == len(SURVEY_PERIODS) == 5
    blank_dates = []
    for name, period in periods.items():
        start, end = period.get("start"), period.get("end")
        if start is None and end is None:
            blank_dates.append(name)
            assert period["exclusions"], "an absent date must be explained, not silently blank"
            continue
        assert re.match(r"\d{4}-\d{2}-\d{2}", str(start)) and re.match(r"\d{4}-\d{2}-\d{2}", str(end))
        assert str(start) <= str(end), name
    assert blank_dates == ["alighting_distribution"], "Table E-1 leaves that survey's date cell empty"
    blob = json.dumps(periods)
    assert "23/12/2011" in blob and "02/01/2012" in blob, "the documented no-survey window must be carried"


# ------------------------------------------------------------------ honesty of claims
def test_time_depth_is_reported_as_a_cross_section(metadata, observed):
    depth = metadata["time_depth"]
    assert depth["records"] == len(observed)
    assert depth["distinct_survey_periods"] == 5
    assert depth["distinct_dates"] == ["2011-12-08", "2012-02-11", "2012-11-21", "2013-06-17", "2013-06-18"]
    # Only the queue measure is tied to a dated survey day; nothing here spans months.
    dated = observed.loc[observed["observation_date"].notna(), "measure"].unique()
    assert set(dated) == {"queue_length_at_ticket_counters"}
    for measure, part in observed.groupby("measure"):
        assert part["observation_date"].nunique(dropna=True) <= 2, measure


def test_gate_rejects_the_source_for_future_prediction(metadata):
    gate = metadata["validation_gate"]
    assert gate["eligible_for_primary_future_prediction_model"] is False
    failed = set(gate["failed_criteria"])
    assert {"genuine_future_test_period_exists", "time_ordering_is_known",
            "sufficient_observations_for_time_series_split"} <= failed
    assert len(failed) >= 5
    for name in failed:
        assert len(gate["criteria"][name]["evidence"]) > 40, f"{name} needs written evidence, not just a flag"
    assert "REJECT" in gate["decision"] and "ACCEPT" in gate["decision"]


def test_gate_is_a_real_computation_not_a_constant():
    extractor = _extractor()
    for records, periods in ((249, 5), (12, 1), (5000, 300)):
        gate = extractor.validation_gate({"records": records, "distinct_survey_periods": periods})
        assert gate["eligible_for_primary_future_prediction_model"] is False
        assert str(records) in gate["criteria"]["sufficient_observations_for_time_series_split"]["evidence"]
    assert set(extractor.validation_gate({"records": 1, "distinct_survey_periods": 1})["criteria"]) == set(
        extractor.validation_gate({"records": 2, "distinct_survey_periods": 2})["criteria"])


# ------------------------------------------------------------------ quarantine of model output
def test_modelled_forecasts_are_quarantined_and_flagged():
    modelled = pd.read_csv(MODELLED_CSV)
    assert set(modelled["year"]) == {2012, 2016, 2021, 2031}
    assert modelled["eligible_as_supervised_label"].astype(str).eq("False").all()
    assert modelled["classification"].astype(str).str.contains("MODEL OUTPUT", case=False).all()
    # the numbers the brief warns about must exist only in the quarantine file
    assert float(modelled.loc[modelled["year"].eq(2031), "total_lakhs"].iloc[0]) == pytest.approx(134.65, abs=0.01)


def test_observed_file_contains_no_forecast_horizon_rows(observed):
    assert "year" not in observed.columns
    assert not observed["time_interval"].astype(str).eq("P1Y").any()
    assert not observed["measure"].astype(str).str.contains("forecast|projection", case=False).any()
    for date_column in ("survey_period_start", "survey_period_end", "observation_date"):
        values = pd.to_datetime(observed[date_column], errors="coerce").dropna()
        assert values.empty or values.max().year <= 2013, f"{date_column} reaches beyond the survey document"


def test_no_training_or_feature_code_reads_the_quarantine_file():
    offenders = []
    for path in list((ROOT / "ml").rglob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        if path.name == "extract_mumbai_pdf_surveys.py":
            continue
        if "mumbai_suburban_rail_MODELLED" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"modelled study output must never enter a training path: {offenders}"


# ------------------------------------------------------------------ parser behaviour
def test_collapsed_normalises_the_pdf_text_layer():
    pages = {7: "Table  E- 4\n   Up   1,234   567   (89)\n\n  8.00 - 9.00    2,000"}
    text = collapsed(pages, 7)
    assert "\n" not in text and "  " not in text
    assert "1,234 567 (89)" in text
    # A cited page that is absent from the extraction is an error, never a silent skip:
    # silently continuing is how a whole table could vanish and the dataset shrink unnoticed.
    with pytest.raises(PdfParseError, match="page 8 is missing"):
        collapsed(pages, 7, 8)
    ordered = {1: "first page", 2: "second page"}
    assert collapsed(ordered, 1, 2) == "first page second page"
    assert collapsed(ordered, 2, 1) == "second page first page", "multi-page tables keep read order"


def test_numeric_helpers_handle_the_reports_comma_grouping():
    assert _int("12,34,567") == 1234567
    assert _numbers("total 4,293,693 against 143,580") == [4293693, 143580]
    assert _close(100, 101) and not _close(100, 140)


def _pdf_extraction_possible() -> bool:
    import importlib.util

    return PDF_PATH.is_file() and importlib.util.find_spec("pymupdf") is not None


@pytest.mark.skipif(not _pdf_extraction_possible(),
                    reason="source PDF is not redistributed (and/or the optional pymupdf dependency is missing)")
def test_committed_extract_is_reproducible_from_the_source_pdf():
    parsed = parse_pdf(PDF_PATH)
    assert parsed["page_count"] == 38
    observed_lists = ("hourly_travel", "station_entry_exit_totals", "hourly_entry_exit_profile",
                      "section_load", "train_crowding", "peak_hours", "queue_observations")
    assert sum(len(parsed[name]) for name in observed_lists) == len(pd.read_csv(OBSERVED_CSV)) == 249
    assert len(parsed["survey_periods"]) == 5
    modelled = parsed["modelled_forecasts"]
    assert {int(row["year"]) for row in modelled["values"]} == {2012, 2016, 2021, 2031}
    assert modelled["classification"].upper().startswith("HISTORICAL STUDY MODEL OUTPUT")
    assert modelled["eligible_as_supervised_label"] is False


def test_network_context_and_peak_hours_are_carried_through(observed, metadata):
    assert set(metadata["network_context"]) == set(NETWORK_CONTEXT)
    assert metadata["network_context"]["corridors"] == 3
    assert sum(metadata["network_context"]["stations"].values()) == 115
    morning = [row for row in PEAK_HOURS if row["direction"] == "UP"]
    assert all(re.match(r"\d{2}:\d{2}-\d{2}:\d{2}", row["peak_hour_label"]) for row in PEAK_HOURS)
    assert any(row["peak_hour_passengers"] == 632000 for row in morning)
    totals = observed[observed["measure"].eq("station_entries_plus_exits_14h")].groupby("line")["demand_count"].max()
    assert "Western Line" in totals.index and totals["Western Line"] >= 500_000
