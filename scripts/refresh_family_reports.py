#!/usr/bin/env python3
"""Regenerate the explanatory limitation text of already-trained families from the shared generator.

`ml/training/limitations.py` derives a family's limitations from that family's own record, so when the
generator changes, the stored reports have to change with it - otherwise an artifact keeps asserting
sentences about a different city's data. Re-fitting identical models to rewrite prose would waste the
better part of an hour, so this reads the inputs back out of what is already on disk (the registered
family entry, the dataset sidecar, the normalized file the family was built from, and the fit window the
trainer recorded), calls the same generator the trainer calls, and writes the result into both
`model_report.json` and the report copy inside the model bundle. No model, metric, threshold or split in
this repository is recomputed, added or removed by it.

Usage:
    python3 scripts/refresh_family_reports.py                 # every family with artifacts on disk
    python3 scripts/refresh_family_reports.py --system-id mumbai-metro --recompress
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from ml.training import limitations  # noqa: E402
from ml.training.registry import MODEL_FAMILIES  # noqa: E402


def _span(system_id: str, family: dict[str, Any]) -> tuple[str | None, str | None]:
    relative = family.get("dataset_relative_path")
    if not relative:
        return None, None
    path = ROOT / str(relative)
    if not path.is_file():
        return None, None
    stamps = pd.read_csv(path, usecols=["timestamp"], encoding="utf-8-sig")["timestamp"]
    return str(stamps.min()), str(stamps.max())


def _horizon_text(family: dict[str, Any], report: dict[str, Any]) -> str:
    granularity = str(family.get("granularity") or "period")
    if granularity == "day":
        horizon = report.get("forecast_horizon") or {}
        usable, measured = horizon.get("usable_horizon_days"), horizon.get("max_measured_horizon_days")
        return ("Forecasts past the last observation are recursive one-day model calls bounded by the family's "
                f"measured horizon ({usable} usable of {measured} measured days); the horizon governance recorded "
                "in this report is what the service accepts, and nothing beyond it is answered with a guess.")
    limit = int(family.get("max_recursive_horizon_hours") or family.get("max_recursive_horizon_days") or 336)
    return ("Forecasts past the most recent observation are recursive one-hour model calls, limited to "
            f"{limit} hours from the data frontier; the uncertainty of those calls is not calibrated and is "
            "reported as historical-relative bands, never as a confidence percentage.")


def refresh(system_id: str, *, recompress: bool) -> dict[str, Any]:
    import joblib

    family = MODEL_FAMILIES.get(system_id)
    if family is None:
        raise SystemExit(f"'{system_id}' is not a registered family")
    directory = ROOT / "backend/models" / str(family.get("artifact_subdirectory") or system_id)
    report_path = directory / "model_report.json"
    bundle_path = directory / "transitcrowd.joblib"
    if not report_path.is_file() and not bundle_path.is_file():
        raise SystemExit(f"no artifacts on disk for '{system_id}' in {directory.relative_to(ROOT)}")

    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    bundle = joblib.load(bundle_path) if bundle_path.is_file() else None
    metadata = {}
    metadata_path = ROOT / str(family.get("metadata_relative_path") or "")
    if family.get("metadata_relative_path") and metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    first, last = _span(system_id, family)
    report["limitations"] = limitations.build(
        family, metadata, first_observation=first, last_observation=last,
        fit_window=report.get("fit_window") or {}, horizon_text=_horizon_text(family, report))
    if bundle is not None and isinstance(bundle.get("model_report"), dict):
        bundle["model_report"]["limitations"] = report["limitations"]
    if report_path.is_file():
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if bundle is not None and (recompress or report_path.is_file()):
        joblib.dump(bundle, bundle_path, compress=9 if recompress else 3)
    return {"system_id": system_id, "limitations": len(report["limitations"]),
            "report_written": report_path.is_file(), "bundle_updated": bundle is not None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-id", action="append", default=None,
                        help="family to refresh; repeatable. Default: every registered family with artifacts.")
    parser.add_argument("--recompress", action="store_true",
                        help="re-write the joblib bundle at compression level 9 (same objects, smaller file)")
    args = parser.parse_args()
    targets = args.system_id or [system_id for system_id in sorted(MODEL_FAMILIES)
                                 if (ROOT / "backend/models" / system_id / "model_report.json").is_file()]
    for system_id in targets:
        result = refresh(system_id, recompress=args.recompress)
        print(f"[limitations] {result['system_id']}: {result['limitations']} statements rewritten "
              f"(report={result['report_written']}, bundle={result['bundle_updated']})")


if __name__ == "__main__":
    main()
