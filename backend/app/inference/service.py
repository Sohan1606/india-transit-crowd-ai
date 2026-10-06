"""Artifact-backed inference for registered India transit systems.

The service exposes only model families whose observed-demand source has been
verified and whose matching artifacts are loaded. It never trains on requests
or converts static GTFS schedules into passenger counts.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from ml.data_pipeline.cleaning import clean_normalized_demand
from ml.data_pipeline.source import BMRCL_TIMEZONE
from ml.features.forecasting import FEATURE_COLUMNS, features_for_target
from ml.training.registry import get_model_family
from ml.training.risk import RISK_ORDER, classify_demand, historical_percentile, resolve_thresholds


class InferenceError(RuntimeError):
    pass


class ServiceUnavailable(InferenceError):
    pass


class UnknownSystem(InferenceError):
    pass


class UnknownEntity(InferenceError):
    pass


class InsufficientHistory(InferenceError):
    pass


class ForecastHorizonExceeded(InferenceError):
    pass


# Compatibility names for downstream callers that used the pre-migration service.
UnknownRoute = UnknownEntity

FEATURE_LABELS = {
    "hour": "Target clock hour",
    "day_of_week": "Target day of week",
    "day_of_month": "Target day of month",
    "month": "Target month",
    "week_of_year": "Target week of year",
    "is_weekend": "Weekend indicator",
    "is_peak_hour": "Peak-hour calendar indicator",
    "lag_1": "Previous-hour station boardings",
    "lag_24": "Same clock hour yesterday",
    "lag_168": "Same clock hour last week",
    "rolling_mean_3": "Previous 3-hour mean",
    "rolling_mean_24": "Previous 24-hour mean",
    "rolling_mean_168": "Previous 7-day mean",
    "rolling_std_24": "Previous 24-hour variability",
    "rolling_std_168": "Previous 7-day variability",
    "same_hour_previous_day": "Observed boardings 24 hours earlier",
    "same_hour_previous_week": "Observed boardings 7 days earlier",
    "entity_id": "Station identity",
}


class TransitInferenceService:
    def __init__(self, artifact_path: Path, data_path: Path, source_metadata_path: Path | None = None):
        self.bundle: dict[str, Any] | None = None
        self.hourly: pd.DataFrame | None = None
        self.unavailable_detail: str | None = None
        self.station_analytics_data: dict[str, Any] | None = None
        self.artifact_path = artifact_path
        self.data_path = data_path
        self.source_metadata_path = source_metadata_path
        self.source_metadata: dict[str, Any] = {}
        self.timezone = BMRCL_TIMEZONE
        try:
            if artifact_path.is_file():
                loaded = joblib.load(artifact_path)
                if not isinstance(loaded, dict) or not {"regression_model", "classification_model", "risk_thresholds", "system_id"}.issubset(loaded):
                    raise ValueError("Artifact does not contain a current India model-family bundle.")
                self.bundle = loaded
                family = get_model_family(str(loaded["system_id"]))
                self.timezone = str(family.get("timezone", BMRCL_TIMEZONE))
            else:
                self.unavailable_detail = f"Model artifact not found: {artifact_path.name}"
        except Exception as exc:
            self.unavailable_detail = f"Model artifact could not be loaded ({type(exc).__name__})."
            self.bundle = None

        try:
            if data_path.is_file():
                normalized, _ = clean_normalized_demand(pd.read_csv(data_path), timezone=self.timezone)
                self.hourly = normalized
            elif self.unavailable_detail is None:
                self.unavailable_detail = f"Normalized observed-demand data not found: {data_path.name}"
        except Exception as exc:
            self.hourly = None
            self.unavailable_detail = f"Normalized observed-demand data could not be loaded ({type(exc).__name__})."

        if source_metadata_path and source_metadata_path.is_file():
            try:
                self.source_metadata = json.loads(source_metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.source_metadata = {}

        if self.bundle and self.hourly is not None:
            artifact_system = str(self.bundle.get("system_id"))
            present_systems = set(self.hourly["system_id"].astype(str).unique())
            trained = set(map(str, self.bundle.get("entity_ids", [])))
            present = set(self.hourly.loc[self.hourly["system_id"].astype(str).eq(artifact_system), "entity_id"].astype(str))
            if present_systems != {artifact_system} or not trained or not trained.issubset(present):
                self.unavailable_detail = "Model-family system/entity IDs do not match the normalized observed-demand dataset."
                self.bundle = None
                self.hourly = None
            elif self.source_metadata.get("normalized_sha256"):
                actual_hash = hashlib.sha256(data_path.read_bytes()).hexdigest()
                if actual_hash != self.source_metadata["normalized_sha256"]:
                    self.unavailable_detail = "Normalized dataset checksum does not match the source metadata sidecar. Re-run data preparation and model validation."
                    self.bundle = None
                    self.hourly = None

    @property
    def system_id(self) -> str | None:
        return str(self.bundle["system_id"]) if self.bundle else None

    @property
    def model_ready(self) -> bool:
        return self.bundle is not None

    @property
    def data_ready(self) -> bool:
        return self.hourly is not None and not self.hourly.empty

    @property
    def ready(self) -> bool:
        return self.model_ready and self.data_ready

    @property
    def entity_ids(self) -> list[str]:
        if not self.ready:
            return []
        present = set(self.hourly.loc[self.hourly["system_id"].astype(str).eq(self.system_id), "entity_id"].astype(str))
        return sorted(present & set(map(str, self.bundle.get("entity_ids", []))))

    @property
    def stations(self) -> list[str]:
        return self.entity_ids

    def _require_ready(self, system_id: str | None = None) -> str:
        if not self.ready:
            raise ServiceUnavailable(self.unavailable_detail or "Verified model artifacts or normalized observed data are unavailable.")
        requested = str(system_id or self.system_id)
        if requested != self.system_id:
            raise UnknownSystem(
                f"Prediction is unavailable for '{requested}'. The only loaded verified model family is '{self.system_id}'."
            )
        return requested

    def _require_entity(self, station_id: str, system_id: str | None = None) -> str:
        self._require_ready(system_id)
        normalized = str(station_id).strip()
        if normalized not in self.entity_ids:
            raise UnknownEntity(f"Unknown or untrained station '{normalized}'. Choose an ID returned by GET /api/stations.")
        return normalized

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.ready else "degraded",
            "model_ready": self.model_ready,
            "data_ready": self.data_ready,
            "system_id": self.system_id,
            "model_version": self.bundle.get("model_version") if self.bundle else None,
            "detail": None if self.ready else self.unavailable_detail,
        }

    def metadata(self) -> dict[str, Any]:
        system_id = self._require_ready()
        data = self.hourly.loc[self.hourly["system_id"].astype(str).eq(system_id)
                               & self.hourly["entity_id"].astype(str).isin(self.entity_ids)]
        first = pd.Timestamp(data["timestamp"].min())
        latest = pd.Timestamp(data["timestamp"].max())
        default_station = self.entity_ids[0]
        station_latest = pd.Timestamp(data.loc[data["entity_id"].eq(default_station), "timestamp"].max())
        default_target = station_latest + pd.Timedelta(hours=1)
        family = dict(self.bundle.get("model_family", {}))
        source_meta = self.source_metadata or self.bundle.get("dataset_metadata", {})
        return {
            "project": "INDIA TRANSIT CROWD AI",
            "tagline": "PREDICT THE CROWD. PLAN THE JOURNEY.",
            "system_id": system_id,
            "city": family.get("city", "Bengaluru"),
            "mode": family.get("mode", "METRO"),
            "operator": family.get("operator", "BMRCL"),
            "model_scope": "Verified observed-demand prediction is available only for Bengaluru Namma Metro/BMRCL station-hour boardings in this historical snapshot.",
            "timezone": self.timezone,
            "dataset": {
                "title": source_meta.get("source_title", "BMRCL/Namma Metro station-hour ridership"),
                "source_url": source_meta.get("source_url", "https://github.com/Vonter/bmrcl-ridership-hourly"),
                "source_data_url": source_meta.get("source_data_url"),
                "source_commit": source_meta.get("upstream_commit"),
                "source_sha256": source_meta.get("source_sha256"),
                "license": source_meta.get("license", "ODbL-1.0"),
                "license_url": source_meta.get("license_url"),
                "attribution": source_meta.get("attribution"),
                "granularity": "one observed station-hour",
                "measure": "station boardings/entries, not physical occupancy or onboard load",
                "timestamp_min": first.isoformat(),
                "timestamp_max": latest.isoformat(),
                "observed_rows": int(len(data)),
                "station_count": len(self.entity_ids),
                "station_ids": self.entity_ids,
                "station_names": self.bundle.get("entity_names", {}),
                "source_periods": source_meta.get("source_periods", []),
                "explicit_zero_observations": int(data["demand_count"].eq(0).sum()),
                "missing_observations_filled": 0,
                "source_metadata": source_meta,
                "is_live": False,
            },
            "features": {"count": len(FEATURE_COLUMNS), "columns": FEATURE_COLUMNS},
            "primary_target": "target_next_hour_demand",
            "risk_definition": "Historical-relative demand bands fitted on training targets; not capacity, occupancy or safety thresholds.",
            "default_station_id": default_station,
            "default_target_date": default_target.strftime("%Y-%m-%d"),
            "default_target_hour": int(default_target.hour),
            "default_target_timestamp": default_target.isoformat(),
            "prediction_max_recursive_horizon_hours": self.bundle.get("max_recursive_horizon_hours", 336),
            "regression_champion": self.bundle.get("regression_model_key"),
            "classification_champion": self.bundle.get("classification_model_key"),
        }

    def station_summaries(self, system_id: str | None = None) -> list[dict[str, Any]]:
        selected_system = self._require_ready(system_id)
        data = self.hourly.loc[
            self.hourly["system_id"].astype(str).eq(selected_system)
            & self.hourly["entity_id"].astype(str).isin(self.entity_ids)
        ]
        summaries = data.groupby(["entity_id", "entity_name"], sort=True).agg(
            mean_hourly_boardings=("demand_count", "mean"),
            latest_observation=("timestamp", "max"),
            observed_hours=("demand_count", "count"),
        ).reset_index()
        return [{
            "station_id": str(row.entity_id),
            "station_name": str(row.entity_name),
            "mean_hourly_boardings": float(row.mean_hourly_boardings),
            "latest_observation": pd.Timestamp(row.latest_observation).isoformat(),
            "observed_hours": int(row.observed_hours),
            "system_id": selected_system,
        } for row in summaries.itertuples()]

    def _target_timestamp(self, target_date: str, target_hour: int) -> pd.Timestamp:
        try:
            target = pd.Timestamp(f"{target_date} {int(target_hour):02d}:00:00")
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid local target date or hour.") from exc
        return target.tz_localize(self.timezone).floor("h")

    def _classify_with_model(self, X: pd.DataFrame) -> str:
        model = self.bundle["classification_model"]
        key = self.bundle.get("classification_model_key", "")
        value = np.asarray(model.predict(X)).reshape(-1)[0]
        return RISK_ORDER[int(value)] if key == "xgboost" else str(value)

    def _regress(self, X: pd.DataFrame) -> float:
        raw = float(np.asarray(self.bundle["regression_model"].predict(X)).reshape(-1)[0])
        return max(0.0, raw)

    def _predict_core(self, station_id: str, target: pd.Timestamp, system_id: str | None = None) -> dict[str, Any]:
        selected_system = self._require_ready(system_id)
        station_id = self._require_entity(station_id, selected_system)
        target = pd.Timestamp(target)
        target = target.tz_localize(self.timezone) if target.tzinfo is None else target.tz_convert(self.timezone)
        target = target.floor("h")
        station_data = self.hourly.loc[
            self.hourly["system_id"].astype(str).eq(selected_system)
            & self.hourly["entity_id"].astype(str).eq(station_id)
        ].copy()
        latest = pd.Timestamp(station_data["timestamp"].max())
        horizon = int((target - latest).total_seconds() // 3600) if target > latest else 0
        maximum = int(self.bundle.get("max_recursive_horizon_hours", 336))
        if horizon > maximum:
            raise ForecastHorizonExceeded(
                f"Target is {horizon} hours beyond the latest observed hour for {station_id}; the recursive limit is {maximum} hours."
            )
        if target > latest:
            history = station_data[["timestamp", "entity_id", "demand_count"]].copy()
            predicted: float | None = None
            final_features: pd.DataFrame | None = None
            for step in range(1, horizon + 1):
                step_target = latest + pd.Timedelta(hours=step)
                try:
                    final_features = features_for_target(history, station_id, step_target, timezone=self.timezone)
                except ValueError as exc:
                    raise InsufficientHistory(str(exc)) from exc
                predicted = self._regress(final_features[FEATURE_COLUMNS])
                history = pd.concat([history, pd.DataFrame([{
                    "timestamp": step_target, "entity_id": station_id, "demand_count": predicted,
                }])], ignore_index=True)
            demand = float(predicted)
            X = final_features[FEATURE_COLUMNS]
            recursive = True
        else:
            try:
                final_features = features_for_target(station_data, station_id, target, timezone=self.timezone)
            except ValueError as exc:
                raise InsufficientHistory(str(exc)) from exc
            X = final_features[FEATURE_COLUMNS]
            demand = self._regress(X)
            recursive = False

        risk, threshold_source = classify_demand(
            demand, station_id, selected_system, self.bundle["risk_thresholds"]
        )
        threshold, _ = resolve_thresholds(station_id, selected_system, self.bundle["risk_thresholds"])
        percentile = historical_percentile(
            demand, station_id, selected_system, self.bundle.get("training_distributions", {})
        )
        if not np.isfinite(percentile):
            percentile = None
        classifier_risk = self._classify_with_model(X)
        observed_target = bool(
            station_data["timestamp"].eq(target).any()
        )
        forecast_kind = (
            "post_snapshot_projection" if target > latest
            else "historical_replay" if observed_target
            else "unobserved_hour_estimate"
        )
        if recursive and horizon > 1:
            note = "Recursive snapshot projection from the latest observed station-hour; model error may compound. No calibrated uncertainty interval is available."
        elif target > latest:
            note = "Projection from the latest published BMRCL observation; the archive is historical, not a live feed, and the target may be in the past relative to today."
        elif observed_target:
            note = "Historical one-step replay using only observations strictly before the target; the target itself is not used as a feature."
        else:
            note = "Estimate for an hour with no published target observation, using only earlier observed features; missing target data is not treated as zero."
        aligned = station_data.loc[station_data["timestamp"].eq(target)]
        if aligned.empty:
            scoring = {
                "actual_observed_demand": None, "observation_status": "OBSERVED VALUE UNAVAILABLE",
                "evaluation_status": ("not_scored_future_period" if target > latest else "not_scorable_no_observation_for_target"),
                "absolute_error": None, "signed_error": None, "absolute_percentage_error": None,
                "error_note": ("The BMRCL archive holds no observation for this station-hour, so there is nothing to "
                               "compare against. It has not been estimated, interpolated or replaced with zero."),
            }
        else:
            observed = float(pd.to_numeric(aligned["demand_count"], errors="coerce").iloc[-1])
            absolute_error = abs(demand - observed)
            scoring = {
                "actual_observed_demand": observed, "observation_status": "OBSERVED",
                "observation_rows": int(len(aligned)), "evaluation_status": "scored_against_observation",
                "absolute_error": float(absolute_error), "signed_error": float(demand - observed),
                "absolute_percentage_error": float(absolute_error / observed * 100.0) if observed else None,
                "error_note": ("Actual value is the observation stored in the archive for this station-hour; it was not a "
                               "model input. A historical replay is scored for transparency, not as out-of-sample accuracy."),
            }
        scoring["horizon_status"] = "unmeasured"
        scoring["horizon_validation"] = {
            "status": "not_available_for_this_artifact",
            "detail": ("The hour-granularity artifact predates horizon banding, so no per-horizon accuracy claim is "
                       "attached; error growth for recursive projections is documented in the model report instead."),
            "max_recursive_horizon_hours": int(self.bundle.get("max_recursive_horizon_hours", 336)),
        }
        scoring["forecast_interval"] = None
        return {
            "system_id": selected_system,
            "station_id": station_id,
            "station_name": str(station_data["entity_name"].iloc[0]),
            "target_timestamp": target.isoformat(),
            "origin_timestamp": (latest if (recursive and horizon > 1) else target - pd.Timedelta(hours=1)).isoformat(),
            "origin_basis": ("data_frontier_recursive_seed" if (recursive and horizon > 1) else "previous_observed_period"),
            "data_frontier": latest.isoformat(),
            "predicted_boardings": float(demand),
            "measure": str(self._family_label("measure") or "hourly_station_boardings"),
            "unit": str(self._family_label("unit") or "passengers boarding the station in that clock hour"),
            "relative_demand_band": risk,
            "risk": risk,
            "risk_method": threshold_source,
            "risk_thresholds": {key: float(threshold[key]) for key in ("q50", "q80", "q95")},
            "threshold_sample_count": int(threshold.get("sample_count", 0)),
            "historical_percentile": percentile,
            "classification_check": classifier_risk,
            "classification_agrees": classifier_risk == risk,
            "regression_model": self.bundle.get("regression_model_key", "unknown"),
            "classification_model": self.bundle.get("classification_model_key", "unknown"),
            "forecast_horizon_hours": horizon,
            "is_recursive_forecast": recursive,
            "forecast_kind": forecast_kind,
            "forecast_note": note,
            **scoring,
            "_features": final_features,
        }

    def _family_label(self, key: str) -> str | None:
        """Registry/bundle metadata for this family, or None when it carries none."""
        value = dict(self.bundle.get("model_family") or {}).get(key)
        if value:
            return str(value)
        try:
            return str(get_model_family(str(self.system_id)).get(key) or "") or None
        except ValueError:
            return None

    def _local_explanation(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        model = self.bundle["regression_model"]
        features: pd.DataFrame = result["_features"][FEATURE_COLUMNS].copy()
        base_prediction = float(result["predicted_boardings"])
        sensitivities = []
        for column in self.bundle.get("numeric_features", []):
            reference = self.bundle.get("training_medians", {}).get(column)
            if reference is None or not np.isfinite(float(reference)):
                continue
            changed = features.copy()
            actual_value = float(changed.iloc[0][column])
            changed.loc[changed.index[0], column] = float(reference)
            counterfactual = max(0.0, float(np.asarray(model.predict(changed)).reshape(-1)[0]))
            delta = base_prediction - counterfactual
            sensitivities.append({
                "feature": column,
                "label": FEATURE_LABELS.get(column, column.replace("_", " ").title()),
                "actual_value": actual_value,
                "reference_value": float(reference),
                "prediction_with_reference": counterfactual,
                "delta_boardings": float(delta),
                "absolute_delta": float(abs(delta)),
                "direction": "raises the model output versus its training-median reference" if delta > 0 else "lowers the model output versus its training-median reference" if delta < 0 else "no change in this one-feature perturbation",
            })
        sensitivities.sort(key=lambda entry: entry["absolute_delta"], reverse=True)
        return sensitivities[:6]

    def predict(self, system_id: str, station_id: str, target_date: str, target_hour: int) -> dict[str, Any]:
        target = self._target_timestamp(target_date, target_hour)
        result = self._predict_core(station_id, target, system_id)
        result["explanation"] = self._local_explanation(result)
        result["explanation_method"] = (
            "Model-backed sensitivity, not SHAP: each numeric feature is replaced individually with its training-partition median and the persisted regression model is re-run. "
            "The signed delta is descriptive, not causal; correlated features are not jointly adjusted."
        )
        result["recommendation"] = self._recommend(result)
        result.pop("_features", None)
        return result

    def _recommend(self, selected: dict[str, Any]) -> dict[str, Any]:
        selected_time = pd.Timestamp(selected["target_timestamp"])
        candidates: list[dict[str, Any]] = []
        failures = 0
        for offset in (-3, -2, -1, 1, 2, 3):
            alternative_time = selected_time + pd.Timedelta(hours=offset)
            try:
                prediction = self._predict_core(selected["station_id"], alternative_time, selected["system_id"])
                candidates.append({
                    "timestamp": alternative_time.isoformat(), "hour": int(alternative_time.hour),
                    "predicted_boardings": float(prediction["predicted_boardings"]),
                    "relative_demand_band": prediction["relative_demand_band"],
                    "historical_percentile": prediction["historical_percentile"],
                    "offset_hours": offset,
                })
            except (InsufficientHistory, ForecastHorizonExceeded):
                failures += 1
        basis = (
            "The selected model's estimates for nearby hours at this same station (within ±3 hours, selected hour excluded). "
            "A lower predicted boardings count is not a capacity or occupancy guarantee."
        )
        if not candidates:
            return {"status": "insufficient_data", "message": "Insufficient contiguous history for nearby station-hour model estimates.", "basis": basis, "candidates": []}
        best = min(candidates, key=lambda entry: (entry["predicted_boardings"], abs(entry["offset_hours"])))
        if best["predicted_boardings"] >= selected["predicted_boardings"]:
            return {"status": "no_lower_demand_window", "message": "No lower-demand nearby hour was found by the model.", "basis": basis,
                    "candidates": sorted(candidates, key=lambda entry: abs(entry["offset_hours"]))}
        selected_count = float(selected["predicted_boardings"])
        reduction = (selected_count - best["predicted_boardings"]) / selected_count * 100 if selected_count > 0 else None
        return {
            "status": "available", "message": "Lowest predicted nearby demand window.", "basis": basis,
            "recommended": best, "selected_predicted_boardings": selected_count,
            "reduction_percent": float(reduction) if reduction is not None else None,
            "candidates": sorted(candidates, key=lambda entry: abs(entry["offset_hours"])),
            "skipped_candidates_insufficient_history": failures,
        }

    def history(self, system_id: str, station_id: str, hours: int = 168, end: str | None = None) -> dict[str, Any]:
        selected_system = self._require_ready(system_id)
        station_id = self._require_entity(station_id, selected_system)
        frame = self.hourly.loc[
            self.hourly["system_id"].astype(str).eq(selected_system)
            & self.hourly["entity_id"].astype(str).eq(station_id)
        ].copy()
        end_time = pd.Timestamp(end) if end else frame["timestamp"].max()
        end_time = end_time.tz_localize(self.timezone) if end_time.tzinfo is None else end_time.tz_convert(self.timezone)
        frame = frame.loc[(frame["timestamp"] <= end_time) & (frame["timestamp"] > end_time - pd.Timedelta(hours=max(1, int(hours))))]
        frame = frame.sort_values("timestamp")
        return {
            "system_id": selected_system, "station_id": station_id,
            "points": [{"timestamp": pd.Timestamp(row.timestamp).isoformat(), "observed_boardings": float(row.demand_count), "observation_type": "observed"}
                       for row in frame.itertuples()],
            "measure": "hourly_station_boardings",
            "source": "published BMRCL historical observations; missing station-hours are omitted and not interpolated",
        }

    def heatmap(self, system_id: str, station_id: str) -> dict[str, Any]:
        selected_system = self._require_ready(system_id)
        station_id = self._require_entity(station_id, selected_system)
        frame = self.hourly.loc[
            self.hourly["system_id"].astype(str).eq(selected_system)
            & self.hourly["entity_id"].astype(str).eq(station_id)
        ].copy()
        frame["day_of_week"] = frame["timestamp"].dt.dayofweek
        frame["hour"] = frame["timestamp"].dt.hour
        grouped = frame.groupby(["day_of_week", "hour"])["demand_count"].agg(["mean", "count"])
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        cells = []
        for day in range(7):
            for hour in range(24):
                record = grouped.loc[(day, hour)] if (day, hour) in grouped.index else None
                cells.append({
                    "day_of_week": day, "day_name": names[day], "hour": hour,
                    "mean_observed_boardings": float(record["mean"]) if record is not None else None,
                    "observations": int(record["count"]) if record is not None else 0,
                })
        return {"system_id": selected_system, "station_id": station_id, "cells": cells,
                "measure": "hourly_station_boardings", "source": "mean of observed station-hour values; empty cells remain unavailable"}

    def station_analytics(self) -> dict[str, Any]:
        self._require_ready()
        if self.station_analytics_data is None:
            file = self.artifact_path.parent / "station_analytics.json"
            try:
                self.station_analytics_data = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.station_analytics_data = self.bundle.get("model_report", {}).get("station_analytics")
        if not self.station_analytics_data:
            raise ServiceUnavailable("PCA/DBSCAN station analytics artifact is unavailable.")
        return self.station_analytics_data

    def model_performance(self) -> dict[str, Any]:
        self._require_ready()
        return self.bundle.get("model_report", {})

    def station_comparison(self, system_id: str, target_date: str, target_hour: int,
                           selected_station_id: str | None = None) -> dict[str, Any]:
        selected_system = self._require_ready(system_id)
        target = self._target_timestamp(target_date, target_hour)
        items = []
        for station_id in self.entity_ids:
            try:
                result = self._predict_core(station_id, target, selected_system)
                items.append({
                    "station_id": station_id,
                    "station_name": result["station_name"],
                    "predicted_boardings": result["predicted_boardings"],
                    "relative_demand_band": result["relative_demand_band"],
                    "historical_percentile": result["historical_percentile"],
                    "is_selected": station_id == (selected_station_id or ""),
                })
            except (InsufficientHistory, ForecastHorizonExceeded):
                continue
        items.sort(key=lambda item: (
            item["historical_percentile"] if item["historical_percentile"] is not None else 101,
            item["station_name"],
        ))
        return {
            "system_id": selected_system,
            "target_timestamp": target.isoformat(),
            "comparison_basis": "Each estimate is ranked against that station's training-only historical distribution; values do not represent physical occupancy or a comparable safety rating.",
            "stations": items,
            "stations_without_estimate": len(self.entity_ids) - len(items),
        }
