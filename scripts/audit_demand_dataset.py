#!/usr/bin/env python3
"""Print the verified facts about a candidate demand table (audit only - writes nothing).

Run this on any supplied CSV *before* deciding what it can do:

    python3 scripts/audit_demand_dataset.py --csv file.csv
    python3 scripts/audit_demand_dataset.py --csv file.csv --json /tmp/audit.json

It reports the row/column inventory, what the file declares about its own provenance (a
`Data_Type = Synthetic` column is surfaced at the top), the measured timestamp grid and time
slots, entity coverage and holes, duplicate-key structure, which columns could be the demand
target, what the segmentation columns (line / corridor / direction / status) actually do - and
whether every precomputed ``Target_*`` column really reproduces the demand series shifted
forward, which is the only way such a column earns the right to be used as a label.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.data_pipeline.audit import audit_csv  # noqa: E402


def _line(label: str, value: object) -> str:
    return f"{label:<34} {value}"


def report(payload: dict) -> str:
    out: list[str] = []
    source = payload.get("source", {})
    inv = payload["inventory"]
    prov = payload["provenance"]
    temporal = payload["temporal"]
    profile = payload["profiler"]
    out.append("=" * 92)
    out.append(f"AUDIT {source.get('path', '<frame>')}")
    out.append("=" * 92)
    out.append(_line("rows / columns / memory", f"{inv['rows']:,} / {inv['columns']} / {inv['memory_mb']} MB"))
    out.append(_line("fully duplicated rows", inv["fully_duplicated_rows"]))
    out.append(_line("sha256", str(source.get("sha256", ""))[:16] + "…"))
    if prov.get("declared_class_columns"):
        out.append("")
        out.append("-- what the file declares about itself ------------------------------")
        for item in prov["declared_class_columns"]:
            out.append(_line(f"column {item['column']}", f"{item['reads_as']} :: values {item['values']} "
                                                        f"(synthetic share {item['synthetic_share']:.0%})"))
        out.append(_line("classification", prov["classification"]))
    out.append("")
    out.append("-- columns -------------------------------------------------------------")
    for name, entry in inv["column_report"].items():
        numeric = ""
        if "min" in entry:
            numeric = f" range {entry['min']:g}..{entry['max']:g} int {entry['integer_share']:.0%}"
        samples = f" values {entry['sample_values'][:6]}" if entry.get("sample_values") else ""
        out.append(_line(name, f"{entry['dtype']} | distinct {entry['distinct']:,} | missing {entry['missing_share']:.1%}"
                              f"{numeric}{samples}"))
    out.append("")
    out.append("-- temporal ------------------------------------------------------------")
    if temporal.get("error"):
        out.append(_line("error", temporal["error"]))
    else:
        out.append(_line("timestamp column", temporal.get("timestamp_column")))
        out.append(_line("range", f"{temporal.get('min')} -> {temporal.get('max')}"))
        period = temporal.get("period")
        if period:
            out.append(_line("measured period", f"{period['seconds']}s ({period['granularity']}), "
                                                f"modal share {period['modal_spacing_share']:.0%}, "
                                                f"{period['distinct_spacings']} distinct spacing(s)"))
        else:
            out.append(_line("measured period", f"NONE - {temporal.get('period_error')}"))
        out.append(_line("distinct timestamps / periods", f"{temporal.get('distinct_timestamps', 0):,} / "
                                                          f"{temporal.get('distinct_periods', 0):,}"))
        if temporal.get("time_slots_present"):
            slots = temporal["time_slots_present"]
            out.append(_line("clock times present", f"{slots['count']} :: "
                                                     f"{', '.join(list(slots['slots'])[:12])}"
                                                     f"{' …' if slots['count'] > 12 else ''}"))
            if temporal.get("time_slot_note"):
                out.append(_line("", temporal["time_slot_note"]))
        if temporal.get("slots_per_entity_day"):
            spd = temporal["slots_per_entity_day"]
            out.append(_line("slots per entity-day", f"min {spd['min']} / median {spd['median']:.1f} / max {spd['max']} "
                                                      f"| continuous-hours series: {spd['continuous_hours']}"))
        grid = temporal.get("candidate_grid")
        if grid:
            out.append(_line("day x slot grid", f"days {grid['distinct_days']} (contiguous {grid['daily_contiguous_share']:.0%}) "
                                                f"x {grid['slots_per_day']} slots :: {', '.join(grid['slots'])}"))
            out.append(_line("observed per entity-day", f"min {grid['observations_per_entity_day']['min']} / "
                                                        f"median {grid['observations_per_entity_day']['median']:.1f} / "
                                                        f"max {grid['observations_per_entity_day']['max']}"))
            out.append(_line("implied formulation", grid["implied_formulation"]))
        entities = temporal.get("entities")
        if entities:
            out.append(_line(f"entities ({entities['column']})", entities["count"]))
            out.append(_line("rows per entity", f"min {entities['rows_per_entity']['min']:,} / "
                                                 f"median {entities['rows_per_entity']['median']:,.1f} / "
                                                 f"max {entities['rows_per_entity']['max']:,}"))
            out.append(_line("span per entity (days)", f"{entities['span_days']['min']}..{entities['span_days']['max']}"))
            out.append(_line("within-entity spacing", temporal.get("within_entity_spacing")))
            out.append(_line("off-grid steps", f"{temporal.get('off_grid_steps', 0):,} "
                                                f"({temporal.get('off_grid_step_share', 0):.1%})"))
            grid = temporal.get("grid_cells", {})
            out.append(_line("grid cells", f"expected {grid.get('expected_over_entity_spans', 0):,} / "
                                            f"observed {grid.get('observed', 0):,} / missing "
                                            f"{grid.get('missing', 0):,} (coverage "
                                            f"{(grid.get('coverage_ratio') or 0):.1%})"))
    out.append("")
    out.append("-- demand target candidates --------------------------------------------")
    demand = profile.get("demand") or {}
    out.append(_line("chosen", demand.get("chosen") or profile.get("mapping", {}).get("demand")))
    if demand.get("ambiguous"):
        out.append(_line("AMBIGUOUS with it", ", ".join(demand["ambiguous"])))
    for name, entry in (demand.get("table") or {}).items():
        flag = "" if not entry.get("disqualifiers") else f"  <- {'; '.join(entry['disqualifiers'])}"
        out.append(_line(f"  {name}", f"score {entry.get('score')}{flag}"))
    out.append("")
    out.append("-- segmentation / direction columns ------------------------------------")
    for name, entry in (payload["segmentation"].get("candidates") or {}).items():
        out.append(_line(name, f"{entry['role_guess']} | distinct {entry['distinct']} | "
                               f"{entry.get('relation', 'labels only')} | values {entry['values'][:6]}"))
    dupes = payload.get("duplicate_keys") or {}
    if dupes.get("duplicate_entity_timestamp_rows"):
        out.append(_line("repeated entity+timestamp rows", dupes["duplicate_entity_timestamp_rows"]))
        out.append(_line("disambiguated by", dupes.get("columns_that_disambiguate_repeated_keys")))
        out.append(_line("", dupes.get("suggestion", "")))
    out.append("")
    out.append("-- precomputed target columns (never trusted by default) ---------------")
    targets = payload.get("precomputed_targets") or {}
    if targets.get("error") or not targets.get("candidates"):
        out.append(_line("result", targets.get("error") or targets.get("verdict_summary")))
    for name, entry in (targets.get("per_target") or {}).items():
        if not isinstance(entry, dict):
            continue
        out.append(_line(name, f"{entry.get('verdict')} (alignments tested {entry.get('alignments_tested', 0)}, "
                               f"best {entry.get('best_alignment', '-')}, exact "
                               f"{(entry.get('evidence') or {}).get('exact_or_within_tolerance', 0):.1%})"))
        out.append(_line("", f"     {entry.get('decision') or entry.get('reason')}"))
    out.append("")
    out.append("-- readiness -------------------------------------------------------------")
    readiness = payload["readiness"]
    out.append(_line("can enter registration", readiness["can_enter_registration"]))
    for blocker in readiness["blockers"]:
        out.append(_line("  blocker", blocker))
    if readiness["ignored_precomputed_targets"]:
        out.append(_line("targets ignored as ground truth", ", ".join(readiness["ignored_precomputed_targets"])))
    if readiness.get("supported_time_slots_note"):
        out.append(_line("supported times", readiness["supported_time_slots_note"]))
    out.append("=" * 92)
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--timezone", default="Asia/Kolkata")
    parser.add_argument("--nrows", type=int, default=None, help="audit only the first N rows (structure is usually enough)")
    parser.add_argument("--ignore-column", action="append", default=None)
    parser.add_argument("--dataset-class", default=None,
                        help="override the provenance class the audit infers from the file itself")
    parser.add_argument("--low-memory", action="store_true",
                        help="read text columns as categoricals so a multi-hundred-thousand-row file can be "
                             "audited in full on a small machine (values are unchanged)")
    parser.add_argument("--json", type=Path, default=None, help="also write the machine-readable report here")
    args = parser.parse_args()
    if not args.csv.is_file():
        parser.error(f"file not found: {args.csv}")
    payload = audit_csv(args.csv, timezone=args.timezone, nrows=args.nrows, ignore_columns=args.ignore_column,
                        low_memory=args.low_memory, dataset_class=args.dataset_class)
    print(report(payload))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(json.loads(json.dumps(payload, default=str)), indent=2), encoding="utf-8")
        print(f"machine-readable report: {args.json}")


if __name__ == "__main__":
    main()
