#!/usr/bin/env python3
"""Extract observed Mumbai suburban-rail survey data from the MRVC/Wilbur Smith PDF.

Writes:
  data/research/mumbai_suburban_rail_pdf_observed.csv            (observed + derived survey records)
  data/research/mumbai_suburban_rail_pdf_observed.metadata.json  (provenance, granularity, time depth, gate)
  data/research/mumbai_suburban_rail_MODELLED_od_forecast.csv     (quarantined study model output)

The extraction is deterministic and cross-checked: the parser refuses to emit a table
whose rows do not reproduce the totals printed in that same table.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.data_pipeline.mumbai_pdf import PdfParseError, parse_pdf  # noqa: E402

DEFAULT_PDF = ROOT.parent / "uploads" / "ExecutiveSummarywilber FINAL.pdf"
OBSERVED_COLUMNS = [
    "system_id", "city", "mode", "operator", "line", "station_id", "station_name", "direction",
    "service_type", "survey_period_start", "survey_period_end", "time_interval", "interval_label",
    "demand_count", "measure", "unit", "slow_count", "fast_count", "share_percent",
    "total_services", "authorised_entry_exit", "unauthorised_entry_exit", "trains_stopping_8_to_22",
    "section_load", "average_passengers_per_train", "maximum_passengers_per_train", "rated_capacity",
    "total_ticket_counters", "working_ticket_counters", "queue_length_persons", "average_queue_minutes",
    "observation_date", "peak_hour_label", "peak_hour_passengers", "section", "aggregation_level",
    "observation_type", "basis", "source_document", "source_table", "source_page", "provenance",
]


def slug(name: str) -> str:
    import re
    import unicodedata
    ascii_name = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def base_row(kind: str, period: dict | None) -> dict:
    return {
        "system_id": "mumbai-suburban-railway", "city": "Mumbai", "mode": "SUBURBAN_RAIL",
        "operator": "Western Railway / Central Railway (Indian Railways); study commissioned by MRVC",
        "provenance": f"PDF table extraction ({kind})",
        "survey_period_start": period.get("start") if period else None,
        "survey_period_end": period.get("end") if period else None,
    }


def to_observed_frames(parsed: dict) -> tuple[pd.DataFrame, dict]:
    periods = parsed["survey_periods"]
    rows: list[dict] = []

    for item in parsed["hourly_travel"]:
        row = base_row("hourly_travel", periods[item.pop("survey_period_key")])
        row.update({
            "line": item["line"], "direction": item["direction"],
            "service_type": "SLOW_AND_FAST", "time_interval": item["interval_label"],
            "interval_label": item["interval_label"], "demand_count": item["total_count"],
            "slow_count": item.get("slow_count"), "fast_count": item.get("fast_count"),
            "share_percent": item.get("share_percent"),
            "total_services": item.get("total_services"),
            "measure": item["measure"], "unit": item["unit"],
            "observation_type": item["observation_type"], "basis": item["basis"],
            "source_document": item["source_document"], "source_table": item["source_table"],
            "source_page": item["source_page"], "aggregation_level": "line",
            "station_name": None, "station_id": None,
        })
        rows.append(row)

    for item in parsed["station_entry_exit_totals"]:
        row = base_row("station_entry_exit", periods[item.pop("survey_period_key")])
        name = item["station_name"]
        row.update({
            "line": item["line"], "direction": item["direction"], "service_type": item["service_type"],
            "station_name": name, "station_id": slug(name), "time_interval": item["time_interval"],
            "demand_count": item["total_entry_exit_14h"],
            "authorised_entry_exit": item["authorised_entry_exit"],
            "unauthorised_entry_exit": item["unauthorised_entry_exit"],
            "trains_stopping_8_to_22": item["trains_stopping_8_to_22"],
            "measure": item["measure"], "unit": item["unit"], "observation_type": item["observation_type"],
            "source_document": "Mumbai Sub-urban Rail Passenger Surveys and Analysis (Executive Summary)",
            "source_table": item["source_table"], "source_page": item["source_page"],
            "aggregation_level": "station", "basis": "counted at all authorised and unauthorised entry points",
        })
        rows.append(row)

    for item in parsed["hourly_entry_exit_profile"]:
        row = base_row("hourly_entry_exit", periods[item.pop("survey_period_key")])
        row.update({
            "line": item["line"], "direction": item["direction"], "service_type": item["service_type"],
            "station_name": item.get("station_name"), "station_id": None,
            "time_interval": item["interval_label"], "interval_label": item["interval_label"],
            "demand_count": item["entry_exit_count"], "share_percent": item["share_percent"],
            "measure": item["measure"], "unit": item["unit"], "observation_type": item["observation_type"],
            "aggregation_level": item["aggregation_level"], "basis": "station entry/exit counts summarised per hour",
            "source_document": "Mumbai Sub-urban Rail Passenger Surveys and Analysis (Executive Summary)",
            "source_table": item["source_table"], "source_page": item["source_page"],
        })
        rows.append(row)

    for item in parsed["section_load"]:
        key = item.pop("survey_period_key")
        peak_label = item.pop("peak_hour_label", None) or periods[key].get("daily_window")
        row = base_row("section_load", periods[key])
        row.update({
            "line": item["line"], "direction": item["direction"], "service_type": item["service_type"],
            "section": item["section"], "time_interval": peak_label,
            "interval_label": peak_label,
            "demand_count": item["section_load"], "section_load": item["section_load"],
            "measure": item["measure"], "unit": item["unit"], "observation_type": item["observation_type"],
            "basis": "peak-hour section load derived from in-train boarding/alighting counts",
            "source_document": "Mumbai Sub-urban Rail Passenger Surveys and Analysis (Executive Summary)",
            "source_table": item["source_table"], "source_page": item["source_page"],
            "aggregation_level": "section",
        })
        rows.append(row)

    for item in parsed["train_crowding"]:
        row = base_row("train_crowding", periods[item.pop("survey_period_key")])
        item.pop("capacity_source", None)
        row.update({
            "line": item["line"], "direction": item["direction"], "service_type": item["service_type"],
            "time_interval": "peak hour", "demand_count": item["average_passengers_per_train"],
            "average_passengers_per_train": item["average_passengers_per_train"],
            "maximum_passengers_per_train": item["maximum_passengers_per_train"],
            "rated_capacity": item["rated_capacity"], "measure": item["measure"], "unit": item["unit"],
            "observation_type": item["observation_type"],
            "basis": "peak-hour section load divided by number of trains in the peak hour",
            "source_document": item["source_document"], "source_table": item["source_table"],
            "source_page": item["source_page"], "aggregation_level": "line_service_type",
        })
        rows.append(row)

    for item in parsed["peak_hours"]:
        note = item.pop("note", None)
        row = base_row("peak_hour", periods[item.pop("survey_period_key")])
        row.update({
            "line": item["line"], "direction": item["direction"], "service_type": "SLOW_AND_FAST",
            "time_interval": item["peak_hour_label"], "peak_hour_label": item["peak_hour_label"],
            "demand_count": item["peak_hour_passengers"], "peak_hour_passengers": item["peak_hour_passengers"],
            "measure": item["measure"], "unit": item["unit"], "observation_type": item["observation_type"],
            "basis": note, "source_document": item["source_document"],
            "source_table": item["source_table"], "source_page": item["source_page"],
            "aggregation_level": "line",
        })
        rows.append(row)

    for item in parsed["queue_observations"]:
        row = base_row("queue", None)
        row["survey_period_start"] = item["observation_date"]
        row["survey_period_end"] = item["observation_date"]
        row.update({
            "line": item["line"], "station_name": item["station_name"], "station_id": slug(item["station_name"]),
            "direction": item["direction"], "service_type": item["service_type"],
            "observation_date": item["observation_date"], "time_interval": "peak hours",
            "demand_count": item["queue_length_persons"],
            "total_ticket_counters": item["total_ticket_counters"],
            "working_ticket_counters": item["working_ticket_counters"],
            "queue_length_persons": item["queue_length_persons"],
            "average_queue_minutes": item["average_queue_minutes"],
            "measure": item["measure"], "unit": item["unit"], "observation_type": item["observation_type"],
            "basis": "counters and queue length observed at the stated survey date",
            "source_document": "Mumbai Sub-urban Rail Passenger Surveys and Analysis (Executive Summary)",
            "source_table": item["source_table"], "source_page": item["source_page"],
            "aggregation_level": "station",
        })
        rows.append(row)

    frame = pd.DataFrame(rows)
    for column in OBSERVED_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    frame = frame[OBSERVED_COLUMNS]

    summary = {
        "records": int(len(frame)),
        "records_by_measure": dict(Counter(frame["measure"].dropna().tolist())),
        "distinct_survey_periods": int(frame[["survey_period_start", "survey_period_end"]].astype(str).agg("|".join, axis=1).nunique()),
        "distinct_lines": sorted({str(v) for v in frame["line"].dropna().unique()}),
        "distinct_stations_named": int(frame["station_name"].dropna().nunique()),
        "distinct_time_intervals": int(frame["time_interval"].dropna().nunique()),
        "distinct_dates": sorted({str(v) for v in frame["survey_period_start"].dropna().unique()}),
        "measures_with_a_real_timestamp": ["queue_length_at_ticket_counters (dated survey day only)"],
    }
    return frame, summary


DIRECTION_SYNONYMS = {"UP": "UP", "DOWN": "DOWN", "BOTH": "BOTH"}
SERVICE_TYPE_SYNONYMS = {
    "ALL": "ALL", "SLOW_AND_FAST": "SLOW_AND_FAST", "FAST + SLOW": "SLOW_AND_FAST",
    "SLOW": "SLOW", "SLOW SERVICES": "SLOW", "FAST": "FAST", "FAST SERVICES": "FAST",
    "MAIN HARBOUR": "MAIN_HARBOUR", "TRANS HARBOUR": "TRANS_HARBOUR",
}


def normalize_vocabulary(value, synonyms: dict[str, str]) -> tuple[object, str | None]:
    """Return the controlled value plus the original text whenever they differ.

    The report writes free-text labels ("Up Direction, Peak hour (8:30 - 9:30)",
    "Fast + Slow"). Grouping needs a controlled vocabulary, but the original wording is
    evidence, so it is preserved in a sibling column instead of being discarded.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None, None
    text = str(value).strip()
    canonical = text.upper()
    for token, replacement in (("UP DIRECTION", "UP"), ("DOWN DIRECTION", "DOWN")):
        if canonical.startswith(token):
            canonical = replacement
            break
    canonical = synonyms.get(canonical, canonical)
    return canonical, (None if canonical == text else text)


