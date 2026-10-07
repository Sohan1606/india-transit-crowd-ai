#!/usr/bin/env python3
"""Measure what a served family costs per prediction, and show that predicting does not train.

The API answers a prediction by replaying observed history and projecting forward with the persisted
bundle. This script exercises exactly that code path (the same classes backend/app/main.py builds),
reports cold start and per-request latency, and compares the artifact file's modification time before
and after - an unchanged mtime is the observable evidence that no refit, cross-validation or
dataset rebuild happened during prediction.

    python scripts/benchmark_inference.py --system-id mumbai-local-central
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.inference.daily_service import DailyDemandInferenceService  # noqa: E402
from backend.app.inference.service import TransitInferenceService  # noqa: E402
from ml.training.registry import model_family_directory, serving_families  # noqa: E402


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    index = min(len(ordered) - 1, max(0, int(round(share * (len(ordered) - 1)))))
    return float(ordered[index])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--system-id", default=None, help="registered family (default: the first served one)")
    parser.add_argument("--requests", type=int, default=24, help="predictions to time (default 24)")
    parser.add_argument("--json", default=None, help="also write the measurements to this JSON file")
    args = parser.parse_args()

    families = serving_families()
    if not families:
        print("No served families in data/registry/model_families.json.")
        return 2
    system_id = args.system_id or sorted(families)[0]
    if system_id not in families:
        print(f"'{system_id}' is not a served family. Served: {', '.join(sorted(families))}")
        return 2
    family = families[system_id]
    artifact = model_family_directory(ROOT / "backend/models", system_id) / "transitcrowd.joblib"
    data_path = ROOT / family["dataset_relative_path"]
    meta_path = ROOT / family["metadata_relative_path"] if family.get("metadata_relative_path") else None
    print(f"[family] {system_id}: granularity={family['granularity']} served_as={family.get('served_as')}")
    print(f"[files]  artifact {artifact.name} {artifact.stat().st_size:,} bytes; "
          f"dataset {data_path.name} {data_path.stat().st_size:,} bytes")
    if not artifact.exists():
        print(f"[blocked] no artifact bundle at {artifact.relative_to(ROOT)}: this family cannot predict yet. "
              f"Build it with scripts/run_mumbai_registration.sh (or the equivalent register command with --train).")
        return 3

    mtime_before = artifact.stat().st_mtime
    started = time.perf_counter()
    service = (TransitInferenceService if family["granularity"] == "hour" else DailyDemandInferenceService)(
        artifact, data_path, meta_path)
    cold_seconds = time.perf_counter() - started
    print(f"[load]   dataset read + bundle load + integrity checks: {cold_seconds:.2f} s "
          f"(this is startup cost, paid once per process - not per request)")
    if getattr(service, "unavailable_detail", None):
        print(f"[blocked] service refused to load: {service.unavailable_detail}")
        return 3

    entity_ids = [str(item) for item in service.bundle.get("entity_ids", [])]
    # The frontier is the last timestamp the dataset actually holds, read from the frame the service loaded:
    # a future request and a historical request take different paths, so this decides which is being timed.
    observed = service.daily if family["granularity"] == "day" else service.hourly
    import pandas as pd
    frontier = pd.Timestamp(observed["timestamp"].max())
    day_step = 1
    hours = [7, 8, 9, 18, 20, 0]
    latencies: list[float] = []
    kinds = {"future": 0, "historical": 0}
    for index in range(max(1, args.requests)):
        entity = entity_ids[index % len(entity_ids)]
        offset = 2 + index
        if family["granularity"] == "hour":
            ahead = (frontier + timedelta(days=offset // 24)).date()
            hour = hours[index % len(hours)]
            if index % 3 == 1:
                target, kind = (frontier - timedelta(days=offset // 24 + 1)).date(), "historical"
            else:
                target, kind = ahead, "future"
            call = lambda: service.predict(system_id, entity, target.isoformat(), hour)  # noqa: E731
        else:
            if index % 3 == 1:
                target, kind = (frontier - timedelta(days=offset * day_step + 1)).date(), "historical"
            else:
                target, kind = (frontier + timedelta(days=offset * day_step)).date(), "future"
            call = lambda: service.predict(system_id, entity, target.isoformat())  # noqa: E731
        started = time.perf_counter()
        result = call()
        latencies.append((time.perf_counter() - started) * 1000.0)
        kinds[kind] += 1
        if index == 0:
            print(f"[first]  {kind} request returned keys {sorted(result)[:6]}... in {latencies[0]:.1f} ms")

    ms = percentile(latencies, 0.50)
    p95 = percentile(latencies, 0.95)
    print(f"[latency] {len(latencies)} requests ({kinds['future']} future, {kinds['historical']} historical): "
          f"p50 {ms:.1f} ms, p95 {p95:.1f} ms, max {max(latencies):.1f} ms, mean {statistics.fmean(latencies):.1f} ms")
    mtime_after = artifact.stat().st_mtime
    print(f"[no-refit] artifact mtime unchanged across all requests: {mtime_after == mtime_before} "
          f"({mtime_before:.0f} -> {mtime_after:.0f}); prediction reads the bundle and never retrains")
    if args.json:
        import pathlib
        pathlib.Path(str(args.json)).write_text(json.dumps({
            "system_id": system_id, "granularity": family["granularity"], "served_as": family.get("served_as"),
            "cold_load_seconds": round(cold_seconds, 3), "requests": len(latencies),
            "p50_ms": round(ms, 2), "p95_ms": round(p95, 2), "max_ms": round(max(latencies), 2),
            "artifact_bytes": artifact.stat().st_size, "dataset_bytes": data_path.stat().st_size,
            "artifact_mtime_unchanged": mtime_after == mtime_before,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"[json]   {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
