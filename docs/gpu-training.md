# Training on your own machine (Windows + NVIDIA), without editing source

The dataset pipeline, audit, validation gate and model selection all live in this repository already; what a
GPU box changes is only which XGBoost build is installed and which device it is told to use.

## Windows PowerShell

```powershell
git clone https://github.com/Sohan1606/india-transit-crowd-ai.git
cd india-transit-crowd-ai
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\windows_gpu_training.ps1
```

That script runs, in order:

1. `py -3.13 -m venv .\.venv-transitcrowd` - Python 3.13, matching the version this project is developed on.
2. `pip install -r backend\requirements-gpu.txt` - the CUDA-capable `xgboost==2.1.4` instead of the pinned
   `xgboost-cpu`, plus the same pandas / scikit-learn / joblib versions the artifacts were built with.
3. `python scripts\fetch_lfs_object.py --all --under data\development` - materialises the two supplied Mumbai
   CSVs from Git LFS and verifies each file against the checksum inside its pointer.
4. `python scripts\check_gpu.py` - the preflight. It fails unless a tiny fit on `device="cuda"` really ran on a
   GPU. A CPU-only wheel accepts `device="cuda"` and only prints a warning, so the preflight treats that warning
   as a failure rather than reporting a pass.
5. `$env:TRANSITCROWD_XGB_DEVICE = "cuda"`, then the same two `scripts\register_demand_dataset.py` commands as
   `scripts\run_mumbai_registration.sh`: normalize → audit → derive the target from `Estimated_Passenger_Count`
   (the file's own `Target_*` columns are rejected by the audit and never read) → chronological split → candidate
   comparison → champion selection → `transitcrowd.joblib` + `model_report.json` + `station_analytics.json` →
   validation gate → registry entry + the committed `data/inference` copy.
6. `python scripts\benchmark_inference.py --system-id mumbai-local-central` and `--system-id mumbai-metro`.

Useful switches: `-Cpu` (CPU build, no preflight), `-SkipFetch` (sources already downloaded),
`-SystemId mumbai-metro` (one family).

## Linux / WSL

```bash
pip install -r backend/requirements-gpu.txt
python3 scripts/fetch_lfs_object.py --all --under data/development
python3 scripts/check_gpu.py                      # exit 2 = no usable CUDA wheel, training on CPU still works
TRANSITCROWD_XGB_DEVICE=cuda sh scripts/run_mumbai_registration.sh
python3 scripts/benchmark_inference.py --system-id mumbai-local-central
```

## What is and is not a GPU decision

Only the two XGBoost candidates take a device; every other candidate (linear, random forest, SVR, seasonal
naive) runs on CPU either way, so GPU training changes speed and the XGBoost entries of the comparison table, not
the pipeline. The trainers record nothing GPU-specific in the artifact beyond the fitted estimators, which is why
a bundle fitted here and a bundle fitted on a GPU are interchangeable for serving - and why the reports, not the
hardware, are what a reviewer should read.

## Latency, for comparison

Measured in the development sandbox (1 vCPU, 1984 MB RAM, CPU-only build) with `scripts/benchmark_inference.py`:

| family | cold load | p50 | p95 | max | artifact rewritten? |
| --- | --- | --- | --- | --- | --- |
| mumbai-local-central | 4.16 s | 1362.3 ms | 1532.4 ms | 1601.1 ms | no |
| mumbai-metro | 3.97 s | 1584.4 ms | 3249.9 ms | 3868.0 ms | no |

`no` in the last column is the point: a prediction reads the persisted bundle and projects forward, it does not
retrain, cross-validate, re-select a model or rebuild the dataset.
