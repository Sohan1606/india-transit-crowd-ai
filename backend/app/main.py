"""FastAPI entrypoint. Persisted artifacts are loaded; requests never trigger training."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ml.training.registry import model_family_directory, serving_families

from backend.app.api.routes import router
from backend.app.inference.daily_service import DailyDemandInferenceService
from backend.app.inference.service import TransitInferenceService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SYSTEM_ID = "bengaluru-namma-metro"


def _default_data_path() -> Path:
    configured = os.getenv("TRANSITCROWD_DATA")
    return Path(configured) if configured else PROJECT_ROOT / "data/processed/namma_metro_station_hourly.csv"


def _default_model_path() -> Path:
    configured = os.getenv("TRANSITCROWD_MODEL")
    return Path(configured) if configured else PROJECT_ROOT / "backend/models" / DEFAULT_SYSTEM_ID / "transitcrowd.joblib"


def _default_source_metadata_path() -> Path:
    configured = os.getenv("TRANSITCROWD_SOURCE_METADATA")
    return Path(configured) if configured else PROJECT_ROOT / "data/processed/namma_metro_station_hourly.metadata.json"


# Each registered family owns its artifact directory and normalized dataset, so a
# system with unverified or missing data degrades alone instead of disabling the API.
FAMILY_DATASETS = {
    "bengaluru-namma-metro": ("data/processed/namma_metro_station_hourly.csv",
                             "data/processed/namma_metro_station_hourly.metadata.json"),
    "chennai-cmrl-metro": ("data/processed/chennai_metro_demand_timeseries.csv",
                           "data/processed/chennai_metro_demand_timeseries.metadata.json"),
}


def _build_services(models_root: Path) -> dict[str, Any]:
    services: dict[str, Any] = {}
    for system_id, family in serving_families().items():
        # A family carries its own dataset paths once it is registered through
        # scripts/register_demand_dataset.py; the map below remains for the two families
        # that shipped before that path existed.
        data_rel = family.get("dataset_relative_path") or FAMILY_DATASETS.get(system_id, (None, None))[0]
        metadata_rel = family.get("metadata_relative_path") or FAMILY_DATASETS.get(system_id, (None, None))[1]
        if data_rel is None:
            continue
        artifact = model_family_directory(models_root, system_id) / "transitcrowd.joblib"
        data_path = PROJECT_ROOT / data_rel
        meta_path = PROJECT_ROOT / metadata_rel if metadata_rel else None
        constructor = TransitInferenceService if family["granularity"] == "hour" else DailyDemandInferenceService
        services[system_id] = constructor(artifact, data_path, meta_path)
    return services


def create_app(service: TransitInferenceService | None = None, artifact_path: Path | None = None,
               data_path: Path | None = None, source_metadata_path: Path | None = None,
               services: dict[str, Any] | None = None) -> FastAPI:
    app = FastAPI(
        title="India Transit Crowd AI API",
        description=(
            "India transit discovery with artifact-backed passenger-demand prediction only for verified observed-demand data. "
            "Loaded families: Bengaluru Namma Metro/BMRCL station-hour boardings and Chennai Metro CMRL station-day entries. "
            "Predictions for days that have not been observed are labelled MODEL FORECAST; static GTFS is never used as a demand target."
        ),
        version="2.0.0",
        docs_url="/api/docs",
        redoc_url=None,
    )
    if service is None:
        service = TransitInferenceService(
            artifact_path or _default_model_path(), data_path or _default_data_path(),
            source_metadata_path or _default_source_metadata_path(),
        )
    app.state.inference_service = service
    registry = dict(services) if services is not None else _build_services(PROJECT_ROOT / "backend/models")
    if services is None and service is not None:
        # An explicitly injected service must own its family slot, otherwise a caller
        # that only wants to override the Bengaluru service would still be answered by
        # whatever happens to sit on disk.
        registry[str(getattr(service, "system_id", None) or DEFAULT_SYSTEM_ID)] = service
    app.state.services = registry

    allowed = [origin.strip() for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def root():
        return {
            "service": "INDIA TRANSIT CROWD AI",
            "prediction_scope": ("observed-demand predictions for verified model families only: Bengaluru Namma Metro "
                                 "station-hour boardings (hourly) and Chennai Metro station-day entries (daily)"),
            "health": "/api/health", "systems": "/api/systems", "docs": "/api/docs",
        }

    return app


app = create_app()
