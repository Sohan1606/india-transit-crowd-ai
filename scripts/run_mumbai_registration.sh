#!/bin/sh
# One-shot, reproducible materialisation of the two Mumbai demo families from the supplied files.
# Sequential on purpose: the box has 1 GB of RAM and each training pass needs most of it.
set -e
cd "$(dirname "$0")/.."

echo "=== Mumbai Local (Central) - hourly, derived next-hour target ==="
python3 scripts/register_demand_dataset.py \
  --csv data/development/synthetic/mumbai_local_all_central_stations_2026_synthetic-1.csv \
  --system-id mumbai-local-central --city "Mumbai" --mode SUBURBAN --operator "Central Railway" \
  --entity-type STATION --granularity hour \
  --timestamp-columns Date,Time \
  --entity-column Source_Station --entity-name-column Source_Station --line-column Line \
  --entity-key-columns Line,Source_Station --fit-window-days 120 \
  --entity-hierarchy-labels "Corridor,From" \
  --route-group-column Line --route-station-column Source_Station --route-position-column Station_Position \
  --demand-column Estimated_Passenger_Count \
  --entity-attribute-columns Line,Source_Station,Station_Position,Peak_Direction \
  --entity-hierarchy-columns Line,Source_Station \
  --measure passengers_per_hour --timezone "Asia/Kolkata" \
  --dataset-class synthetic_development --observation-type modelled_estimate --serve-as demo \
  --source-id mumbai-central-synthetic-2026 \
  --source-url "$(git remote get-url origin | sed 's/\.git$//')/tree/feature/future-demand-dataset/data/development/synthetic" \
  --source-commit "$(git rev-parse --short origin/feature/future-demand-dataset)" \
  --exclude-unobserved-future \
  --licence "Provided by the dataset owner for development use; not a public feed" \
  --redistribution "Supplied private file; never redistributed. Regenerate with scripts/fetch_lfs_object.py." \
  --provenance-statement "Synthetic Central-suburb demand table supplied for development. Data_Type=Synthetic on per Line+station series. Served as a labelled demonstration family, never as live ridership." \
  --write --install-registry --train

echo "=== Mumbai Metro - daily grid with the published slot inside the entity key ==="
python3 scripts/register_demand_dataset.py \
  --csv data/development/synthetic/Mumbai_Metro_Crowd_Prediction_2026.csv \
  --system-id mumbai-metro --city "Mumbai" --mode METRO --operator "Mumbai Metro (all lines)" \
  --entity-type STATION --granularity day \
  --timestamp-columns Date \
  --entity-column Source_Station --entity-name-column Source_Station --line-column Metro_Line \
  --entity-key-columns Metro_Line,Source_Station,Destination_Station,Time --fit-window-days 150 \
  --entity-hierarchy-labels "Line,From,Towards,Time slot" \
  --demand-column Estimated_Passenger_Count \
  --entity-attribute-columns Metro_Line,Line_Name,Operational_Status,Source_Station,Destination_Station,Time,Stations_On_Line,Travel_Direction \
  --entity-hierarchy-columns Metro_Line,Source_Station,Destination_Station,Time \
  --measure metro_segment_demand --timezone "Asia/Kolkata" \
  --dataset-class synthetic_development --observation-type modelled_estimate --serve-as demo \
  --source-id mumbai-metro-synthetic-2026 \
  --source-url "$(git remote get-url origin | sed 's/\.git$//')/tree/feature/future-demand-dataset/data/development/synthetic" \
  --source-commit "$(git rev-parse --short origin/feature/future-demand-dataset)" \
  --exclude-unobserved-future \
  --licence "Provided by the dataset owner for development use; not a public feed" \
  --redistribution "Supplied private file; never redistributed. Regenerate with scripts/fetch_lfs_object.py." \
  --provenance-statement "Synthetic Mumbai Metro demand table supplied for development, published at six discrete so the target is derived from Estimated_Passenger_Count. Served as a labelled demonstration family." \
  --write --install-registry --train

echo "=== done ==="
