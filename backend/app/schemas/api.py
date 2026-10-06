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
    target_hour: int | None = Field(
        default=None, ge=0, le=23,
        description="Required for hour-granularity families; omit for day-granularity families such as chennai-cmrl-metro.",
    )

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
    granularity: Literal["hour", "day"] | None = None
    station_count: int | None = None
    data_period: list[dict[str, Any]] = Field(default_factory=list)


class StationSummary(BaseModel):
    station_id: str
    station_name: str
    mean_hourly_boardings: float
    latest_observation: str
    observed_hours: int
    system_id: str
    # Day-granularity families report the same two facts in their own unit; the
    # hourly fields above are kept so existing clients keep working.
    granularity: Literal["hour", "day"] | None = None
    mean_daily_entries: float | None = None
    observed_days: int | None = None


class PredictionResponse(BaseModel):
    """Shared response for hour- and day-granularity families.

    Fields that only one granularity can answer are optional rather than being given a
    fake value: a daily model must not report an hour, and an hourly model must not
    report a day total. ``forecast_kind`` and ``is_model_forecast`` say whether the
    target day/hour has been observed yet, so a historical replay is never presented as
    a future forecast.
    """

    system_id: str
    station_id: str
    station_name: str
    target_timestamp: str
    origin_timestamp: str
    granularity: Literal["hour", "day"] | None = None
    predicted_boardings: float | None = None
    predicted_entries: float | None = None
    predicted_demand: float | None = None
    measure: str
    unit: str | None = None
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
    model_version: str | None = None
    forecast_horizon_hours: int | None = None
    forecast_horizon_days: int | None = None
    is_recursive_forecast: bool
    is_model_forecast: bool | None = None
    forecast_kind: str
    origin_basis: Literal["previous_observed_period", "data_frontier_recursive_seed"] | None = None
    unit: str | None = None
    # Scoring against the source observation for the requested period. When the source has not
    # published that period there is no actual value and none is invented: the fields below say
    # so explicitly instead of being omitted, so a client cannot read silence as zero error.
    actual_observed_demand: float | None = None
    observation_status: Literal["OBSERVED", "OBSERVED VALUE UNAVAILABLE"] | None = None
    observation_rows: int | None = None
    evaluation_status: str | None = None
    absolute_error: float | None = None
    signed_error: float | None = None
    absolute_percentage_error: float | None = None
    error_note: str | None = None
    # Horizon governance: how far this projection reaches, how accurate that far-out answer is
    # known to be, and the empirical (not calibrated) interval that the measurement supports.
    horizon_status: Literal["within_validated_range", "beyond_validated_range", "unmeasured",
                            "not_applicable_historical"] | None = None
    horizon_validation: dict[str, Any] | None = None
    forecast_interval: dict[str, Any] | None = None
    forecast_note: str
    data_frontier: str | None = None
    target_date: str | None = None
    training_cutoff: str | None = None
    generated_at_utc: str | None = None
    data_freshness_days: int | None = None
    target_column: str | None = None
    explanation: list[dict[str, Any]]
    explanation_method: str
    recommendation: dict[str, Any]
    evaluation_context: dict[str, Any] | None = None


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
    predicted_daily_entries: float | None = None


class StationComparisonResponse(BaseModel):
    system_id: str
    target_timestamp: str
    comparison_basis: str
    stations: list[StationComparisonItem]
    stations_without_estimate: int
    forecast_horizon_days: int | None = None
    is_model_forecast: bool | None = None
