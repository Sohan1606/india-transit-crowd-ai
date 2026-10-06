"""HTTP endpoints for data-backed India system discovery and predictions."""
from __future__ import annotations
from datetime import date
from fastapi import APIRouter, HTTPException, Query, Request

from backend.app.catalog import OBSERVED_DEMAND_CANDIDATES, known_system, list_systems
from backend.app.inference.service import (
    ForecastHorizonExceeded, InferenceError, InsufficientHistory, ServiceUnavailable,
    UnknownEntity, UnknownSystem,
)
from backend.app.schemas.api import (
    HealthResponse, HeatmapResponse, HistoryResponse, PredictionRequest, PredictionResponse,
    StationComparisonResponse, StationSummary, SystemItem,
)

router = APIRouter(prefix="/api")


def _service(request: Request):
    return request.app.state.inference_service


def _raise_api_error(exc: InferenceError) -> None:
    if isinstance(exc, UnknownEntity):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, UnknownSystem):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ServiceUnavailable):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, (InsufficientHistory, ForecastHorizonExceeded)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail="The request could not be completed.") from exc


def _require_prediction_system(request: Request, system_id: str) -> None:
    catalog = known_system(system_id)
    if catalog is None:
        raise HTTPException(status_code=404, detail=f"Unknown system '{system_id}'. Use GET /api/systems for the discovery catalog.")
    current = next((item for item in list_systems(_service(request)) if item["system_id"] == system_id), catalog)
    if not current.get("prediction_available"):
        # A catalogued system with a verified model family but a missing local
        # artifact/data is a service failure (503), not an unsupported mode.
        if catalog.get("prediction_available") and system_id == "bengaluru-namma-metro":
            return
        reason = current.get("prediction_unavailable_reason") or "No verified observed-demand model is loaded for this system."
        raise HTTPException(status_code=409, detail=f"Prediction unavailable for {current['system_name']} ({system_id}): {reason}")


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(request: Request):
    return _service(request).health()


@router.get("/systems", response_model=list[SystemItem], tags=["discovery"])
def systems(request: Request):
    return list_systems(_service(request))


@router.get("/demand-sources", tags=["discovery"])
def demand_sources():
    return {
        "verified_prediction_source_ids": ["bmrcl-ridership-hourly"],
        "additional_observed_demand_candidates": OBSERVED_DEMAND_CANDIDATES,
        "policy": "A candidate is not enabled until its file, provenance, time granularity and reuse rights are verified. GTFS schedules never constitute observed passenger demand.",
    }


@router.get("/metadata", tags=["data"])
def metadata(request: Request):
    try:
        return _service(request).metadata()
    except InferenceError as exc:
        _raise_api_error(exc)


@router.get("/stations", response_model=list[StationSummary], tags=["discovery"])
def stations(request: Request, system_id: str = Query(min_length=1, max_length=80)):
    _require_prediction_system(request, system_id)
    try:
        return _service(request).station_summaries(system_id)
    except InferenceError as exc:
        _raise_api_error(exc)


@router.post("/predict", response_model=PredictionResponse, tags=["forecast"])
def predict(payload: PredictionRequest, request: Request):
    _require_prediction_system(request, payload.system_id)
    try:
        return _service(request).predict(
            payload.system_id, payload.station_id, payload.target_date.isoformat(), payload.target_hour
        )
    except InferenceError as exc:
        _raise_api_error(exc)


@router.get("/history", response_model=HistoryResponse, tags=["analytics"])
def history(
    request: Request,
    system_id: str = Query(min_length=1, max_length=80),
    station_id: str = Query(min_length=1, max_length=100),
    hours: int = Query(default=168, ge=1, le=720),
    end: str | None = Query(default=None, description="Optional inclusive ISO timestamp in the system's local timezone."),
):
    _require_prediction_system(request, system_id)
    try:
        return _service(request).history(system_id, station_id, hours, end)
    except InferenceError as exc:
        _raise_api_error(exc)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid end timestamp. Use an ISO local timestamp.")


@router.get("/heatmap", response_model=HeatmapResponse, tags=["analytics"])
def heatmap(request: Request, system_id: str = Query(min_length=1, max_length=80),
            station_id: str = Query(min_length=1, max_length=100)):
    _require_prediction_system(request, system_id)
    try:
        return _service(request).heatmap(system_id, station_id)
    except InferenceError as exc:
        _raise_api_error(exc)


@router.get("/station-analytics", tags=["analytics"])
def station_analytics(request: Request):
    try:
        return _service(request).station_analytics()
    except InferenceError as exc:
        _raise_api_error(exc)


@router.get("/model-performance", tags=["models"])
def model_performance(request: Request):
    try:
        return _service(request).model_performance()
    except InferenceError as exc:
        _raise_api_error(exc)


@router.get("/station-comparison", response_model=StationComparisonResponse, tags=["forecast"])
def station_comparison(
    request: Request,
    system_id: str = Query(min_length=1, max_length=80),
    target_date: date = Query(),
    target_hour: int = Query(ge=0, le=23),
    selected_station_id: str | None = Query(default=None, min_length=1, max_length=100),
):
    _require_prediction_system(request, system_id)
    try:
        return _service(request).station_comparison(
            system_id, target_date.isoformat(), target_hour, selected_station_id
        )
    except InferenceError as exc:
        _raise_api_error(exc)