def normalize_source_table(value: str) -> tuple[str, str | None]:
    text = str(value).strip()
    match = re.match(r"^(Table|Figure)\s*E-\s*(\d+)", text)
    if not match:
        return text, None
    canonical = f"{match.group(1)} E-{int(match.group(2))}"
    remainder = text[match.end():].strip(" .,-()")
    return canonical, (remainder or None)



def validation_gate(summary: dict) -> dict:
    """Phase 15 gate for the primary future-prediction model."""
    criteria = {
        "target_values_are_actual_observations": {
            "pass": False,
            "evidence": "Most values are sample-survey expansions (2-step: coach→train, sample services→all peak services), not raw counts. Only entry/exit counts and queue counts are directly counted, and even those are one-day aggregates.",
        },
        "time_ordering_is_known": {
            "pass": False,
            "evidence": "Hourly order within 08:00-22:00 is known, but there is only one surveyed weekday per line; no ordering across days exists.",
        },
        "temporal_granularity_is_known": {
            "pass": True,
            "evidence": "1 hour for the interval tables; 14-hour day totals for station rows.",
        },
        "entity_identity_stable_enough": {
            "pass": True,
            "evidence": "Named stations and fixed line/section labels; 47 station rows over 4 line rosters.",
        },
        "source_provenance_documented": {
            "pass": True,
            "evidence": "Single PDF; table and page recorded for every row; survey schedule in Table E-1.",
        },
        "missingness_quantified": {
            "pass": False,
            "evidence": "The report does not state how many of the 154 network stations were excluded, nor per-station survey-day counts, so missingness cannot be quantified.",
        },
        "no_future_values_used_for_past_features": {
            "pass": True,
            "evidence": "No lag/rolling features are constructed from this source at all.",
        },
        "license_usage_rights_understood": {
            "pass": False,
            "evidence": "No licence or reuse statement is printed in the executive summary; MRVC/WSA ownership of the survey report is asserted by the cover page only.",
        },
        "sufficient_observations_for_time_series_split": {
            "pass": False,
            "evidence": f"{summary['records']} extracted rows exist, but they form {summary['distinct_survey_periods']} survey-period snapshots rather than a series; no train/validation/test time split is possible.",
        },
        "genuine_future_test_period_exists": {
            "pass": False,
            "evidence": "A 2013 study has no future observation after any candidate cut-off; a 'forecast' here would be pure extrapolation from one weekday, unverifiable.",
        },
    }
    failed = [name for name, result in criteria.items() if not result["pass"]]
    return {
        "eligible_for_primary_future_prediction_model": not failed,
        "failed_criteria": failed,
        "criteria": criteria,
        "decision": (
            "REJECT as the primary future-prediction dataset. ACCEPT as a labelled historical "
            "baseline: peak-hour shape, hourly profile, station entry/exit structure and crowding ratios."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--outdir", type=Path, default=ROOT / "data/research")
    args = parser.parse_args()
    if not args.pdf.is_file():
        raise SystemExit(f"Source PDF not found: {args.pdf}")

    raw_bytes = args.pdf.read_bytes()
    try:
        parsed = parse_pdf(args.pdf)
    except PdfParseError as exc:
        raise SystemExit(f"PDF extraction failed validation: {exc}") from exc

    observed, summary = to_observed_frames(parsed)
    args.outdir.mkdir(parents=True, exist_ok=True)
    out_csv = args.outdir / "mumbai_suburban_rail_pdf_observed.csv"
    for column, synonyms in (("direction", DIRECTION_SYNONYMS), ("service_type", SERVICE_TYPE_SYNONYMS)):
        pairs = observed[column].map(lambda value, mapping=synonyms: normalize_vocabulary(value, mapping))
        observed[column] = [pair[0] for pair in pairs]
        observed[f"{column}_source_label"] = [pair[1] for pair in pairs]
    table_pairs = observed["source_table"].map(normalize_source_table)
    observed["source_table"] = [pair[0] for pair in table_pairs]
    observed["source_table_note"] = [pair[1] for pair in table_pairs]
    observed.to_csv(out_csv, index=False)

    modelled = parsed["modelled_forecasts"]
    modelled_frame = pd.DataFrame(modelled["values"])
    modelled_frame.insert(0, "classification", modelled["classification"])
    modelled_frame.insert(1, "eligible_as_supervised_label", False)
    modelled_csv = args.outdir / "mumbai_suburban_rail_MODELLED_od_forecast.csv"
    modelled_frame.to_csv(modelled_csv, index=False)

    gate = validation_gate(summary)
    metadata = {
        "dataset_id": "mumbai-suburban-rail-pdf-observed-2011-2013",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_document": {
            "title": "Mumbai Sub-urban Rail Passenger Surveys and Analysis — Executive Summary",
            "prepared_for": "Mumbai Railway Vikas Corporation Ltd. (MRVC)",
            "prepared_by": "Wilbur Smith Associates",
            "file_name": args.pdf.name,
            "file_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "pdf_pages": parsed["page_count"],
            "pdf_creation_date": "2013-08-16",
            "pdf_modification_date": "2013-09-04",
            "licence_or_reuse_statement": "None printed in the executive summary; treat as reference-only unless MRVC grants reuse.",
        },
        "granularity": {
            "hourly_tables": "one named 1-hour interval within 08:00-22:00 (station profile) or the sampled peak period 07:00-11:30 / 16:00-20:30 (train travel)",
            "station_tables": "one 14-hour typical-weekday total per station",
            "is_continuous_time_series": False,
            "observations_per_entity": "exactly one survey day per line/station",
        },
        "time_depth": summary,
        "survey_periods": parsed["survey_periods"],
        "station_scope": parsed["station_scope"],
        "network_context": parsed["network_context"],
        "observed_vs_modelled": {
            "observed_or_derived_tables_used": [
                "Table E-4", "Table E-5", "Table E-6", "Table E-7", "Table E-8", "Table E-9", "Table E-10",
                "Table E-11", "Table E-12", "Table E-14", "Table E-15", "Table E-16", "Table E-17",
                "Table E-18", "Table E-19", "Table E-20", "Table E-21", "Table E-22",
                "Figures E-4..E-9 narrative peak hours", "Narrative iv train crowding",
            ],
            "modelled_tables_quarantined": {
                "Table E-13": "Passenger Trips OD forecast for 2012 / 2016 (interpolated) / 2021 / 2031 — HISTORICAL STUDY MODEL OUTPUT",
            },
        },
        "modelled_forecast_quarantine": modelled,
        "validation_gate": gate,
        "target_definition": {
            "proposed_target": None,
            "reason": "No future observation exists after any cut-off, and each entity has a single surveyed day, so no autoregressive target can be defined or evaluated.",
        },
        "notes": [
            "The number in brackets in Tables E-5..E-8 is the number of trains running in that hour; in Tables E-14..E-20 it is the number of trains stopping at the station between 08:00 and 22:00. Both are preserved as service features, never as demand.",
            "Section III lists 37 selected stations; the scope lists name 13 + 8 + 14 + 11 = 46 station entries with Virar shared between two tables and Dadar split into West/Central. The report's own count of 37 is retained verbatim rather than reconciled.",
            "The report states the survey was carried out on a typical weekday and that the evening pattern was assumed to mirror the morning in reverse order; that assumption is recorded as a methodology note, not corrected.",
            "No per-day dates are invented anywhere in this dataset.",
        ],
        "outputs": {
            "observed_csv": str(out_csv.relative_to(ROOT)),
            "observed_csv_sha256": hashlib.sha256(out_csv.read_bytes()).hexdigest(),
            "modelled_csv": str(modelled_csv.relative_to(ROOT)),
            "modelled_csv_sha256": hashlib.sha256(modelled_csv.read_bytes()).hexdigest(),
        },
    }
    out_meta = args.outdir / "mumbai_suburban_rail_pdf_observed.metadata.json"
    out_meta.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Observed records : {len(observed):,} -> {out_csv.relative_to(ROOT)}")
    print(f"By measure       : {json.dumps(summary['records_by_measure'])}")
    print(f"Modelled quarantined rows: {len(modelled_frame)} -> {modelled_csv.relative_to(ROOT)}")
    print(f"Gate eligible    : {gate['eligible_for_primary_future_prediction_model']}")
    print(f"Failed criteria  : {', '.join(gate['failed_criteria']) or 'none'}")
    print(f"Metadata         : {out_meta.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
