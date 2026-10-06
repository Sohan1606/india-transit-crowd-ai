"""Inference for day-granularity observed-demand model families.

This service exists separately from :class:`~backend.app.inference.service.TransitInferenceService`
because the two families differ in a way that must not be paper over: the Bengaluru
family predicts the next *hour* of station boardings from hourly observations, while
this family predicts the next *day* of station entries from daily observations.

Consequences that are enforced here:

* A target day at or before the source's last published day is answered by a replay
  built only from strictly earlier observations and is reported as ``historical_replay``
  — never as a future forecast.
* A target day after that frontier is answered by recursive projection, one day at a
  time, and is reported as ``post_frontier_projection`` with ``is_model_forecast=True``.
* There is no hour-level output for this family: hour-of-day heatmaps are refused rather
  than silently down-sampled, because a daily total contains no information about the
  distribution of passengers within the day.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from ml.data_pipeline.cleaning import clean_normalized_demand
from ml.features.daily import FEATURE_COLUMNS, TARGET
from ml.features.daily import features_for_target
from ml.training.forecast import project_future
from ml.training.registry import get_model_family
from ml.training.risk import RISK_ORDER, classify_demand, historical_percentile, resolve_thresholds

from backend.app.inference.service import (
    ForecastHorizonExceeded, InferenceError, InsufficientHistory, ServiceUnavailable,
    UnknownEntity, UnknownSystem,
)

FEATURE_LABELS = {
    "day_of_week": "Target day of week (Monday=0)",
    "day_of_month": "Target day of month",
    "month": "Target month",
    "week_of_year": "Target week of year",
    "is_weekend": "Weekend indicator",
    "is_month_start": "Month-start indicator",
    "lag_1": "Observed entries 1 day earlier",
    "lag_7": "Observed entries 1 week earlier",
    "lag_14": "Observed entries 2 weeks earlier",
    "lag_28": "Observed entries 4 weeks earlier",
    "rolling_mean_7": "Mean of the previous 7 observed days",
    "rolling_std_7": "Variability of the previous 7 observed days",
    "rolling_mean_28": "Mean of the previous 28 observed days",
    "rolling_std_28": "Variability of the previous 28 observed days",
    "same_weekday_mean_4wk": "Mean of the same weekday over the last 4 weeks",
    "trend_ratio_7_28": "Short-term level divided by 4-week level",
    "entity_id": "Station-line identity",
}


class GranularityMismatch(InferenceError):
    """The request asks for a resolution the loaded family's data cannot answer."""


