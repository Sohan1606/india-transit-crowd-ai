"""HTTP endpoints for data-backed India system discovery and predictions."""
from __future__ import annotations
from datetime import date

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request

from ml.training.registry import get_model_family

from backend.app.catalog import OBSERVED_DEMAND_CANDIDATES, known_system, list_systems
from backend.app.inference.daily_service import GranularityMismatch
from backend.app.inference.service import (
    ForecastHorizonExceeded, InferenceError, InsufficientHistory, ServiceUnavailable,
    UnknownEntity, UnknownSystem,
)
from backend.app.schemas.api import (
    HealthResponse, HeatmapResponse, HistoryResponse, PredictionRequest, PredictionResponse,
    StationComparisonResponse, StationSummary, SystemItem,
)

router = APIRouter(prefix="/api")


def _service(request: Request, system_id: str | None = None):
    """Resolve the inference service that owns a model family.

    Hour- and day-granularity families are separate objects with different feature
    contracts, so a request must be routed by ``system_id`` rather than served by one
    global model. ``app.state.inference_service`` stays the compatibility default.
    """
    services = dict(getattr(request.app.state, "services", {}) or {})
    if system_id:
        selected = services.get(str(system_id))
        if selected is not None:
            return selected
    return request.app.state.inference_service


def _granularity(system_id: str | None) -> str:
    if not system_id:
        return "hour"
    try:
        return str(get_model_family(system_id).get("granularity", "hour"))
    except ValueError:
        return "hour"


def _hour_target_required(system_id: str, target_hour) -> int:
    if target_hour is None:
        raise HTTPException(status_code=422, detail=(
            f"{system_id} is an hour-granularity model family: target_hour (0-23) is required. "
            "Day-granularity families such as chennai-cmrl-metro accept a date only."))
    return int(target_hour)


def _raise_api_error(exc: InferenceError) -> None:
    if isinstance(exc, UnknownEntity):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, UnknownSystem):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ServiceUnavailable):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, (InsufficientHistory, ForecastHorizonExceeded)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, GranularityMismatch):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail="The request could not be completed.") from exc


def _require_prediction_system(request: Request, system_id: str) -> None:
    catalog = known_system(system_id)
    if catalog is None:
        raise HTTPException(status_code=404, detail=f"Unknown system '{system_id}'. Use GET /api/systems for the discovery catalog.")
    services = dict(getattr(request.app.state, "services", {}) or {})
    current = next((item for item in list_systems(_service(request), services) if item["system_id"] == system_id), catalog)
    if not current.get("prediction_available"):
        # A catalogued system with a verified model family but a missing local
        # artifact/data is a service failure (503), not an unsupported mode.
        if catalog.get("prediction_available") and system_id in services:
            return
        reason = current.get("prediction_unavailable_reason") or "No verified observed-demand model is loaded for this system."
        raise HTTPException(status_code=409, detail=f"Prediction unavailable for {current['system_name']} ({system_id}): {reason}")


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(request: Request, system_id: str | None = Query(default=None, max_length=80)):
    return _service(request, system_id).health()


@router.get("/systems", response_model=list[SystemItem], tags=["discovery"])
def systems(request: Request):
    return list_systems(_service(request), dict(getattr(request.app.state, "services", {}) or {}))


@router.get("/demand-sources", tags=["discovery"])
def demand_sources():
    return {
        "verified_prediction_source_ids": ["bmrcl-ridership-hourly", "cmrl-passenger-flow-daily"],
        "granularity_by_source": {"bmrcl-ridership-hourly": "station-hour", "cmrl-passenger-flow-daily": "station-day"},
        "additional_observed_demand_candidates": OBSERVED_DEMAND_CANDIDATES,
        "policy": "A candidate is not enabled until its file, provenance, time granularity and reuse rights are verified. GTFS schedules never constitute observed passenger demand.",
    }


@router.get("/metadata", tags=["data"])
def metadata(request: Request, system_id: str | None = Query(default=None, max_length=80)):
    try:
        return _service(request, system_id).metadata()
    except InferenceError as exc:
        _raise_api_error(exc)


@router.get("/stations", response_model=list[StationSummary], tags=["discovery"])
def stations(request: Request, system_id: str = Query(min_length=1, max_length=80)):
    _require_prediction_system(request, system_id)
    try:
        summaries = _service(request, system_id).station_summaries(system_id)
        granularity = _granularity(system_id)
        for item in summaries:
            item["granularity"] = granularity
        return summaries
    except InferenceError as exc:
        _raise_api_error(exc)


@router.post("/predict", response_model=PredictionResponse, tags=["forecast"])
def predict(payload: PredictionRequest, request: Request):
    _require_prediction_system(request, payload.system_id)
    if _granularity(payload.system_id) == "hour":
        _hour_target_required(payload.system_id, payload.target_hour)
    try:
        result = _service(request, payload.system_id).predict(
            payload.system_id, payload.station_id, payload.target_date.isoformat(), payload.target_hour
        )
        result.setdefault("granularity", _granularity(payload.system_id))
        return result
    except InferenceError as exc:
        _raise_api_error(exc)


