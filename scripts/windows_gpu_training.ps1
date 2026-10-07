# Mumbai training on a Windows machine with an NVIDIA GPU: the exact sequence, no source edits.
#
# The two training commands below are the same two commands as scripts/run_mumbai_registration.sh, with the
# paths spelled for Windows; a test asserts that both scripts keep using the same flags. Run from the
# repository root in Windows PowerShell:
#
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\scripts\windows_gpu_training.ps1
#
#   -Cpu          train with the CPU build instead (fully supported, slower)
#   -SkipFetch    keep the source CSVs already downloaded
#   -SystemId mumbai-local-central | mumbai-metro     one family only

[CmdletBinding()]
param(
    [switch]$Cpu,
    [switch]$SkipFetch,
    [string]$SystemId = ""
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$remoteUrl = (git remote get-url origin) -replace '\.git$', ''
$sourceCommit = (git rev-parse --short origin/feature/future-demand-dataset)

Write-Host "==> 1. Python 3.13 virtual environment" -ForegroundColor Cyan
if (-not (Test-Path ".\.venv-transitcrowd\Scripts\python.exe")) { py -3.13 -m venv .\.venv-transitcrowd }
& .\.venv-transitcrowd\Scripts\python.exe -m pip install --upgrade pip | Out-Null
if ($Cpu) {
    Write-Host "==> 2. Requirements: the CPU build (backend\requirements.txt)" -ForegroundColor Cyan
    & .\.venv-transitcrowd\Scripts\python.exe -m pip install -r .\backend\requirements.txt
} else {
    Write-Host "==> 2. Requirements: the CUDA-capable XGBoost build (backend\requirements-gpu.txt)" -ForegroundColor Cyan
    & .\.venv-transitcrowd\Scripts\python.exe -m pip install -r .\backend\requirements-gpu.txt
}

if (-not $SkipFetch) {
    Write-Host "==> 3. Materialise the two Mumbai source CSVs from Git LFS, checksum verified against the pointer" -ForegroundColor Cyan
    & .\.venv-transitcrowd\Scripts\python.exe .\scripts\fetch_lfs_object.py --all --under data\development
}

if (-not $Cpu) {
    Write-Host "==> 4. GPU preflight (a CPU-only wheel that only warns about CUDA is rejected here)" -ForegroundColor Cyan
    & .\.venv-transitcrowd\Scripts\python.exe .\scripts\check_gpu.py --json gpu-preflight.json
    if ($LASTEXITCODE -ne 0) { throw "GPU preflight failed. Fix the driver or install the GPU wheel, or re-run with -Cpu." }
    $env:TRANSITCROWD_XGB_DEVICE = "cuda"
} else { $env:TRANSITCROWD_XGB_DEVICE = "cpu" }
Write-Host "    TRANSITCROWD_XGB_DEVICE=$env:TRANSITCROWD_XGB_DEVICE - the trainers read this, no file is edited" -ForegroundColor Yellow

# The source file's own Target_* columns are rejected by the audit layer, so the only demand column passed
# below is Estimated_Passenger_Count; the next-period target is derived from the chronological series.

if ($SystemId -eq "" -or $SystemId -eq "mumbai-local-central") {
    Write-Host "==> 5. Mumbai Local (Central): normalize, validate, train hourly, persist" -ForegroundColor Cyan
    $py = ".\.venv-transitcrowd\Scripts\python.exe"
    & $py .\scripts\register_demand_dataset.py `
        --csv data\development\synthetic\mumbai_local_all_central_stations_2026_synthetic-1.csv `
        --system-id mumbai-local-central --city "Mumbai" --mode SUBURBAN --operator "Central Railway" `
        --entity-type STATION --granularity hour `
        --timestamp-columns Date,Time `
        --entity-column Source_Station --entity-name-column Source_Station --line-column Line `
        --entity-key-columns Line,Source_Station --fit-window-days 120 `
        --entity-hierarchy-labels "Corridor,From" `
        --route-group-column Line --route-station-column Source_Station --route-position-column Station_Position `
        --demand-column Estimated_Passenger_Count `
        --entity-attribute-columns Line,Source_Station,Station_Position,Peak_Direction `
        --entity-hierarchy-columns Line,Source_Station `
        --measure passengers_per_hour --timezone "Asia/Kolkata" `
        --dataset-class synthetic_development --observation-type modelled_estimate --serve-as demo `
        --source-id mumbai-central-synthetic-2026 `
        --source-url "$remoteUrl/tree/feature/future-demand-dataset/data/development/synthetic" `
        --source-commit "$sourceCommit" `
        --exclude-unobserved-future `
        --licence "Provided by the dataset owner for development use; not a public feed" `
        --redistribution "Supplied private file; never redistributed. Regenerate with scripts/fetch_lfs_object.py." `
        --provenance-statement "Synthetic Central-suburb demand table supplied for development. Data_Type=Synthetic on per Line+station series. Served as a labelled demonstration family, never as live ridership." `
        --write --install-registry --train
    if ($LASTEXITCODE -ne 0) { throw "mumbai-local-central failed" }
}

if ($SystemId -eq "" -or $SystemId -eq "mumbai-metro") {
    Write-Host "==> 6. Mumbai Metro: normalize, validate, train at day granularity, persist" -ForegroundColor Cyan
    $py = ".\.venv-transitcrowd\Scripts\python.exe"
    & $py .\scripts\register_demand_dataset.py `
        --csv data\development\synthetic\Mumbai_Metro_Crowd_Prediction_2026.csv `
        --system-id mumbai-metro --city "Mumbai" --mode METRO --operator "Mumbai Metro (all lines)" `
        --entity-type STATION --granularity day `
        --timestamp-columns Date `
        --entity-column Source_Station --entity-name-column Source_Station --line-column Metro_Line `
        --entity-key-columns Metro_Line,Source_Station,Destination_Station,Time --fit-window-days 150 `
        --entity-hierarchy-labels "Line,From,Towards,Time slot" `
        --demand-column Estimated_Passenger_Count `
        --entity-attribute-columns Metro_Line,Line_Name,Operational_Status,Source_Station,Destination_Station,Time,Stations_On_Line,Travel_Direction `
        --entity-hierarchy-columns Metro_Line,Source_Station,Destination_Station,Time `
        --measure metro_segment_demand --timezone "Asia/Kolkata" `
        --dataset-class synthetic_development --observation-type modelled_estimate --serve-as demo `
        --source-id mumbai-metro-synthetic-2026 `
        --source-url "$remoteUrl/tree/feature/future-demand-dataset/data/development/synthetic" `
        --source-commit "$sourceCommit" `
        --exclude-unobserved-future `
        --licence "Provided by the dataset owner for development use; not a public feed" `
        --redistribution "Supplied private file; never redistributed. Regenerate with scripts/fetch_lfs_object.py." `
        --provenance-statement "Synthetic Mumbai Metro demand table supplied for development, published at six discrete so the target is derived from Estimated_Passenger_Count. Served as a labelled demonstration family." `
        --write --install-registry --train
    if ($LASTEXITCODE -ne 0) { throw "mumbai-metro failed" }
}

Write-Host "==> 7. Inference latency of the persisted bundles (prediction never retrains)" -ForegroundColor Cyan
foreach ($family in @("mumbai-local-central", "mumbai-metro")) {
    if ($SystemId -eq "" -or $SystemId -eq $family) {
        & .\.venv-transitcrowd\Scripts\python.exe .\scripts\benchmark_inference.py --system-id $family --json "$family-latency.json"
    }
}

Write-Host "==> Done." -ForegroundColor Green
Write-Host "    Models:   backend\models\mumbai-*\transitcrowd.joblib (joblib only, no .pkl duplicate; not committed)"
Write-Host "    Reports:  backend\models\mumbai-*\model_report.json, plus the metrics tables in docs\mumbai-*.md"
Write-Host "    Serve:    uvicorn backend.app.main:app --port 8000"
Write-Host "    Whatever hardware produced them, these families stay labelled SYNTHETIC DEMONSTRATION DATA,"
Write-Host "    NOT LIVE PASSENGER RIDERSHIP."
