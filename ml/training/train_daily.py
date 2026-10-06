"""Chronological training for day-granularity observed-demand model families.

This module is the daily counterpart of :mod:`ml.training.train`. It exists as a
separate family rather than a flag because the horizon semantics differ: a daily
model predicts an observed count for a calendar day, so the model registry, the
feature schema, the risk thresholds and the reported horizon must not silently
reuse the hourly contract.

Selection discipline is identical to the hourly family: the champion is chosen on
the chronological validation window only, the latest window is reported once, and
no future observation is ever used to build a past feature.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import f1_score, mean_absolute_error, mean_squared_error
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import LinearSVC, LinearSVR
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

from ml.evaluation.metrics import classification_metrics, regression_metrics
from ml.training.horizon import horizon_bands
from ml.training.registry import get_model_family
from ml.features.daily import FEATURE_COLUMNS, HISTORY_FEATURES, TARGET, TIME_FEATURES, build_supervised_frame
from ml.training.risk import RISK_ORDER, classify_demand, fit_risk_thresholds, historical_percentile

MODEL_VERSION = "2.1.0-india-daily"
BUNDLE_FORMAT = "transitcrowd-model-v2"
MAX_JOBS = min(max(os.cpu_count() or 1, 1), 4)
REGRESSION_KEYS = ["seasonal_naive", "linear_regression", "decision_tree", "random_forest", "svr", "xgboost"]
CLASSIFICATION_KEYS = ["baseline", "logistic_regression", "decision_tree", "random_forest", "svm", "xgboost"]
SPLIT_RATIOS = (0.70, 0.15, 0.15)
#: Hard technical ceiling for a recursive projection, and how far the trainer is allowed to look
#: for the point where a projection stops beating the mean (bounded by the validation partition).
#: Below MIN_SERVICEABLE_HORIZON_DAYS the product would refuse a week ahead, which no archive of
#: this size can support, so the floor is documented as a product decision rather than a measurement.
MAX_RECURSIVE_HORIZON_DAYS = 60
HORIZON_SCAN_DAYS = 45
MIN_SERVICEABLE_HORIZON_DAYS = 7


class SeasonalNaiveDaily:
    """Same weekday last week, falling back to the previous day."""

    def fit(self, X, y=None):
        return self

    def predict(self, X):
        weekly = pd.to_numeric(X["lag_7"], errors="coerce").to_numpy(float)
        previous = pd.to_numeric(X["lag_1"], errors="coerce").to_numpy(float)
        return np.where(np.isfinite(weekly), weekly, previous)

    def get_params(self, deep=True):
        return {}

    def set_params(self, **params):
        return self


def _preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ("entity_id", OneHotEncoder(handle_unknown="ignore", sparse_output=False), ["entity_id"]),
            ("numeric", StandardScaler(), [column for column in FEATURE_COLUMNS if column != "entity_id"]),
        ],
        remainder="drop", verbose_feature_names_out=True,
    )


def make_regression_model(name: str):
    if name == "seasonal_naive":
        return _seasonal_naive_pipeline()
    from xgboost import XGBRegressor

    estimators = {
        "linear_regression": LinearRegression(),
        "decision_tree": DecisionTreeRegressor(max_depth=10, min_samples_leaf=15, random_state=42),
        "random_forest": RandomForestRegressor(
            n_estimators=250, max_depth=16, min_samples_leaf=4, max_features=0.7,
            n_jobs=MAX_JOBS, random_state=42,
        ),
        "svr": LinearSVR(C=0.5, epsilon=0.05, max_iter=6000, random_state=42, dual="auto"),
        "xgboost": XGBRegressor(
            n_estimators=400, max_depth=5, learning_rate=0.04, min_child_weight=10, subsample=0.85,
            colsample_bytree=0.8, reg_lambda=6.0, objective="reg:squarederror", eval_metric="rmse",
            tree_method="hist", n_jobs=MAX_JOBS, random_state=42,
        ),
    }
    if name not in estimators:
        raise KeyError(name)
    from sklearn.pipeline import Pipeline

    return Pipeline([("preprocess", _preprocessor()), ("model", estimators[name])])


def _seasonal_naive_pipeline():
    from sklearn.pipeline import Pipeline
    from sklearn.base import TransformerMixin

    class Passthrough(TransformerMixin):
        def fit(self, X, y=None):
            return self

        def transform(self, X):
            return X

    from sklearn.base import BaseEstimator, RegressorMixin

    class Naive(BaseEstimator, RegressorMixin):
        def fit(self, X, y=None):
            return self

        def predict(self, X):
            return SeasonalNaiveDaily().predict(X)

    return Pipeline([("passthrough", Passthrough()), ("model", Naive())])


def make_classification_model(name: str):
    from sklearn.pipeline import Pipeline

    if name == "baseline":
        return Pipeline([("passthrough", _Passthrough()), ("model", DummyClassifier(strategy="most_frequent"))])
    estimators = {
        "logistic_regression": LogisticRegression(max_iter=2000, class_weight="balanced", solver="lbfgs"),
        "decision_tree": DecisionTreeClassifier(max_depth=10, min_samples_leaf=15, class_weight="balanced", random_state=42),
        "random_forest": RandomForestClassifier(
            n_estimators=250, max_depth=16, min_samples_leaf=4, max_features=0.7,
            class_weight="balanced_subsample", n_jobs=MAX_JOBS, random_state=42,
        ),
        "svm": LinearSVC(C=0.5, class_weight="balanced", max_iter=8000, random_state=42),
        "xgboost": _xgb_classifier(),
    }
    if name not in estimators:
        raise KeyError(name)
    return Pipeline([("preprocess", _preprocessor()), ("model", estimators[name])])


class _Passthrough:
    def fit(self, X, y=None):
        return self

    def transform(self, X):
        return X

    def get_params(self, deep=True):
        return {}

    def set_params(self, **params):
        return self

    def fit_transform(self, X, y=None):
        return X


def _xgb_classifier():
    from xgboost import XGBClassifier

    return XGBClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.04, min_child_weight=10, subsample=0.85,
        colsample_bytree=0.8, reg_lambda=6.0, objective="multi:softprob", num_class=len(RISK_ORDER),
        eval_metric="mlogloss", tree_method="hist", n_jobs=MAX_JOBS, random_state=42,
    )


def _risk_labels(frame: pd.DataFrame, thresholds: dict[str, Any]) -> np.ndarray:
    systems = frame["system_id"].astype(str) if "system_id" in frame.columns else pd.Series("", index=frame.index)
    return np.asarray([
        classify_demand(float(value), str(entity_id), str(system_id), thresholds)[0]
        for entity_id, system_id, value in zip(frame["entity_id"], systems, frame[TARGET])
    ], dtype=str)


def _encode(name: str, labels: np.ndarray) -> np.ndarray:
    if name == "xgboost":
        mapping = {label: index for index, label in enumerate(RISK_ORDER)}
        return np.asarray([mapping[label] for label in labels], dtype=int)
    return labels


def _decode(name: str, prediction: np.ndarray) -> np.ndarray:
    if name == "xgboost":
        return np.asarray([RISK_ORDER[int(value)] for value in np.asarray(prediction).reshape(-1)], dtype=str)
    return np.asarray(prediction, dtype=str)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def daily_entity_behaviour(daily: pd.DataFrame) -> pd.DataFrame:
    """Training-window station behaviour at day granularity (no clock-hour fields)."""
    rows = []
    for entity_id, group in daily.groupby("entity_id", sort=True):
        values = pd.to_numeric(group["demand_count"], errors="coerce")
        timestamps = pd.to_datetime(group["timestamp"])
        mean = float(values.mean())
        weekend = values[timestamps.dt.dayofweek >= 5]
        weekday = values[timestamps.dt.dayofweek < 5]
        ordered = values.sort_index()
        autocorr = float(pd.Series(ordered).autocorr(lag=7)) if len(ordered) > 10 else 0.0
        rows.append({
            "entity_id": str(entity_id),
            "entity_name": str(group["entity_name"].iloc[0]) if "entity_name" in group.columns else str(entity_id),
            "mean_daily_demand": mean,
            "median_daily_demand": float(values.median()),
            "weekday_mean": float(weekday.mean()) if len(weekday) else 0.0,
            "weekend_mean": float(weekend.mean()) if len(weekend) else 0.0,
            "weekend_to_weekday_ratio": float(weekend.mean() / weekday.mean()) if len(weekend) and len(weekday) and weekday.mean() else 0.0,
            "q95_daily_demand": float(values.quantile(0.95)),
            "coefficient_of_variation": float(values.std(ddof=0) / mean) if mean else 0.0,
            "lag7_autocorrelation": autocorr,
            "observed_days": int(len(group)),
        })
    return pd.DataFrame(rows)


def fit_daily_profiles(daily: pd.DataFrame, min_samples: int = 4) -> dict[str, Any]:
    """PCA + DBSCAN over daily behaviour features, fitted on the training window only."""
    from sklearn.cluster import DBSCAN
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    features = daily_entity_behaviour(daily)
    if len(features) < 3:
        raise ValueError("PCA/DBSCAN requires at least three observed entities.")
    columns = [column for column in features.columns if column.endswith(("demand", "mean", "ratio", "autocorrelation"))]
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features[columns].replace([np.inf, -np.inf], np.nan).fillna(0.0))
    pca = PCA(n_components=2, random_state=42)
    coordinates = pca.fit_transform(scaled)
    labels = DBSCAN(eps=1.1, min_samples=min_samples, metric="euclidean").fit_predict(coordinates)
    entities = [{
        "entity_id": str(row["entity_id"]), "entity_name": str(row["entity_name"]),
        "pc1": float(coordinates[i, 0]), "pc2": float(coordinates[i, 1]),
        "cluster_id": int(labels[i]), "is_outlier": bool(labels[i] == -1),
        "behaviour": {column: float(row[column]) for column in columns},
    } for i, row in features.reset_index(drop=True).iterrows()]
    cluster_ids = sorted({int(value) for value in labels if int(value) != -1})
    return {
        "method": "StandardScaler → PCA (2 components) → DBSCAN over day-granularity behaviour features",
        "entity_count": int(len(features)), "features_used": columns,
        "pca": {"components": 2, "explained_variance_ratio": [float(v) for v in pca.explained_variance_ratio_],
                "total_explained_variance_ratio": float(pca.explained_variance_ratio_.sum())},
        "dbscan": {"eps": 1.1, "min_samples": int(min_samples), "metric": "euclidean",
                   "cluster_count_excluding_noise": int(len(cluster_ids)),
                   "outlier_count": int(np.sum(labels == -1)),
                   "clusters": [{"cluster_id": int(c), "entity_count": int(np.sum(labels == c))} for c in cluster_ids]},
        "entities": entities,
        "interpretation_note": "Cluster IDs are algorithm outputs from the training window, not operator-defined station types.",
    }


def _fit_regression(name: str, X: pd.DataFrame, y: pd.Series):
    model = make_regression_model(name)
    model.fit(X, y)
    return model


def _fit_classifier(name: str, X: pd.DataFrame, labels: np.ndarray):
    model = make_classification_model(name)
    encoded = _encode(name, labels)
    if name == "xgboost":
        from sklearn.utils.class_weight import compute_sample_weight

        model.fit(X, encoded, model__sample_weight=compute_sample_weight("balanced", encoded))
    else:
        model.fit(X, encoded)
    return model


def _predict_classifier(name: str, model, X: pd.DataFrame) -> np.ndarray:
    return _decode(name, model.predict(X))


def _probabilities(name: str, model, X: pd.DataFrame) -> np.ndarray | None:
    if not hasattr(model, "predict_proba"):
        return None
    try:
        raw = np.asarray(model.predict_proba(X), dtype=float)
        final = model.named_steps["model"]
        classes = np.asarray(getattr(final, "classes_", []))
        aligned = np.zeros((len(X), len(RISK_ORDER)), dtype=float)
        for index, raw_class in enumerate(classes):
            label = RISK_ORDER[int(raw_class)] if name == "xgboost" else str(raw_class)
            if label in RISK_ORDER and index < raw.shape[1]:
                aligned[:, RISK_ORDER.index(label)] = raw[:, index]
        sums = aligned.sum(axis=1)
        valid = sums > 0
        aligned[valid] = aligned[valid] / sums[valid, None]
        return aligned if valid.all() else None
    except (ValueError, IndexError, TypeError):
        return None


def train_daily(daily: pd.DataFrame, dataset_metadata: dict[str, Any] | None = None,
                tz: str = "Asia/Kolkata", split_ratios=SPLIT_RATIOS) -> dict[str, Any]:
    """Chronological benchmark suite for one day-granularity model family."""
    metadata = dict(dataset_metadata or {})
    system_id = str(daily["system_id"].iloc[0])
    # Refusing an unregistered family here is deliberate: a model must be attached to a
    # verified system/mode/operator family before it can be served.
    family = get_model_family(system_id)
    supervised = build_supervised_frame(daily, timezone=tz)
    unique_days = np.array(sorted(supervised["timestamp"].unique()))
    if len(unique_days) < 12:
        raise ValueError("A chronological train/validation/test split needs at least 12 target days.")
    first_cut = int(np.floor(len(unique_days) * split_ratios[0]))
    second_cut = int(np.floor(len(unique_days) * (split_ratios[0] + split_ratios[1])))
    train_days, validation_days, test_days = unique_days[:first_cut], unique_days[first_cut:second_cut], unique_days[second_cut:]
    train = supervised.loc[supervised["timestamp"].isin(train_days)].copy()
    validation = supervised.loc[supervised["timestamp"].isin(validation_days)].copy()
    test = supervised.loc[supervised["timestamp"].isin(test_days)].copy()
    if not len(train) or not len(validation) or not len(test):
        raise ValueError("Chronological split produced an empty partition.")
    train_cut, validation_cut = pd.Timestamp(train_days[-1]), pd.Timestamp(validation_days[-1])

    thresholds = fit_risk_thresholds(train, target_column=TARGET)
    X_train, y_train = train[FEATURE_COLUMNS], train[TARGET]
    X_valid, y_valid = validation[FEATURE_COLUMNS], validation[TARGET]
    X_test, y_test = test[FEATURE_COLUMNS], test[TARGET]

    regression_scores: dict[str, dict[str, Any]] = {}
    fitted: dict[str, Any] = {}
    for name in REGRESSION_KEYS:
        started = datetime.now(timezone.utc)
        model = _fit_regression(name, X_train, y_train)
        seconds = (datetime.now(timezone.utc) - started).total_seconds()
        prediction = np.maximum(np.asarray(model.predict(X_valid), dtype=float), 0.0)
        regression_scores[name] = {"validation": regression_metrics(y_valid, prediction), "fit_seconds": round(seconds, 3)}
        fitted[name] = model
    regression_ranked = sorted(
        REGRESSION_KEYS,
        key=lambda name: (round(regression_scores[name]["validation"]["mae"], 6),
                          round(regression_scores[name]["validation"]["rmse"], 6), name),
    )
    champion_regression = regression_ranked[0]

    labels_train = _risk_labels(train, thresholds)
    labels_valid = _risk_labels(validation, thresholds)
    labels_test = _risk_labels(test, thresholds)
    classification_scores: dict[str, dict[str, Any]] = {}
    classification_models: dict[str, Any] = {}
    for name in CLASSIFICATION_KEYS:
        started = datetime.now(timezone.utc)
        model = _fit_classifier(name, X_train, labels_train)
        seconds = (datetime.now(timezone.utc) - started).total_seconds()
        predicted = _predict_classifier(name, model, X_valid)
        probabilities = _probabilities(name, model, X_valid)
        classification_scores[name] = {
            "validation": classification_metrics(labels_valid, predicted, probabilities),
            "fit_seconds": round(seconds, 3),
        }
        classification_models[name] = model
    classification_ranked = sorted(
        CLASSIFICATION_KEYS,
        key=lambda name: (-round(classification_scores[name]["validation"]["f1_macro"], 6),
                          -round(classification_scores[name]["validation"]["high_recall"], 6), name),
    )
    champion_classification = classification_ranked[0]

    regression_test = {
        name: regression_metrics(y_test, np.maximum(np.asarray(fitted[name].predict(X_test), dtype=float), 0.0))
        for name in REGRESSION_KEYS
    }
    classification_test = {
        name: classification_metrics(labels_test, _predict_classifier(name, classification_models[name], X_test))
        for name in CLASSIFICATION_KEYS
    }

    importance: list[dict[str, Any]] = []
    if champion_regression != "seasonal_naive":
        try:
            result = permutation_importance(fitted[champion_regression], X_valid, y_valid, n_repeats=8,
                                            random_state=42, scoring="neg_mean_absolute_error", n_jobs=1)
            importance = sorted(
                ({"feature": column, "mae_increase": float(value)}
                 for column, value in zip(FEATURE_COLUMNS, result.importances_mean)),
                key=lambda item: -item["mae_increase"],
            )
        except (ValueError, TypeError):
            importance = []

    daily_only = daily.loc[pd.to_datetime(daily["timestamp"]) <= train_cut].copy()
    profiles = fit_daily_profiles(daily_only) if len(daily_only) else {"method": "not fitted", "entities": []}
    entity_ids = sorted(daily["entity_id"].astype(str).unique().tolist())
    entity_names = {
        str(entity_id): str(name)
        for entity_id, name in daily[["entity_id", "entity_name"]].drop_duplicates().itertuples(index=False, name=None)
    }
    distributions = {
        "__global__": np.sort(train[TARGET].to_numpy(dtype=float)).tolist(),
        **{f"entity:{entity}": np.sort(part[TARGET].to_numpy(dtype=float)).tolist()
           for entity, part in train.groupby("entity_id")},
    }
    if "system_id" in train.columns:
        for system, part in train.groupby("system_id"):
            distributions[f"system:{system}"] = np.sort(part[TARGET].to_numpy(dtype=float)).tolist()
    medians = {column: float(pd.to_numeric(train[column], errors="coerce").median())
               for column in FEATURE_COLUMNS if column != "entity_id"}
    created_at = datetime.now(timezone.utc).isoformat()

    report = {
        "project": "INDIA TRANSIT CROWD AI",
        "tagline": "PREDICT THE CROWD. PLAN THE JOURNEY.",
        "model_version": MODEL_VERSION,
        "training_timestamp_utc": created_at,
        "model_family": {"system_id": system_id, "granularity": "day", "target": TARGET},
        "dataset": {
            **metadata,
            "observed_entity_day_rows": int(len(daily)),
            "supervised_rows": int(len(supervised)),
            "entity_count": int(len(entity_ids)),
            "timestamp_min": pd.Timestamp(daily["timestamp"].min()).isoformat(),
            "timestamp_max": pd.Timestamp(daily["timestamp"].max()).isoformat(),
            "target_measure": "daily_station_entries",
            "target_semantics": "observed station entries on target day T, predicted only from observations strictly before T",
        },
        "feature_schema": {
            "feature_count": len(FEATURE_COLUMNS), "features": FEATURE_COLUMNS,
            "time_features": TIME_FEATURES, "historical_features": HISTORY_FEATURES, "target": TARGET,
            "minimum_contiguous_history_days": 28,
        },
        "split": {
            "strategy": "Chronological split over unique target days: earliest 70% train, next 15% validation, latest 15% test; every station on the same day stays in the same partition.",
            "train": {"rows": int(len(train)), "start": str(train["timestamp"].min()), "end": str(train["timestamp"].max()), "unique_days": int(train["timestamp"].nunique())},
            "validation": {"rows": int(len(validation)), "start": str(validation["timestamp"].min()), "end": str(validation["timestamp"].max()), "unique_days": int(validation["timestamp"].nunique())},
            "test": {"rows": int(len(test)), "start": str(test["timestamp"].min()), "end": str(test["timestamp"].max()), "unique_days": int(test["timestamp"].nunique())},
            "train_cutoff": train_cut.isoformat(), "validation_cutoff": validation_cut.isoformat(),
            "leakage_controls": [
                "Lags and rolling windows for target day T use observations up to and including T-1 only.",
                "Entities or target days lacking 28 contiguous prior observation days are dropped, never bridged or zero-filled.",
                "Risk thresholds are fitted on the chronological training targets only and frozen for validation, test and inference.",
                "Validation selects the champion; the final test window is reported once and never used for selection.",
                "Behaviour profiles/PCA/DBSCAN use observations through the training cutoff only.",
            ],
        },
        "regression": {
            "selection_metric": "validation MAE; tie-break on validation RMSE, then model key",
            "uses_test_metrics": False,
            "champion_key": champion_regression,
            "champion_name": champion_regression.replace("_", " ").title(),
            "ranking_by_validation": regression_ranked,
            "models": [{"key": key, "name": key.replace("_", " ").title(),
                        "validation": regression_scores[key]["validation"], "test": regression_test[key],
                        "fit_seconds": regression_scores[key]["fit_seconds"], "validation_rank": regression_ranked.index(key) + 1}
                       for key in REGRESSION_KEYS],
        },
        "classification": {
            "selection_metric": "validation macro F1; tie-break on HIGH recall, then model key",
            "uses_test_metrics": False,
            "champion_key": champion_classification,
            "champion_name": champion_classification.replace("_", " ").title(),
            "ranking_by_validation": classification_ranked,
            "models": [{"key": key, "name": key.replace("_", " ").title(),
                        "validation": classification_scores[key]["validation"], "test": classification_test[key],
                        "fit_seconds": classification_scores[key]["fit_seconds"], "validation_rank": classification_ranked.index(key) + 1}
                       for key in CLASSIFICATION_KEYS],
        },
        "demand_risk": thresholds,
        "explainability": {
            "global_method": "Permutation importance on chronological validation observations (increase in MAE); associational, not causal.",
            "global_feature_importance": importance,
            "uncertainty": "No calibrated prediction interval or confidence percentage is produced.",
        },
        "station_analytics": profiles,
        "artifacts": {"bundle": "transitcrowd.joblib", "report": "model_report.json", "station_analytics": "station_analytics.json"},
        "limitations": [
            "Target is CMRL station entries per day; it is not onboard load, occupancy, capacity utilisation or a safety level.",
            "The archive begins at the collector's first capture date, so annual seasonality and festival/holiday effects outside the window are unmodelled.",
            "No weather, disruption, fare-change, event or service-frequency variable is joined to the model.",
            "Trees cannot extrapolate beyond the observed feature range; forecasts far beyond the data frontier regress toward recent levels.",
            "Forecasts past the last observation are one-day-ahead model calls applied recursively and are labelled as model forecasts, never as live counts.",
            "CMRL data are copyrighted by the operator; this project documents the download path and does not redistribute the raw archive.",
        ],
    }
    # --- horizon governance (validation stage only) -------------------------------------
    # The champion is re-run recursively across the validation partition, exactly as the API
    # runs it, to measure how error grows per horizon day. That measurement decides both the
    # serviceable horizon and the empirical bands the API returns.
    def _champion_predict(features: pd.DataFrame) -> float:
        return float(np.asarray(fitted[champion_regression].predict(features[FEATURE_COLUMNS]), dtype=float)[0])

    horizon_start = pd.Timestamp(train_cut) + pd.Timedelta(days=1)
    horizon_end = pd.Timestamp(validation_cut)
    try:
        bands = horizon_bands(
            daily,
            history=daily.loc[pd.to_datetime(daily["timestamp"]).lt(horizon_start)],
            predict_fn=_champion_predict, start=horizon_start, end=horizon_end, timezone=tz,
            entities=list(entity_ids), max_horizon=HORIZON_SCAN_DAYS)
    except ValueError as exc:
        bands = {"error": str(exc), "usable_horizon_days": 0, "max_measured_horizon_days": 0, "per_horizon": {}}
    measured = int(bands.get("max_measured_horizon_days") or 0)
    usable = int(bands.get("usable_horizon_days") or 0)
    # A horizon shorter than the measured window is a data-driven refusal: the projection stopped
    # beating the average. An artefact whose error never exceeds the reference dispersion inside
    # the measured window keeps the documented technical ceiling, because nothing was measured
    # that would justify cutting it earlier.
    horizon_limit = (min(MAX_RECURSIVE_HORIZON_DAYS, max(MIN_SERVICEABLE_HORIZON_DAYS, usable))
                     if 0 < usable < measured else int(MAX_RECURSIVE_HORIZON_DAYS))
    serviceable = min(MAX_RECURSIVE_HORIZON_DAYS, max(usable, MIN_SERVICEABLE_HORIZON_DAYS)) if usable else MAX_RECURSIVE_HORIZON_DAYS
    bands["policy"] = {
        "max_recursive_horizon_days": int(MAX_RECURSIVE_HORIZON_DAYS),
        "measured_horizon_days": measured,
        "usable_horizon_days": usable,
        "horizon_limit_days": int(horizon_limit),
        "serviceable_horizon_days": int(serviceable),
        "limit_basis": ("validation error exceeded the reference dispersion at this horizon" if horizon_limit < MAX_RECURSIVE_HORIZON_DAYS
                        else "no horizon inside the measured window lost to the mean-predictor baseline"),
        "beyond_measured_range": ("the widest measured band is reused and the answer is labelled "
                                  "beyond_validated_range" if MAX_RECURSIVE_HORIZON_DAYS > measured else "not applicable"),
    }

    report["forecast_horizon"] = {
        "policy": bands.get("policy"), "method": bands.get("method"),
        "evaluation_window": bands.get("evaluation_window"), "evaluated_pairs": bands.get("evaluated_pairs"),
        "entities": bands.get("entities"), "entities_unprojectable": bands.get("entities_unprojectable"),
        "reference_dispersion": bands.get("reference_dispersion"),
        "usable_horizon_days": bands.get("usable_horizon_days"),
        "max_measured_horizon_days": bands.get("max_measured_horizon_days"),
        "error_by_horizon_days": bands.get("per_horizon"),
        "note": bands.get("note"),
    }

    bundle = {
        "bundle_format": BUNDLE_FORMAT,
        "model_version": MODEL_VERSION, "system_id": system_id, "granularity": "day",
        "target": TARGET, "created_at_utc": created_at,
        "regression_model": fitted[champion_regression], "regression_model_key": champion_regression,
        "classification_model": classification_models[champion_classification],
        "classification_model_key": champion_classification,
        "classification_label_encoding": champion_classification == "xgboost",
        "feature_columns": FEATURE_COLUMNS,
        "numeric_features": [column for column in FEATURE_COLUMNS if column != "entity_id"],
        "entity_ids": entity_ids, "entity_names": entity_names,
        "risk_thresholds": thresholds, "training_distributions": distributions, "training_medians": medians,
        "training_cutoff": train_cut.isoformat(), "validation_cutoff": validation_cut.isoformat(),
        "test_end": pd.Timestamp(test_days[-1]).isoformat(),
        "data_end": pd.Timestamp(daily["timestamp"].max()).isoformat(),
        "min_history_days": 28, "max_recursive_horizon_days": int(horizon_limit),
        "validated_horizon_days": int(measured), "serviceable_horizon_days": int(serviceable),
        "horizon_error_bands": bands,
        "timezone": tz, "model_family": family, "global_feature_importance": importance,
        "dataset_metadata": metadata, "model_report": report,
        "supervised_rows": int(len(supervised)),
    }
    return {"report": report, "bundle": bundle, "supervised": supervised,
            "train_cutoff": train_cut, "test_end": pd.Timestamp(test_days[-1]),
            "data_end": pd.Timestamp(daily["timestamp"].max())}


def save_artifacts(result: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(result["bundle"], output_dir / "transitcrowd.joblib", compress=3)
    (output_dir / "model_report.json").write_text(
        json.dumps(_jsonable(result["report"]), indent=2, allow_nan=False), encoding="utf-8")
    (output_dir / "station_analytics.json").write_text(
        json.dumps(_jsonable(result["report"]["station_analytics"]), indent=2, allow_nan=False), encoding="utf-8")
    return output_dir