@router.get("/history", response_model=HistoryResponse, tags=["analytics"])
def history(
    request: Request,
    system_id: str = Query(min_length=1, max_length=80),
    station_id: str = Query(min_length=1, max_length=100),
    hours: int = Query(default=168, ge=1, le=720),
    days: int | None = Query(default=None, ge=1, le=730),
    end: str | None = Query(default=None, description="Optional inclusive ISO timestamp in the system's local timezone."),
):
    _require_prediction_system(request, system_id)
    granularity = _granularity(system_id)
    if granularity == "day" and days is None and hours != 168:
        raise HTTPException(status_code=409, detail=(
            f"{system_id} stores daily observations; use ?days=N instead of ?hours=N."))
    count = days if granularity == "day" else hours
    if count is None:
        count = 60
    try:
        return _service(request, system_id).history(system_id, station_id, count, end)
    except InferenceError as exc:
        _raise_api_error(exc)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid end timestamp. Use an ISO local timestamp.")


@router.get("/heatmap", response_model=HeatmapResponse, tags=["analytics"])
def heatmap(request: Request, system_id: str = Query(min_length=1, max_length=80),
            station_id: str = Query(min_length=1, max_length=100)):
    _require_prediction_system(request, system_id)
    try:
        return _service(request, system_id).heatmap(system_id, station_id)
    except InferenceError as exc:
        _raise_api_error(exc)


@router.get("/weekly-pattern", tags=["analytics"])
def weekly_pattern(request: Request, system_id: str = Query(min_length=1, max_length=80),
                   station_id: str = Query(min_length=1, max_length=100)):
    """Observed day-of-week profile; the honest substitute for an hourly heatmap at day granularity."""
    _require_prediction_system(request, system_id)
    service = _service(request, system_id)
    if not hasattr(service, "weekly_pattern"):
        raise HTTPException(status_code=409, detail=(
            f"{system_id} is an hour-granularity family; GET /api/heatmap already reports its hour-of-day pattern."))
    try:
        return service.weekly_pattern(system_id, station_id)
    except InferenceError as exc:
        _raise_api_error(exc)


@router.get("/station-analytics", tags=["analytics"])
def station_analytics(request: Request, system_id: str | None = Query(default=None, max_length=80)):
    try:
        return _service(request, system_id).station_analytics()
    except InferenceError as exc:
        _raise_api_error(exc)


@router.get("/model-performance", tags=["models"])
def model_performance(request: Request, system_id: str | None = Query(default=None, max_length=80)):
    try:
        return _service(request, system_id).model_performance()
    except InferenceError as exc:
        _raise_api_error(exc)


@router.get("/station-comparison", response_model=StationComparisonResponse, tags=["forecast"])
def station_comparison(
    request: Request,
    system_id: str = Query(min_length=1, max_length=80),
    target_date: date = Query(),
    target_hour: int | None = Query(default=None, ge=0, le=23),
    selected_station_id: str | None = Query(default=None, min_length=1, max_length=100),
):
    _require_prediction_system(request, system_id)
    hour = target_hour if _granularity(system_id) == "day" else _hour_target_required(system_id, target_hour)
    try:
        return _service(request, system_id).station_comparison(
            system_id, target_date.isoformat(), hour, selected_station_id
        )
    except InferenceError as exc:
        _raise_api_error(exc)


@router.get("/future-preview", tags=["forecast"])
def future_preview(request: Request, system_id: str = Query(min_length=1, max_length=80),
                   days: int = Query(default=7, ge=1, le=31)):
    """Model forecasts for the next unobserved days. Nothing here is an observation."""
    _require_prediction_system(request, system_id)
    service = _service(request, system_id)
    if not hasattr(service, "future_preview"):
        raise HTTPException(status_code=409, detail=(
            f"{system_id} is an hour-granularity family; use GET /api/station-comparison with a target date and hour, "
            "which projects past the last observation with the same labelled forecast semantics."))
    try:
        return service.future_preview(system_id, days)
    except InferenceError as exc:
        _raise_api_error(exc)


@router.get("/source-gap", tags=["data"])
def source_gap(request: Request, system_id: str = Query(min_length=1, max_length=80)):
    """How far the observation archive lags today, so 'future' is never ambiguous."""
    _require_prediction_system(request, system_id)
    service = _service(request, system_id)
    if not hasattr(service, "source_gap_report"):
        return {
            "system_id": system_id, "live_feed": False,
            "data_frontier": str(pd.Timestamp(service.hourly["timestamp"].max()).date()) if service.hourly is not None else None,
            "days_behind_today": None,
            "interpretation": ("Hourly family: the bundled BMRCL archive is a historical snapshot, not a live feed; "
                              "predictions beyond its last observed hour are labelled post_snapshot_projection."),
        }
    try:
        return service.source_gap_report()
    except InferenceError as exc:
        _raise_api_error(exc)
