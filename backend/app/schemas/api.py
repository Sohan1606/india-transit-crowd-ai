"""Pydantic contracts for system-aware transit discovery and inference."""
from __future__ import annotations
from datetime import date
import re
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PredictionRequest(StrictRequest):
    system_id: str = Field(min_length=1, max_length=80, examples=["bengaluru-namma-metro"])
    station_id: str = Field(min_length=1, max_length=100, examples=["majestic"])
    target_date: date
    target_hour: int = Field(ge=0, le=23)

    @field_validator("system_id", "station_id")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        slug = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise ValueError("System and station IDs must be lowercase hyphen-separated identifiers.")
        return slug


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    model_ready: bool
    data_ready: bool
    system_id: str | None = None
    model_version: str | None = None
    detail: str | None = None


class SystemItem(BaseModel):
    system_id: str
    system_name: str
    city: str
    state: str
    mode: str
    operator: str
    prediction_available: bool
    prediction_status: str
    observed_demand_status: str
    demand_source_url: str | None = None
    network_reference_url: str | None = None
    network_reference_kind: str
    network_reference_note: str
    prediction_unavailable_reason: str | None = None
    station_count: int | None = None
    data_period: list[dict[str, Any]] = Field(default_factory=list)


class StationSummary(BaseModel):
    station_id: str
    station_name: str
    mean_hourly_boardings: float
    latest_observation: str
    observed_hours: int
    system_id: str


class PredictionResponse(BaseModel):
    system_id: str
    station_id: str
    station_name: str
    target_timestamp: str
    origin_timestamp: str
    predicted_boardings: float
    measure: str
    relative_demand_band: Literal["LOW", "MODERATE", "HIGH", "SEVERE"]
    risk: Literal["LOW", "MODERATE", "HIGH", "SEVERE"]
    risk_method: str
    risk_thresholds: dict[str, float]
    threshold_sample_count: int
    historical_percentile: float | None
    classification_check: str
    classification_agrees: bool
    regression_model: str
    classification_model: str
    forecast_horizon_hours: int
    is_recursive_forecast: bool
    forecast_kind: str
    forecast_note: str
    explanation: list[dict[str, Any]]
    explanation_method: str
    recommendation: dict[str, Any]


class HistoryPoint(BaseModel):
    timestamp: str
    observed_boardings: float
    observation_type: Literal["observed"] = "observed"


class HistoryResponse(BaseModel):
    system_id: str
    station_id: str
    points: list[HistoryPoint]
    measure: str
    source: str


class HeatmapCell(BaseModel):
    day_of_week: int
    day_name: str
    hour: int
    mean_observed_boardings: float | None
    observations: int


class HeatmapResponse(BaseModel):
    system_id: str
    station_id: str
    cells: list[HeatmapCell]
    measure: str
    source: str


class StationComparisonItem(BaseModel):
    station_id: str
    station_name: str
    predicted_boardings: float
    relative_demand_band: str
    historical_percentile: float | None
    is_selected: bool


class StationComparisonResponse(BaseModel):
    system_id: str
    target_timestamp: str
    comparison_basis: str
    stations: list[StationComparisonItem]
    stations_without_estimate: int
