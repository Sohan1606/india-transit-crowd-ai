"""FastAPI entrypoint. Persisted artifacts are loaded; requests never trigger training."""
from __future__ import annotations
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.api.routes import router
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


def create_app(service: TransitInferenceService | None = None, artifact_path: Path | None = None,
               data_path: Path | None = None, source_metadata_path: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="India Transit Crowd AI API",
        description=(
            "India transit discovery with artifact-backed passenger-demand prediction only for verified observed-demand data. "
            "The bundled model covers historical Bengaluru Namma Metro/BMRCL station-hour boardings; static GTFS is never used as a demand target."
        ),
        version="2.0.0",
        docs_url="/api/docs",
        redoc_url=None,
    )
    if service is None:
        service = TransitInferenceService(
            artifact_path or _default_model_path(),
            data_path or _default_data_path(),
            source_metadata_path or _default_source_metadata_path(),
        )
    app.state.inference_service = service

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
            "prediction_scope": "Bengaluru Namma Metro/BMRCL observed station-hour boardings only",
            "health": "/api/health", "systems": "/api/systems", "docs": "/api/docs",
        }

    return app


app = create_app()