class DailyDemandInferenceService:
    """Artifact-backed next-day forecasting for one registered day-granularity family."""

    def __init__(self, artifact_path: Path, data_path: Path, source_metadata_path: Path | None = None):
        self.artifact_path, self.data_path = artifact_path, data_path
        self.source_metadata_path = source_metadata_path
        self.source_metadata: dict[str, Any] = {}
        self.bundle: dict[str, Any] | None = None
        self.daily: pd.DataFrame | None = None
        self.unavailable_detail: str | None = None
        self._sidecar_cache: dict[str, Any] = {}
        self.timezone = "Asia/Kolkata"
        try:
            if artifact_path.is_file():
                loaded = joblib.load(artifact_path)
                if not isinstance(loaded, dict) or not {
                    "regression_model", "classification_model", "risk_thresholds", "system_id",
                }.issubset(loaded):
                    raise ValueError("Artifact does not contain a complete model bundle.")
                if loaded.get("granularity") != "day":
                    raise ValueError("Artifact is not a day-granularity model family; use the hourly service.")
                self.bundle = loaded
                self.timezone = str(get_model_family(str(loaded["system_id"]))["timezone"])
            else:
                self.unavailable_detail = f"Model artifact not found: {artifact_path.name}"
        except Exception as exc:  # noqa: BLE001 - any load failure must degrade the endpoint, not crash the app
            self.unavailable_detail = f"Model artifact could not be loaded ({type(exc).__name__})."
            self.bundle = None
        try:
            if data_path.is_file():
                normalized, _ = clean_normalized_demand(pd.read_csv(data_path), timezone=self.timezone)
                self.daily = normalized
            elif self.unavailable_detail is None:
                self.unavailable_detail = f"Normalized observed-demand data not found: {data_path.name}"
        except Exception as exc:  # noqa: BLE001
            self.daily = None
            self.unavailable_detail = f"Normalized observed-demand data could not be loaded ({type(exc).__name__})."
        if source_metadata_path and source_metadata_path.is_file():
            try:
                self.source_metadata = json.loads(source_metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.source_metadata = {}
        if self.bundle and self.daily is not None:
            system = str(self.bundle["system_id"])
            present = set(self.daily.loc[self.daily["system_id"].astype(str).eq(system), "entity_id"].astype(str))
            trained = set(map(str, self.bundle.get("entity_ids", [])))
            if set(self.daily["system_id"].astype(str).unique()) != {system} or not trained or not trained.issubset(present):
                self.unavailable_detail = ("Model-family system/entity IDs do not match the normalized observed-demand "
                                           "dataset. Re-run scripts/prepare_chennai_data.py and retrain.")
                self.bundle, self.daily = None, None
            elif self.source_metadata.get("normalized_sha256"):
                actual = hashlib.sha256(data_path.read_bytes()).hexdigest()
                if actual != self.source_metadata["normalized_sha256"]:
                    self.unavailable_detail = ("Normalized dataset checksum does not match the source metadata sidecar. "
                                               "Re-run data preparation and model validation.")
                    self.bundle, self.daily = None, None

    # ------------------------------------------------------------------ state
    @property
    def system_id(self) -> str | None:
        return str(self.bundle["system_id"]) if self.bundle else None

    @property
    def model_ready(self) -> bool:
        return self.bundle is not None

    @property
    def data_ready(self) -> bool:
        return self.daily is not None and not self.daily.empty

    @property
    def ready(self) -> bool:
        return self.model_ready and self.data_ready

    @property
    def family(self) -> dict[str, Any]:
        return dict(self.bundle.get("model_family", {})) if self.bundle else {}

    @property
    def entity_ids(self) -> list[str]:
        if not self.ready:
            return []
        system = self.daily.loc[self.daily["system_id"].astype(str).eq(self.system_id), "entity_id"].astype(str)
        return sorted(set(system) & set(map(str, self.bundle.get("entity_ids", []))))

    @property
    def stations(self) -> list[str]:  # parity with the hourly service's vocabulary
        return self.entity_ids

    @property
    def data_frontier(self) -> pd.Timestamp:
        return pd.Timestamp(self.daily["timestamp"].max()).normalize()

    @property
    def next_unobserved_day(self) -> pd.Timestamp:
        return self.data_frontier + pd.Timedelta(days=1)

    def _require_ready(self, system_id: str | None = None) -> str:
        if not self.ready:
            raise ServiceUnavailable(self.unavailable_detail or "Verified day-granularity artifacts or data are unavailable.")
        requested = str(system_id or self.system_id)
        if requested != self.system_id:
            raise UnknownSystem(
                f"Prediction is unavailable for '{requested}'. The loaded day-granularity model family is '{self.system_id}'."
            )
        return requested

    def _require_entity(self, station_id: str, system_id: str | None = None) -> str:
        self._require_ready(system_id)
        normalized = str(station_id).strip()
        if normalized not in self.entity_ids:
            raise UnknownEntity(f"Unknown or untrained station-line entity '{normalized}'. Use GET /api/stations?system_id=...")
        return normalized

    def _station_frame(self, system_id: str, entity_id: str) -> pd.DataFrame:
        frame = self.daily.loc[
            self.daily["system_id"].astype(str).eq(system_id) & self.daily["entity_id"].astype(str).eq(entity_id)
        ].copy()
        return frame.sort_values("timestamp")

    def _sidecar(self, name: str) -> dict[str, Any]:
        """Read a report file next to the artifact; failures are not cached.

        A retrain can add ``evaluation_replay.json`` or ``future_forecast.json`` while the
        process is running, and an auditor asking for the newest evidence must not be
        served a cached "missing" from before that run.
        """
        if name not in self._sidecar_cache:
            path = self.artifact_path.parent / name
            try:
                self._sidecar_cache[name] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
        return self._sidecar_cache[name]

    # ------------------------------------------------------------------ core forecast
    def _forecast(self, entity_id: str, target: pd.Timestamp, system_id: str) -> dict[str, Any]:
        frame = self._station_frame(system_id, entity_id)
        frontier = pd.Timestamp(frame["timestamp"].max()).normalize()
        # The normalized series carries a fixed +05:30 offset while a caller-supplied date
        # localizes to the named zone; pandas refuses to build a range across the two names,
        # so the target is re-expressed in the data's own timezone (wall clock preserved).
        data_tz = str(frontier.tzinfo)
        raw_target = pd.Timestamp(target)
        naive_target = raw_target.tz_localize(None) if raw_target.tzinfo is not None else raw_target
        target = pd.Timestamp(naive_target).tz_localize(data_tz).normalize()
        horizon = int((target - frontier).days)
        maximum = int(self.bundle.get("max_recursive_horizon_days", 60))
        if horizon > maximum:
            raise ForecastHorizonExceeded(
                f"Target is {horizon} days beyond the last observed day for {entity_id}; the recursive limit is {maximum} days."
            )
        minimum_history = int(self.bundle.get("min_history_days", 28))
        if horizon >= 1:
            if horizon == 1:
                try:
                    features = features_for_target(frame, entity_id, target, timezone=data_tz,
                                           min_history_days=minimum_history)
                except ValueError as exc:
                    raise InsufficientHistory(str(exc)) from exc
                demand = self._regress(features)
            else:
                projected = project_future(frame, entity_id, self._regress, frontier + pd.Timedelta(days=1), target,
                                          timezone=data_tz, min_history_days=minimum_history)
                row = projected.iloc[-1]
                if row.get("forecast_demand") is None or pd.isna(row.get("forecast_demand")):
                    raise InsufficientHistory(str(row.get("forecast_error") or "Projection failed."))
                demand = float(row["forecast_demand"])
                features = row.get("_features")
                if isinstance(features, pd.DataFrame):
                    features = features.copy()
                    features["timestamp"] = target
                else:
                    features = None
            kind = "post_frontier_projection"
            note = (
                f"MODEL FORECAST. Day {target.date()} has not been observed by the source; {horizon} day(s) past the "
                f"data frontier. Values beyond the frontier are produced by re-feeding the model its own one-day-ahead "
                "forecasts, so error can compound with horizon. This is not a live count, not occupancy and not a safety rating."
            )
        else:
            try:
                features = features_for_target(frame, entity_id, target, timezone=data_tz,
                                               min_history_days=minimum_history)
            except ValueError as exc:
                raise InsufficientHistory(str(exc)) from exc
            demand = self._regress(features)
            observed = bool(frame["timestamp"].dt.normalize().eq(target).any())
            kind = "historical_replay" if observed else "unobserved_day_estimate"
            note = (
                "HISTORICAL REPLAY, not a future forecast: the target day is already observed by the source, and this "
                "answer uses only observations strictly before it. The stored observation for the target day is never a feature."
                if observed else
                "Estimate for a day with no published observation inside the historical window, using only earlier days."
            )
        band = self._horizon_assessment(demand, horizon)
        scoring = self._score_against_observation(frame, entity_id, target, demand, kind)
        return {
            "system_id": system_id, "station_id": entity_id,
            "station_name": str(frame["entity_name"].iloc[0]) if len(frame) else entity_id,
            "target_timestamp": target.isoformat(),
            "target_date": target.strftime("%Y-%m-%d"),
            # One-step forecasts come from the day before the target; a recursive forecast is
            # seeded at the data frontier, and reporting a fake origin there would hide how far
            # the projection actually reaches.
            "origin_timestamp": (frontier if horizon > 1 else target - pd.Timedelta(days=1)).isoformat(),
            "origin_basis": "data_frontier_recursive_seed" if horizon > 1 else "previous_observed_period",
            "data_frontier": frontier.isoformat(),
            "predicted_entries": float(demand),
            "measure": str(self.family.get("measure") or self.bundle.get("model_family", {}).get("measure")
                           or "daily_station_entries"),
            "unit": (str(self.family.get("label_unit")) if self.family.get("label_unit")
                     else "passengers entering the station on that calendar day (ticket-count derived)"),
            "relative_demand_band": None,  # filled by caller after risk resolution
            "forecast_horizon_days": max(horizon, 0),
            "target_relative_to_data_frontier": ("after" if horizon > 0 else "on" if horizon == 0 else "before"),
            "forecast_kind": kind,
            "is_model_forecast": horizon >= 1,
            "is_recursive_forecast": horizon > 1,
            "forecast_note": note,
            "regression_model": self.bundle.get("regression_model_key", "unknown"),
            "classification_model": self.bundle.get("classification_model_key", "unknown"),
            "training_cutoff": pd.Timestamp(self.bundle["training_cutoff"]).normalize().isoformat(),
            **band, **scoring,
            "_features": features,
            "_demand": float(demand),
        }

    def _horizon_assessment(self, demand: float, horizon: int) -> dict[str, Any]:
        """Measured accuracy for this horizon, plus an empirical interval when one can be justified.

        The bands come from the trainer's recursive evaluation on the validation partition
        (``ml/training/horizon.py``). A model trained before those bands existed returns the
        documented "no measured band" shape instead of inventing one.
        """
        bands = self.bundle.get("horizon_error_bands") or {}
        per_horizon = bands.get("per_horizon") or {}
        policy = bands.get("policy") or {}
        measured = int(policy.get("measured_horizon_days") or bands.get("max_measured_horizon_days") or 0)
        if not per_horizon or horizon < 1:
            return {
                "horizon_status": ("unmeasured" if horizon >= 1 else "not_applicable_historical"),
                "horizon_validation": {
                    "status": "not_available_for_this_artifact",
                    "detail": ("This artifact was trained before horizon bands were measured; the response carries no "
                               "accuracy claim for the horizon. Retrain to obtain them."),
                },
                "forecast_interval": None,
            }
        # Beyond the measured window the *widest* measured band is reused - reported as such, never
        # extrapolated into a tighter claim than the evidence supports.
        horizon_limit = int(policy.get("horizon_limit_days") or policy.get("serviceable_horizon_days") or measured)
        if horizon > measured:
            # Nothing was measured past the validation window, so the widest band that *was*
            # measured is applied: conservative, and labelled as such in the response.
            worst_key = max(per_horizon, key=lambda key: float((per_horizon[key] or {}).get("p90_absolute_error") or 0.0))
            evidence_day, basis, row = int(worst_key), "worst_measured_horizon", per_horizon[worst_key]
        else:
            evidence_day, basis = max(1, min(int(horizon), measured)), "measured_at_horizon"
            row = per_horizon.get(str(evidence_day)) or {}
        p90 = row.get("p90_absolute_error")
        interval = None
        if p90 is not None and np.isfinite(float(p90)):
            interval = {
                "lower": float(max(0.0, demand - float(p90))),
                "upper": float(demand + float(p90)),
                "level": "p90_of_absolute_error",
                "method": ("empirical absolute-error quantile at the measured horizon, from a recursive projection over "
                           "the validation partition"),
                "horizon_days_used": int(evidence_day),
                "band_basis": basis,
                "calibrated": False,
                "is_confidence_interval": False,
            }
        return {
            "horizon_status": ("within_validated_range" if horizon <= measured else "beyond_validated_range"),
            "horizon_validation": {
                "status": "measured_on_validation_partition",
                "measured_horizon_days": measured,
                "usable_horizon_days": int(policy.get("usable_horizon_days") or 0),
                "serviceable_horizon_days": int(policy.get("serviceable_horizon_days") or measured),
                "max_recursive_horizon_days": int(policy.get("max_recursive_horizon_days") or measured),
                "evidence_horizon_days": int(evidence_day),
                "band_basis": basis,
                "horizon_limit_days": horizon_limit,
                "mae_at_horizon": row.get("mae"),
                "p90_absolute_error_at_horizon": p90,
                "p95_absolute_error_at_horizon": row.get("p95_absolute_error"),
                "samples_at_horizon": row.get("samples"),
                "reference_dispersion": (bands.get("reference_dispersion") or {}).get("rule"),
                "beyond_measured_range_note": (bands.get("policy") or {}).get("beyond_measured_range"),
            },
            "forecast_interval": interval,
        }

    def _score_against_observation(self, frame: pd.DataFrame, entity_id: str, target: pd.Timestamp,
                                   demand: float, kind: str) -> dict[str, Any]:
        """Compare the answer with the stored observation whenever one exists - including for a
        forecast made after the fact, which is how a model earns (or loses) trust."""
        aligned = frame.loc[pd.to_datetime(frame["timestamp"]).dt.normalize().eq(target)]
        if aligned.empty:
            return {"actual_observed_demand": None, "observation_status": "OBSERVED VALUE UNAVAILABLE",
                    "evaluation_status": ("not_scored_future_period" if kind == "post_frontier_projection"
                                          else "not_scorable_no_observation_for_target"),
                    "absolute_error": None, "signed_error": None, "absolute_percentage_error": None,
                    "error_note": ("The source published no observation for this entity-day, so there is nothing to "
                                   "compare against. No actual value has been estimated, interpolated or substituted.")}
        observed = float(pd.to_numeric(aligned["demand_count"], errors="coerce").iloc[-1])
        absolute_error = abs(demand - observed)
        percentage = (absolute_error / observed * 100.0) if observed else None
        return {
            "actual_observed_demand": observed,
            "observation_status": "OBSERVED",
            "observation_rows": int(len(aligned)),
            "evaluation_status": "scored_against_observation",
            "absolute_error": float(absolute_error),
            "signed_error": float(demand - observed),
            "absolute_percentage_error": float(percentage) if percentage is not None and np.isfinite(percentage) else None,
            "error_note": ("Actual value is the observation stored by the source for this entity-day; it was not a model "
                           "input (leakage guards in ml/features/daily.py exclude the target period). "
                           + ("This is a hindsight replay, so it is not out-of-sample accuracy."
                              if kind == "historical_replay" else "This is a genuine forward forecast scored after the day was published.")),
        }

    def _regress(self, X: pd.DataFrame) -> float:
        raw = float(np.asarray(self.bundle["regression_model"].predict(X[FEATURE_COLUMNS])).reshape(-1)[0])
        return max(0.0, raw)

    def _classify_with_model(self, X: pd.DataFrame) -> str:
        model = self.bundle["classification_model"]
        key = self.bundle.get("classification_model_key", "")
        value = np.asarray(model.predict(X[FEATURE_COLUMNS])).reshape(-1)[0]
        return RISK_ORDER[int(value)] if key == "xgboost" else str(value)

    def _explain(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        features = result.get("_features")
        if features is None:
            return []
        model = self.bundle["regression_model"]
        base = float(result["_demand"])
        rows = []
        # Feature frames mix integer calendar columns with the station identifier; the
        # counterfactual writes floats, so the working copy is cast once up front.
        numeric_only = [column for column in FEATURE_COLUMNS if column != "entity_id"]
        for column in self.bundle.get("numeric_features", []):
            reference = self.bundle.get("training_medians", {}).get(column)
            if reference is None or not np.isfinite(float(reference)):
                continue
            changed = features[FEATURE_COLUMNS].copy()
            for numeric_column in numeric_only:
                changed[numeric_column] = changed[numeric_column].astype(float)
            actual = float(changed.iloc[0][column])
            changed.loc[changed.index[0], column] = float(reference)
            counterfactual = max(0.0, float(np.asarray(model.predict(changed)).reshape(-1)[0]))
            delta = base - counterfactual
            rows.append({
                "feature": column, "label": FEATURE_LABELS.get(column, column.replace("_", " ").title()),
                "actual_value": actual, "reference_value": float(reference),
                "prediction_with_reference": counterfactual, "delta_entries": float(delta),
                "absolute_delta": float(abs(delta)),
                "direction": ("raises the model output versus its training-median reference" if delta > 0
                              else "lowers the model output versus its training-median reference" if delta < 0 else "no change"),
            })
        rows.sort(key=lambda item: item["absolute_delta"], reverse=True)
        return rows[:6]

    def _recommend(self, result: dict[str, Any], system_id: str) -> dict[str, Any]:
        """Compare neighbouring days for the same station; day granularity cannot rank hours."""
        target = pd.Timestamp(result["target_timestamp"])
        frontier = pd.Timestamp(result["data_frontier"])
        candidates, failures = [], 0
        for offset in (-3, -2, -1, 1, 2, 3):
            alternative = target + pd.Timedelta(days=offset)
            if alternative.normalize() < frontier + pd.Timedelta(days=1):
                continue  # never recommend from a day whose answer would be a replay
            try:
                other = self._forecast(result["station_id"], alternative.normalize(), system_id)
            except (InsufficientHistory, ForecastHorizonExceeded, ValueError):
                failures += 1
                continue
            candidates.append({
                "date": other["target_date"], "day_name": alternative.strftime("%A"),
                "predicted_entries": round(other["_demand"], 2),
                "relative_demand_band": classify_demand(other["_demand"], result["station_id"], system_id,
                                                         self.bundle["risk_thresholds"])[0],
                "delta_vs_selected": round(other["_demand"] - result["_demand"], 2),
                "forecast_horizon_days": other["forecast_horizon_days"],
            })
        if not candidates:
            return {"summary": ("No alternative day could be projected next to this target (it sits at the edge of the "
                                f"recursive horizon of {int(self.bundle.get('max_recursive_horizon_days', 60))} days)."),
                    "alternative_days": [], "failed_alternatives": failures,
                    "advice_kind": "day_level_forecast_comparison",
                    "caveat": "Day granularity gives no time-of-day guidance; it cannot say which hour is quieter."}
        quietest = min(candidates, key=lambda item: item["predicted_entries"])
        busiest = max(candidates, key=lambda item: item["predicted_entries"])
        saving = result["_demand"] - quietest["predicted_entries"]
        summary = (
            f"For {result['station_name']}, the quietest projected day in this window is {quietest['date']} "
            f"({quietest['day_name']}) at {quietest['predicted_entries']:,.0f} entries, {saving:,.0f} below the selected "
            f"day; the busiest is {busiest['date']} ({busiest['day_name']}) at {busiest['predicted_entries']:,.0f}."
        )
        return {
            "summary": summary, "alternative_days": candidates, "failed_alternatives": failures,
            "advice_kind": "day_level_forecast_comparison",
            "caveat": ("Every value here is a model forecast for an unobserved day, ranked against that station's own "
                       "training distribution. It is not a queue, occupancy or safety statement, and day totals cannot "
                       "identify a quieter hour."),
        }

    # ------------------------------------------------------------------ public endpoints
    def predict(self, system_id: str, station_id: str, target_date: str, target_hour: int | None = None) -> dict[str, Any]:
        if target_hour is not None and int(target_hour) not in (0, 24):
            raise GranularityMismatch(
                f"{self.system_id} is a day-granularity model family; target_hour={target_hour} cannot be answered. "
                "Omit target_hour, or use an hour-granularity system such as bengaluru-namma-metro."
            )
        selected = self._require_ready(system_id)
        entity_id = self._require_entity(station_id, selected)
        try:
            target = pd.Timestamp(str(target_date)).tz_localize(self.timezone).normalize()
        except (TypeError, ValueError) as exc:
            raise InsufficientHistory("Invalid target date; use an ISO calendar date such as 2026-10-12.") from exc
        result = self._forecast(entity_id, target, selected)
        demand = result.pop("_demand")
        features = result.pop("_features")
        risk, source = classify_demand(demand, entity_id, selected, self.bundle["risk_thresholds"])
        threshold, _ = resolve_thresholds(entity_id, selected, self.bundle["risk_thresholds"])
        percentile = historical_percentile(demand, entity_id, selected, self.bundle.get("training_distributions", {}))
        classifier_risk = self._classify_with_model(features) if features is not None else "unavailable"
        result.update({
            "predicted_demand": float(demand),
            "relative_demand_band": risk, "risk": risk, "risk_method": source,
            "risk_thresholds": {key: float(threshold[key]) for key in ("q50", "q80", "q95")},
            "threshold_sample_count": int(threshold.get("sample_count", 0)),
            "historical_percentile": percentile if np.isfinite(percentile) else None,
            "classification_check": classifier_risk,
            "classification_agrees": classifier_risk == risk,
            "target_column": TARGET,
            "model_version": self.bundle.get("model_version"),
            "generated_at_utc": datetime.now(dt_timezone.utc).isoformat(),
            "data_freshness_days": int((pd.Timestamp.now(tz=self.timezone).normalize()
                                        - pd.Timestamp(result["data_frontier"])).days),
            "explanation": self._explain({"_features": features, "_demand": demand, **result}),
            "explanation_method": (
                "One-feature counterfactual against the training-partition median using the persisted model; descriptive, "
                "not causal. For a multi-day projection the history columns are themselves partly projected values, so the "
                "delta describes the model's input path rather than an observed condition."
            ),
            "recommendation": self._recommend({**result, "_demand": demand}, selected),
            "evaluation_context": {
                "source": "held-out test partition (latest 15% of days) plus recursive-projection audit",
                "detail": "GET /api/model-performance?system_id=... for the full benchmark table.",
            },
        })
        return result

    def history(self, system_id: str, station_id: str, days: int = 60, end: str | None = None) -> dict[str, Any]:
        selected = self._require_ready(system_id)
        entity_id = self._require_entity(station_id, selected)
        frame = self._station_frame(selected, entity_id)
        end_time = pd.Timestamp(end) if end else frame["timestamp"].max()
        end_time = end_time.tz_localize(self.timezone) if end_time.tzinfo is None else end_time.tz_convert(self.timezone)
        window = frame.loc[(frame["timestamp"] <= end_time)
                           & (frame["timestamp"] > end_time - pd.Timedelta(days=max(1, int(days))))]
        return {
            "system_id": selected, "station_id": entity_id,
            "points": [{"timestamp": pd.Timestamp(row.timestamp).isoformat(), "observed_boardings": float(row.demand_count),
                        "observation_type": "observed"} for row in window.itertuples()],
            "measure": "daily_station_entries",
            "source": ("CMRL passenger-flow observations collected daily by the pinned upstream archive; missing days are "
                       "omitted, never interpolated or filled with zeros"),
        }

    def heatmap(self, system_id: str, station_id: str) -> dict[str, Any]:
        self._require_ready(system_id)
        raise GranularityMismatch(
            f"{self.system_id} publishes daily totals only, so an hour-of-day heatmap would be invented rather than measured. "
            "Use bengaluru-namma-metro for hourly patterns, or /api/history for the daily series."
        )

    def weekly_pattern(self, system_id: str, station_id: str) -> dict[str, Any]:
        """Day-of-week profile of observed daily entries — the honest analogue of a heatmap."""
        selected = self._require_ready(system_id)
        entity_id = self._require_entity(station_id, selected)
        frame = self._station_frame(selected, entity_id)
        frame["day_of_week"] = pd.to_datetime(frame["timestamp"]).dt.dayofweek
        grouped = frame.groupby("day_of_week")["demand_count"].agg(["mean", "median", "count", "std"])
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        cells = [{"day_of_week": day, "day_name": names[day],
                  "mean_observed_daily_entries": float(grouped.loc[day, "mean"]) if day in grouped.index else None,
                  "median_observed_daily_entries": float(grouped.loc[day, "median"]) if day in grouped.index else None,
                  "observations": int(grouped.loc[day, "count"]) if day in grouped.index else 0} for day in range(7)]
        return {"system_id": selected, "station_id": entity_id, "cells": cells,
                "measure": "daily_station_entries",
                "source": "mean/median of observed daily values per weekday; unobserved weekdays stay null",
                "note": "Descriptive statistics of past observations only. This is not a forecast and not hour-level detail."}

    def station_summaries(self, system_id: str | None = None) -> list[dict[str, Any]]:
        selected = self._require_ready(system_id)
        frame = self.daily.loc[self.daily["system_id"].astype(str).eq(selected)
                               & self.daily["entity_id"].astype(str).isin(self.entity_ids)]
        grouped = frame.groupby(["entity_id", "entity_name"], sort=True).agg(
            mean_daily_entries=("demand_count", "mean"),
            latest_observation=("timestamp", "max"),
            observed_days=("demand_count", "count"),
        ).reset_index()
        return [{"station_id": str(row.entity_id), "station_name": str(row.entity_name),
                 "mean_hourly_boardings": float(row.mean_daily_entries),  # schema-compatible field name
                 "mean_daily_entries": float(row.mean_daily_entries),
                 "latest_observation": pd.Timestamp(row.latest_observation).isoformat(),
                 "observed_hours": int(row.observed_days), "observed_days": int(row.observed_days),
                 "system_id": selected} for row in grouped.itertuples()]

    def station_comparison(self, system_id: str, target_date: str, target_hour: int | None = None,
                           selected_station_id: str | None = None) -> dict[str, Any]:
        selected = self._require_ready(system_id)
        target = pd.Timestamp(str(target_date)).tz_localize(self.timezone).normalize()
        items = []
        for entity_id in self.entity_ids:
            try:
                result = self._forecast(entity_id, target, selected)
            except (InsufficientHistory, ForecastHorizonExceeded, ValueError):
                continue
            demand = result.pop("_demand")
            result.pop("_features", None)
            items.append({
                "station_id": entity_id, "station_name": result["station_name"],
                "predicted_boardings": float(demand), "predicted_daily_entries": float(demand),
                "relative_demand_band": classify_demand(demand, entity_id, selected, self.bundle["risk_thresholds"])[0],
                "historical_percentile": historical_percentile(demand, entity_id, selected,
                                                                self.bundle.get("training_distributions", {})),
                "is_selected": entity_id == (selected_station_id or ""),
            })
        for item in items:
            if item["historical_percentile"] is not None and not np.isfinite(item["historical_percentile"]):
                item["historical_percentile"] = None
        items.sort(key=lambda item: (item["historical_percentile"] if item["historical_percentile"] is not None else 101,
                                     item["station_name"]))
        return {"system_id": selected, "target_timestamp": target.isoformat(),
                "forecast_horizon_days": int((target - self.data_frontier).days),
                "is_model_forecast": bool(target > self.data_frontier),
                "comparison_basis": ("Every station is projected with the same champion model for the same target day and "
                                     "ranked against its own training distribution. Predicted daily entries are ticket-count "
                                     "derived and do not represent physical occupancy or a comparable safety rating."),
                "stations": items, "stations_without_estimate": len(self.entity_ids) - len(items)}

    def health(self) -> dict[str, Any]:
        ready = self.ready
        return {"status": "ok" if ready else "degraded", "model_ready": self.model_ready, "data_ready": self.data_ready,
                "system_id": self.system_id, "granularity": "day" if ready else None,
                "model_version": self.bundle.get("model_version") if self.bundle else None,
                "data_frontier": self.data_frontier.strftime("%Y-%m-%d") if ready else None,
                "next_unobserved_date": self.next_unobserved_day.strftime("%Y-%m-%d") if ready else None,
                "detail": None if ready else self.unavailable_detail}

    def metadata(self) -> dict[str, Any]:
        selected = self._require_ready()
        frame = self.daily.loc[self.daily["system_id"].astype(str).eq(selected)
                               & self.daily["entity_id"].astype(str).isin(self.entity_ids)]
        first, latest = pd.Timestamp(frame["timestamp"].min()), pd.Timestamp(frame["timestamp"].max())
        source = self.source_metadata or self.bundle.get("dataset_metadata", {})
        report = self.bundle.get("model_report", {})
        champion = next((item for item in report.get("regression", {}).get("models", [])
                         if item.get("key") == self.bundle.get("regression_model_key")), {})
        return {
            "forecast_horizon_policy": {
                "granularity": self.bundle.get("granularity", "day"),
                "max_recursive_horizon_days": int(self.bundle.get("max_recursive_horizon_days", 60)),
                "validated_horizon_days": int(self.bundle.get("validated_horizon_days")
                                              or (self.bundle.get("horizon_error_bands") or {}).get("max_measured_horizon_days")
                                              or 0),
                "method": ((self.bundle.get("horizon_error_bands") or {}).get("method")
                           or "not measured for this artifact"),
                "interval_method": ((self.bundle.get("horizon_error_bands") or {}).get("note")
                                     or "no measured interval method"),
                "note": ("Every answer beyond the data frontier is produced by re-feeding the model its own forecasts; "
                         "the per-horizon error below is what was actually measured on held-out validation days."),
            },
            "project": "INDIA TRANSIT CROWD AI", "tagline": "PREDICT THE CROWD. PLAN THE JOURNEY.",
            "system_id": selected, "city": self.family.get("city", "Chennai"), "mode": self.family.get("mode", "METRO"),
            "operator": self.family.get("operator", "CMRL"),
            "model_scope": ("Verified observed-demand prediction for Chennai Metro (CMRL) station-day entries. Day "
                            "granularity only: this family cannot answer hour-of-day questions."),
            "granularity": "day", "timezone": self.timezone,
            "dataset": {
                "title": source.get("source_title", "CMRL passenger-flow station daily observations"),
                "source_url": source.get("source_url"), "source_commit": source.get("upstream_commit"),
                "source_sha256": source.get("source_sha256"), "license": source.get("license"),
                "license_url": source.get("license_url"), "attribution": source.get("attribution"),
                "redistribution": source.get("redistribution", "not bundled; fetched on demand and checksum-verified"),
                "granularity": "one observed calendar day per station-line",
                "measure": "passengers entering the station that day (ticket-count derived), not entries+exits and not occupancy",
                "measure_semantics_check": source.get("measure_semantics_check"),
                "timestamp_min": first.isoformat(), "timestamp_max": latest.isoformat(),
                "unique_days": int(pd.to_datetime(frame["timestamp"]).dt.normalize().nunique()),
                "observed_rows": int(len(frame)), "station_count": len(self.entity_ids),
                "station_ids": self.entity_ids, "station_names": self.bundle.get("entity_names", {}),
                "explicit_zero_observations": int(frame["demand_count"].eq(0).sum()),
                "missing_observations_filled": 0,
                "source_periods": source.get("source_periods", []), "source_metadata": source, "is_live": False,
            },
            "features": {"count": len(FEATURE_COLUMNS), "columns": FEATURE_COLUMNS},
            "primary_target": TARGET,
            "risk_definition": ("Historical-relative daily-entry bands fitted on training-partition targets per station-line "
                                "entity; not capacity, occupancy or safety thresholds."),
            "default_station_id": self.entity_ids[0],
            "default_target_date": self.next_unobserved_day.strftime("%Y-%m-%d"),
            "default_target_timestamp": self.next_unobserved_day.isoformat(),
            "genuine_future_prediction_available": True,
            "data_freshness_days": int((pd.Timestamp.now(tz=self.timezone).normalize() - latest.normalize()).days),
            "prediction_max_recursive_horizon_days": int(self.bundle.get("max_recursive_horizon_days", 60)),
            "training_cutoff": pd.Timestamp(self.bundle["training_cutoff"]).normalize().strftime("%Y-%m-%d"),
            "regression_champion": self.bundle.get("regression_model_key"),
            "classification_champion": self.bundle.get("classification_model_key"),
            "regression_champion_test": {key: float(value) for key, value in (champion.get("test") or {}).items()
                                         if key in ("mae", "rmse", "r2") and value is not None},
            "seasonal_naive_test_mae": next((float(item["test"]["mae"]) for item in
                                             report.get("regression", {}).get("models", [])
                                             if item.get("key") == "seasonal_naive" and item.get("test")), None),
        }

    def model_performance(self) -> dict[str, Any]:
        self._require_ready()
        report = dict(self.bundle.get("model_report", {}))
        report["future_forecast_validation"] = self._sidecar("evaluation_replay.json")
        report["future_forecast_validation_note"] = (
            "The recursive projection block is the number to quote for future-date forecasting: it re-feeds the model its "
            "own forecasts and never uses held-out observations as inputs. One-step replay is the optimistic bound."
        )
        report["historical_replay_separation"] = (
            "Predictions for dates at or before the data frontier are historical replays of observed days and are labelled "
            "as such; only post-frontier dates are genuine future forecasts."
        )
        return report

    def station_analytics(self) -> dict[str, Any]:
        self._require_ready()
        data = self._sidecar("station_analytics.json") or self.bundle.get("model_report", {}).get("station_analytics")
        if not data:
            raise ServiceUnavailable("Station analytics artifact is unavailable for this family.")
        return data

    def forecast_snapshot(self) -> dict[str, Any]:
        """The last generated post-frontier snapshot, for auditors and offline review."""
        self._require_ready()
        snapshot = self._sidecar("future_forecast.json")
        if not snapshot:
            raise ServiceUnavailable("No future forecast snapshot has been generated for this family yet.")
        return snapshot

    def future_preview(self, system_id: str, days: int = 7) -> dict[str, Any]:
        """Project every trained station-line entity for the next unobserved days.

        One recursive projection per entity is reused for all requested days, so the
        result is a coherent multi-day path rather than independent one-day guesses.
        """
        selected = self._require_ready(system_id)
        horizon = max(1, min(int(days), int(self.bundle.get("max_recursive_horizon_days", 60))))
        start = self.next_unobserved_day
        end = start + pd.Timedelta(days=horizon - 1)
        minimum_history = int(self.bundle.get("min_history_days", 28))
        rows: list[pd.DataFrame] = []
        for entity_id in self.entity_ids:
            frame = self._station_frame(selected, entity_id)
            rows.append(project_future(frame, entity_id, self._regress, start, end,
                                       timezone=str(self.data_frontier.tzinfo), min_history_days=minimum_history))
        projected = pd.concat([row for row in rows if not row.empty], ignore_index=True)
        scored = projected.dropna(subset=["forecast_demand"])
        by_day = []
        for day, part in scored.groupby(pd.to_datetime(scored["timestamp"]).dt.normalize()):
            peaks = part.loc[part["forecast_demand"].idxmax()]
            band = classify_demand(float(peaks["forecast_demand"]), str(peaks["entity_id"]), selected,
                                  self.bundle["risk_thresholds"])[0]
            by_day.append({
                "date": day.strftime("%Y-%m-%d"), "day_name": day.strftime("%A"),
                "forecast_horizon_days": int((day - self.data_frontier).days),
                "system_total_predicted_entries": float(part["forecast_demand"].sum()),
                "stations_projected": int(len(part)),
                "busiest_station": {"station_id": str(peaks["entity_id"]),
                                    "station_name": self.bundle.get("entity_names", {}).get(str(peaks["entity_id"])),
                                    "predicted_entries": float(peaks["forecast_demand"]), "risk_band": band},
                "weekend_indicator": int(int(day.dayofweek) >= 5),
            })
        recent = self.daily.loc[self.daily["system_id"].astype(str).eq(selected)]
        recent_total = recent.groupby(pd.to_datetime(recent["timestamp"]).dt.normalize())["demand_count"].sum()
        baseline_mean = float(recent_total.tail(28).mean()) if len(recent_total) else None
        return {
            "kind": "MODEL_FORECAST_NOT_LIVE_COUNT",
            "statement": (
                "Every value below is a machine-learned forecast for a calendar day that the source has not observed yet. "
                "It is not a live count, not occupancy, and not a safety rating. Days are projected recursively: each step "
                "consumes the model's own previous forecast, so accuracy degrades with horizon."
            ),
            "system_id": selected, "data_frontier": self.data_frontier.strftime("%Y-%m-%d"),
            "training_cutoff": pd.Timestamp(self.bundle["training_cutoff"]).normalize().strftime("%Y-%m-%d"),
            "days_requested": horizon, "days_projected": len(by_day),
            "recent_observed_daily_total_mean_28d": baseline_mean,
            "model": self.bundle.get("regression_model_key"), "model_version": self.bundle.get("model_version"),
            "days": by_day,
            "expected_accuracy": self._sidecar("evaluation_replay.json").get("recursive_projection_over_same_window", {}),
            "generated_at_utc": datetime.now(dt_timezone.utc).isoformat(),
        }

    def source_gap_report(self) -> dict[str, Any]:
        """How far the archive lags today — the honest answer to 'is this live?'."""
        self._require_ready()
        today = pd.Timestamp.now(tz=self.timezone).normalize()
        lag = int((today - self.data_frontier).days)
        return {"system_id": self.system_id, "data_frontier": self.data_frontier.strftime("%Y-%m-%d"),
                "today_local": today.strftime("%Y-%m-%d"), "days_behind_today": lag,
                "live_feed": False,
                "next_unobserved_date": self.next_unobserved_day.strftime("%Y-%m-%d"),
                "interpretation": ("Observations end at the frontier; every forecast beyond it is a model forecast. "
                                   "The upstream archive is refreshed by its own collector, not by this API.")}
