#!/usr/bin/env python3
"""Preflight for GPU training: prove this machine can actually run CUDA XGBoost before a long run.

Run it from the repository root after installing backend/requirements-gpu.txt:

    python scripts/check_gpu.py

Exit status 0 means the trainers can be pointed at the GPU with TRANSITCROWD_XGB_DEVICE=cuda. Any other
status prints what is missing; training itself never needs an edit to a Python file.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
import warnings


def nvidia_smi() -> tuple[bool, str]:
    binary = shutil.which("nvidia-smi")
    if not binary:
        return False, "nvidia-smi is not on PATH (no NVIDIA driver visible to this shell)"
    try:
        out = subprocess.run([binary, "--query-gpu=name,driver_version,memory.total",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"nvidia-smi could not be executed: {exc}"
    if out.returncode != 0:
        return False, f"nvidia-smi failed: {(out.stderr or out.stdout).strip()[:200]}"
    return True, out.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rows", type=int, default=600, help="rows in the probe dataset (default 600)")
    parser.add_argument("--json", default=None, help="also write the findings to this JSON file")
    args = parser.parse_args()

    findings: dict[str, object] = {"python": sys.version.split()[0], "platform": platform.platform()}
    print(f"[1/4] python {findings['python']} on {findings['platform']}")
    if sys.version_info < (3, 10):
        print("FAIL  training needs Python 3.10 or newer (the project is developed on 3.13).")
        return 4

    present, detail = nvidia_smi()
    findings["nvidia_smi"] = detail
    if present:
        print("[2/4] GPU visible to the driver:")
        for line in detail.splitlines():
            print(f"        {line}")
    else:
        print(f"[2/4] {detail}")
        print("      Continuing: the probe below is what actually decides whether GPU training can run.")

    try:
        import xgboost as xgb
    except ImportError as exc:
        print(f"[3/4] FAIL  import xgboost raised {exc}")
        print("      Install the GPU build on the training machine:  pip install -r backend/requirements-gpu.txt")
        print("      backend/requirements.txt pins xgboost-cpu, which is the right choice for serving but has no CUDA code.")
        return 3
    print(f"[3/4] xgboost {xgb.__version__} (device parameter supported: "
          f"{'device' in xgb.XGBRegressor().get_params()})")

    import numpy as np
    rng = np.random.default_rng(7)
    rows = args.rows
    frame = rng.normal(size=(rows, 6))
    y = frame[:, 0] * 2.0 + frame[:, 1] * -1.5 + rng.normal(scale=0.2, size=rows)
    ok = True
    reason = ""
    started = time.perf_counter()
    # Warnings from fit are the GPU verdict. A prediction from a CPU NumPy array can legitimately emit
    # a device-mismatch warning because the estimator was trained on CUDA but the input array remains on
    # the host. Do not misclassify that warning as a CPU-only build.
    fit_warnings = []
    prediction = np.empty(0)
    with warnings.catch_warnings(record=True) as caught_fit:
        warnings.simplefilter("always")
        try:
            model = xgb.XGBRegressor(n_estimators=40, max_depth=4, tree_method="hist", device="cuda")
            model.fit(frame, y)
        except Exception as exc:  # noqa: BLE001 - report whatever the GPU stack says instead of hiding it
            ok = False
            reason = f"{type(exc).__name__}: {exc}"
        fit_warnings = [str(item.message) for item in caught_fit]

    if ok:
        lower_fit = " ".join(fit_warnings).lower()
        fatal_markers = (
            "not compiled with cuda support",
            "xgboost is not compiled with cuda support",
            "cuda support is not available",
            "no visible gpu is found",
            "cudaerror",
        )
        if any(marker in lower_fit for marker in fatal_markers):
            ok = False
            reason = ("GPU XGBoost fit reported a CUDA failure: " + next(
                message for message in fit_warnings if any(marker in message.lower() for marker in fatal_markers)
            )[:400])

    if ok:
        # Keep prediction as a secondary smoke test, but explicitly tolerate the expected CPU->GPU
        # placement warning produced when NumPy input stays on host memory.
        with warnings.catch_warnings(record=True) as caught_predict:
            warnings.simplefilter("always")
            try:
                prediction = model.predict(frame[:8])
            except Exception as exc:  # noqa: BLE001
                ok = False
                reason = f"{type(exc).__name__}: {exc}"
        unexpected_predict = [
            str(item.message) for item in caught_predict
            if not any(token in str(item.message).lower() for token in (
                "mismatched devices", "fallback to prediction using dmatrix", "fallback to prediction"
            ))
        ]
        if ok and unexpected_predict:
            print("      Note: prediction emitted non-fatal warnings:")
            for message in unexpected_predict[:3]:
                print(f"        {message[:280]}")

    elapsed = time.perf_counter() - started
    if not ok:
        print(f"[4/4] FAIL  a tiny XGBoost fit on device='cuda' did not run on a GPU: {reason[:600]}")
    else:
        print(f"[4/4] PASS  tiny fit + predict on device='cuda' in {elapsed * 1000:.0f} ms; "
              f"model echoes device={model.get_params().get('device')!r}; "
              f"first predictions {', '.join(f'{v:.2f}' for v in prediction[:3])}")
    findings.update({"probe_ok": ok, "probe_seconds": round(elapsed, 3), "xgboost_version": xgb.__version__,
                 "probe_detail": reason})
    if args.json:
        pathlib_write = pathlib.Path(str(args.json)) if False else None
        import pathlib as _pathlib
        _pathlib.Path(str(args.json)).write_text(json.dumps(findings, indent=2) + "\n", encoding="utf-8")
        print(f"      findings written to {args.json}")
    if not ok:
        print("\nNot usable for GPU training. Usual causes: CUDA driver older than the wheel expects, "
              "the CPU-only xgboost wheel installed, or a GPU the driver has not enumerated. "
              "Training on CPU stays fully supported - the same commands without TRANSITCROWD_XGB_DEVICE.")
        return 2
    print("\nReady. Start the Mumbai training run with the GPU selected by environment only:")
    print("  Windows PowerShell:  $env:TRANSITCROWD_XGB_DEVICE = \"cuda\"")
    print("  bash / WSL:         export TRANSITCROWD_XGB_DEVICE=cuda")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
