"""Chronological, mode/operator-scoped benchmarks and persisted model artifacts."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import f1_score, mean_absolute_error, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import LinearSVC, LinearSVR
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

from ml.clustering.entity_behaviour import fit_pca_dbscan
from ml.data_pipeline.cleaning import clean_normalized_demand
from ml.evaluation.metrics import classification_metrics, regression_metrics
from ml.features.forecasting import FEATURE_COLUMNS, HISTORY_FEATURES, TARGET, TIME_FEATURES, build_supervised_frame
from ml.training.registry import get_model_family
from ml.training.risk import RISK_ORDER, classify_demand, fit_risk_thresholds
from ml.data_pipeline.source import BMRCL_TIMEZONE

MODEL_VERSION = "2.0.0-india"
MAX_JOBS = min(max(os.cpu_count() or 1, 1), 4)
REGRESSION_KEYS = ["seasonal_naive", "linear_regression", "decision_tree", "random_forest", "svr", "xgboost"]
CLASSIFICATION_KEYS = ["baseline", "logistic_regression", "decision_tree", "random_forest", "svm", "xgboost"]


class SeasonalNaiveRegressor(RegressorMixin, BaseEstimator):
    """Observed same-hour-yesterday benchmark, with prior-hour fallback."""
    def fit(self, X, y=None):
        return self

    def predict(self, X):
        daily = pd.to_numeric(X["lag_24"], errors="coerce").to_numpy(float)
        previous = pd.to_numeric(X["lag_1"], errors="coerce").to_numpy(float)
        return np.where(np.isfinite(daily), daily, previous)


def _preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ("entity_id", OneHotEncoder(handle_unknown="ignore", sparse_output=False), ["entity_id"]),
            ("numeric", StandardScaler(), [column for column in FEATURE_COLUMNS if column != "entity_id"]),
        ],
        remainder="drop",
        verbose_feature_names_out=True,
    )


def make_regression_model(name: str):
    if name == "seasonal_naive":
        return SeasonalNaiveRegressor()
    from xgboost import XGBRegressor

    estimators = {
        "linear_regression": LinearRegression(n_jobs=None),
        "decision_tree": DecisionTreeRegressor(max_depth=12, min_samples_leaf=20, random_state=42),
        "random_forest": RandomForestRegressor(
            n_estimators=120, max_depth=18, min_samples_leaf=5, max_features=0.85,
            n_jobs=MAX_JOBS, random_state=42,
        ),
        "svr": LinearSVR(C=0.35, epsilon=0.1, max_iter=4000, random_state=42, dual="auto"),
        "xgboost": XGBRegressor(
            n_estimators=140, max_depth=6, learning_rate=0.05, min_child_weight=8,
            subsample=0.85, colsample_bytree=0.85, reg_lambda=5.0,
            objective="reg:squarederror", eval_metric="rmse", tree_method="hist",
            n_jobs=MAX_JOBS, random_state=42,
        ),
    }
    if name not in estimators:
        raise KeyError(name)
    return Pipeline([("preprocess", _preprocessor()), ("model", estimators[name])])


def make_classification_model(name: str):
    if name == "baseline":
        return DummyClassifier(strategy="most_frequent")
    from xgboost import XGBClassifier

    estimators = {
        "logistic_regression": LogisticRegression(max_iter=1200, class_weight="balanced", solver="lbfgs"),
        "decision_tree": DecisionTreeClassifier(max_depth=12, min_samples_leaf=20, class_weight="balanced", random_state=42),
        "random_forest": RandomForestClassifier(
            n_estimators=120, max_depth=18, min_samples_leaf=5, max_features=0.85,
            class_weight="balanced_subsample", n_jobs=MAX_JOBS, random_state=42,
        ),
        "svm": LinearSVC(C=0.5, class_weight="balanced", max_iter=6000, random_state=42),
        "xgboost": XGBClassifier(
            n_estimators=140, max_depth=6, learning_rate=0.05, min_child_weight=8,
            subsample=0.85, colsample_bytree=0.85, reg_lambda=5.0,
            objective="multi:softprob", num_class=len(RISK_ORDER), eval_metric="mlogloss",
            tree_method="hist", n_jobs=MAX_JOBS, random_state=42,
        ),
    }
    if name not in estimators:
        raise KeyError(name)
    return Pipeline([("preprocess", _preprocessor()), ("model", estimators[name])])


def _risk_labels(frame: pd.DataFrame, thresholds: dict[str, Any]) -> np.ndarray:
    systems = frame["system_id"].astype(str) if "system_id" in frame.columns else pd.Series("", index=frame.index)
    return np.asarray([
        classify_demand(float(value), str(entity_id), str(system_id), thresholds)[0]
        for entity_id, system_id, value in zip(frame["entity_id"], systems, frame[TARGET])
    ], dtype=str)


def _classification_fit_target(name: str, labels: np.ndarray) -> np.ndarray:
    if name == "xgboost":
        mapping = {label: index for index, label in enumerate(RISK_ORDER)}
        return np.asarray([mapping[label] for label in labels], dtype=int)
    return labels


def _decode_class_prediction(name: str, prediction: np.ndarray) -> np.ndarray:
    if name == "xgboost":
        return np.asarray([RISK_ORDER[int(value)] for value in np.asarray(prediction).reshape(-1)], dtype=str)
    return np.asarray(prediction, dtype=str)


def _probabilities(name: str, model, X: pd.DataFrame) -> np.ndarray | None:
    if not hasattr(model, "predict_proba"):
        return None
    try:
        raw = np.asarray(model.predict_proba(X), dtype=float)
        final_estimator = model.named_steps["model"] if isinstance(model, Pipeline) else model
        raw_classes = np.asarray(getattr(final_estimator, "classes_", []))
        aligned = np.zeros((len(X), len(RISK_ORDER)), dtype=float)
        for index, raw_class in enumerate(raw_classes):
            label = RISK_ORDER[int(raw_class)] if name == "xgboost" else str(raw_class)
            if label in RISK_ORDER and index < raw.shape[1]:
                aligned[:, RISK_ORDER.index(label)] = raw[:, index]
        sums = aligned.sum(axis=1)
        valid = sums > 0
        aligned[valid] = aligned[valid] / sums[valid, None]
        return aligned if valid.all() else None
    except (ValueError, IndexError, TypeError):
        return None


def _predict_class(name: str, model, X: pd.DataFrame) -> np.ndarray:
    return _decode_class_prediction(name, model.predict(X))


def _fit_classifier(name: str, model, X: pd.DataFrame, labels: np.ndarray) -> None:
    encoded = _classification_fit_target(name, labels)
    if name == "xgboost":
        from sklearn.utils.class_weight import compute_sample_weight
        model.fit(X, encoded, model__sample_weight=compute_sample_weight("balanced", encoded))
    else:
        model.fit(X, encoded)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
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


def _make_time_splits(frame: pd.DataFrame, n_splits: int = 3):
    timestamps = np.array(sorted(pd.to_datetime(frame["timestamp"]).unique()))
    if len(timestamps) < n_splits + 3:
        return []
    splitter = TimeSeriesSplit(n_splits=n_splits)
    folds = []
    for train_idx, validation_idx in splitter.split(timestamps):
        train_times, validation_times = timestamps[train_idx], timestamps[validation_idx]
        train_part = frame.loc[frame["timestamp"].isin(train_times)]
        validation_part = frame.loc[frame["timestamp"].isin(validation_times)]
        if len(train_part) and len(validation_part):
            folds.append((train_part, validation_part))
    return folds


def _cross_validate(frame_train: pd.DataFrame) -> dict[str, Any]:
    """Three expanding-window folds; fold-specific thresholds use fold-train only."""
    regression_folds, classification_folds = [], []
    for train_part, validation_part in _make_time_splits(frame_train, 3):
        reg = make_regression_model("linear_regression")
        reg.fit(train_part[FEATURE_COLUMNS], train_part[TARGET])
        prediction = reg.predict(validation_part[FEATURE_COLUMNS])
        regression_folds.append({
            "train_rows": int(len(train_part)), "validation_rows": int(len(validation_part)),
            "validation_start": str(validation_part["timestamp"].min()),
            "validation_end": str(validation_part["timestamp"].max()),
            "mae": float(mean_absolute_error(validation_part[TARGET], prediction)),
            "rmse": float(np.sqrt(mean_squared_error(validation_part[TARGET], prediction))),
        })
        thresholds = fit_risk_thresholds(train_part)
        y_train = _risk_labels(train_part, thresholds)
        y_validation = _risk_labels(validation_part, thresholds)
        if len(np.unique(y_train)) > 1:
            clf = make_classification_model("logistic_regression")
            clf.fit(train_part[FEATURE_COLUMNS], y_train)
            prediction = _predict_class("logistic_regression", clf, validation_part[FEATURE_COLUMNS])
            classification_folds.append({
                "train_rows": int(len(train_part)), "validation_rows": int(len(validation_part)),
                "validation_start": str(validation_part["timestamp"].min()),
                "validation_end": str(validation_part["timestamp"].max()),
                "macro_f1": float(f1_score(y_validation, prediction, labels=RISK_ORDER, average="macro", zero_division=0)),
            })
    return {
        "method": "sklearn.model_selection.TimeSeriesSplit on unique sorted target timestamps; expanding training windows; no shuffling.",
        "n_splits": 3,
        "regression_reference_model": "Linear Regression",
        "regression_folds": regression_folds,
        "regression_mean_mae": float(np.mean([item["mae"] for item in regression_folds])) if regression_folds else None,
        "classification_reference_model": "Logistic Regression; risk thresholds are re-fitted on each fold's training rows only.",
        "classification_folds": classification_folds,
        "classification_mean_macro_f1": float(np.mean([item["macro_f1"] for item in classification_folds])) if classification_folds else None,
    }


def _score_regression(estimator, X: pd.DataFrame, y: pd.Series) -> tuple[dict, np.ndarray]:
    prediction = np.maximum(0.0, np.asarray(estimator.predict(X), dtype=float))
    return regression_metrics(y, prediction), prediction


def _score_classification(name: str, estimator, X: pd.DataFrame, y: np.ndarray) -> tuple[dict, np.ndarray]:
    prediction = _predict_class(name, estimator, X)
    return classification_metrics(y, prediction, _probabilities(name, estimator, X)), prediction


def _feature_explanations(champion_estimator, X_validation: pd.DataFrame, y_validation: pd.Series,
                          max_rows: int = 2500) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(X_validation) > max_rows:
        positions = np.linspace(0, len(X_validation) - 1, max_rows, dtype=int)
        X_explain = X_validation.iloc[positions].copy()
        y_explain = y_validation.iloc[positions].copy()
    else:
        X_explain, y_explain = X_validation.copy(), y_validation.copy()
    permutation = permutation_importance(
        champion_estimator, X_explain, y_explain, scoring="neg_mean_absolute_error",
        n_repeats=3, random_state=42, n_jobs=1,
    )
    global_importance = [
        {"feature": feature, "importance": float(max(0.0, mean)), "std": float(std),
         "method": "validation permutation importance (increase in MAE)", "validation_rows": int(len(X_explain))}
        for feature, mean, std in zip(FEATURE_COLUMNS, permutation.importances_mean, permutation.importances_std)
    ]
    global_importance.sort(key=lambda item: item["importance"], reverse=True)
    native: list[dict[str, Any]] = []
    if isinstance(champion_estimator, Pipeline):
        final = champion_estimator.named_steps["model"]
        if hasattr(final, "feature_importances_"):
            names = champion_estimator.named_steps["preprocess"].get_feature_names_out()
            native = [
                {"feature": str(name), "importance": float(value), "method": "native tree impurity/gain importance"}
                for name, value in zip(names, final.feature_importances_)
            ]
            native.sort(key=lambda item: item["importance"], reverse=True)
    return global_importance, native


def _distribution_bundle(train: pd.DataFrame, system_id: str) -> dict[str, list[float]]:
    distributions: dict[str, list[float]] = {}
    for entity_id, group in train.groupby("entity_id", sort=True):
        distributions[f"entity:{entity_id}"] = sorted(group[TARGET].astype(float).tolist())
    system_rows = train.loc[train["system_id"].astype(str).eq(str(system_id)), TARGET]
    distributions[f"system:{system_id}"] = sorted(system_rows.astype(float).tolist())
    distributions["__global__"] = sorted(train[TARGET].astype(float).tolist())
    return distributions


def train_and_save(hourly: pd.DataFrame, output_dir: Path,
                   dataset_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Train one verified city/mode/operator family; never mix systems or split times."""
    if "system_id" in hourly.columns and not hourly.empty:
        family_hint = get_model_family(str(hourly["system_id"].iloc[0]))
        system_timezone = str(family_hint.get("timezone", BMRCL_TIMEZONE))
    else:
        system_timezone = BMRCL_TIMEZONE
    hourly, quality = clean_normalized_demand(hourly, timezone=system_timezone)
    system_id = str(hourly["system_id"].iloc[0])
    family = get_model_family(system_id)
    for column in ("city", "mode", "operator", "entity_type", "measure"):
        if hourly[column].nunique() != 1 or str(hourly[column].iloc[0]) != str(family[column]):
            raise ValueError(f"Normalized {column} does not match the registered model family '{system_id}'.")
    if hourly["entity_id"].nunique() < 3:
        raise ValueError("At least three observed entities are required for supervised models and PCA/DBSCAN.")
    output_dir.mkdir(parents=True, exist_ok=True)
    supervised = build_supervised_frame(hourly, timezone=system_timezone)
    timestamps = np.array(sorted(pd.to_datetime(supervised["timestamp"]).unique()))
    if len(timestamps) < 30:
        raise ValueError("At least 30 unique target hours are required for chronological train/validation/test splits.")
    train_end_idx = int(len(timestamps) * 0.70)
    validation_end_idx = int(len(timestamps) * 0.85)
    if train_end_idx < 1 or validation_end_idx <= train_end_idx or validation_end_idx >= len(timestamps):
        raise ValueError("Unable to form non-empty chronological train, validation and test periods.")
    train_cut = pd.Timestamp(timestamps[train_end_idx - 1])
    validation_cut = pd.Timestamp(timestamps[validation_end_idx - 1])
    train = supervised.loc[supervised["timestamp"] <= train_cut].copy().reset_index(drop=True)
    validation = supervised.loc[(supervised["timestamp"] > train_cut) & (supervised["timestamp"] <= validation_cut)].copy().reset_index(drop=True)
    test = supervised.loc[supervised["timestamp"] > validation_cut].copy().reset_index(drop=True)
    if min(len(train), len(validation), len(test)) == 0:
        raise ValueError("Chronological split produced an empty partition.")

    # Thresholds are fitted on train only and remain frozen for all holdouts and inference.
    thresholds = fit_risk_thresholds(train)
    y_train_class = _risk_labels(train, thresholds)
    y_validation_class = _risk_labels(validation, thresholds)
    y_test_class = _risk_labels(test, thresholds)
    if len(np.unique(y_train_class)) < 2:
        raise ValueError("Training partition contains fewer than two relative-demand classes; classification is not trainable.")

    X_train, X_validation, X_test = (part[FEATURE_COLUMNS] for part in (train, validation, test))
    y_train, y_validation, y_test = (part[TARGET].astype(float) for part in (train, validation, test))
    benchmark_regression: dict[str, Any] = {}
    benchmark_classification: dict[str, Any] = {}
    regression_fitted: dict[str, Any] = {}
    for key in REGRESSION_KEYS:
        model = make_regression_model(key)
        started = time.perf_counter()
        model.fit(X_train, y_train)
        elapsed = time.perf_counter() - started
        metrics, _ = _score_regression(model, X_validation, y_validation)
        regression_fitted[key] = model
        benchmark_regression[key] = {"key": key, "validation": metrics, "fit_seconds": round(elapsed, 3)}
        print(f"[validation] regression {key:20s} MAE={metrics['mae']:.3f} RMSE={metrics['rmse']:.3f} R2={metrics['r2']:.4f}")
    regression_ranked = sorted(REGRESSION_KEYS, key=lambda key: (
        benchmark_regression[key]["validation"]["mae"], benchmark_regression[key]["validation"]["rmse"]
    ))
    champion_reg_key = regression_ranked[0]

    for key in CLASSIFICATION_KEYS:
        model = make_classification_model(key)
        started = time.perf_counter()
        _fit_classifier(key, model, X_train, y_train_class)
        elapsed = time.perf_counter() - started
        metrics, _ = _score_classification(key, model, X_validation, y_validation_class)
        benchmark_classification[key] = {"key": key, "validation": metrics, "fit_seconds": round(elapsed, 3)}
        print(f"[validation] classification {key:20s} macro-F1={metrics['f1_macro']:.4f} high-recall={metrics['high_recall']:.3f} severe-recall={metrics['severe_recall']:.3f}")
    classification_ranked = sorted(CLASSIFICATION_KEYS, key=lambda key: (
        -benchmark_classification[key]["validation"]["f1_macro"],
        -benchmark_classification[key]["validation"]["high_recall"], key
    ))
    champion_clf_key = classification_ranked[0]

    combined = pd.concat([train, validation], ignore_index=True).sort_values(["timestamp", "entity_id"], kind="stable")
    X_combined, X_holdout = combined[FEATURE_COLUMNS], X_test
    y_combined = combined[TARGET].astype(float)
    y_combined_class = _risk_labels(combined, thresholds)
    regression_test_metrics: dict[str, dict] = {}
    classification_test_metrics: dict[str, dict] = {}
    for key in REGRESSION_KEYS:
        model = make_regression_model(key)
        model.fit(X_combined, y_combined)
        metrics, _ = _score_regression(model, X_holdout, y_test)
        regression_test_metrics[key] = metrics
        print(f"[test]       regression {key:20s} MAE={metrics['mae']:.3f} RMSE={metrics['rmse']:.3f} R2={metrics['r2']:.4f}")
    for key in CLASSIFICATION_KEYS:
        model = make_classification_model(key)
        _fit_classifier(key, model, X_combined, y_combined_class)
        metrics, _ = _score_classification(key, model, X_holdout, y_test_class)
        classification_test_metrics[key] = metrics
        print(f"[test]       classification {key:20s} macro-F1={metrics['f1_macro']:.4f} high-recall={metrics['high_recall']:.3f} severe-recall={metrics['severe_recall']:.3f}")

    # The validation-selected winner is refit on train+validation; test never selects it.
    final_regression_model = make_regression_model(champion_reg_key)
    final_regression_model.fit(X_combined, y_combined)
    final_classification_model = make_classification_model(champion_clf_key)
    _fit_classifier(champion_clf_key, final_classification_model, X_combined, y_combined_class)
    # Report held-out metrics for the exact champion objects that will be persisted.
    # Parallel histogram boosting can be nondeterministic across separate fits.
    regression_test_metrics[champion_reg_key], _ = _score_regression(final_regression_model, X_holdout, y_test)
    classification_test_metrics[champion_clf_key], _ = _score_classification(
        champion_clf_key, final_classification_model, X_holdout, y_test_class
    )
    global_importance, native_importance = _feature_explanations(
        regression_fitted[champion_reg_key], X_validation, y_validation
    )

    training_distributions = _distribution_bundle(train, system_id)
    training_medians = {
        column: float(pd.to_numeric(train[column], errors="coerce").median())
        for column in FEATURE_COLUMNS if column != "entity_id"
    }
    hourly_times = pd.to_datetime(hourly["timestamp"])
    pca_training_rows = hourly.loc[hourly_times <= train_cut].copy()
    station_analytics = fit_pca_dbscan(pca_training_rows, min_samples=3)
    station_analytics["system_id"] = system_id
    station_analytics["city"] = family["city"]
    station_analytics["mode"] = family["mode"]
    station_analytics["operator"] = family["operator"]
    entity_ids = sorted(hourly["entity_id"].astype(str).unique().tolist())
    entity_names = {
        str(entity_id): str(name)
        for entity_id, name in hourly[["entity_id", "entity_name"]].drop_duplicates().itertuples(index=False, name=None)
    }
    created_at = datetime.now(timezone.utc).isoformat()
    data_metadata = dict(dataset_metadata or {})
    data_metadata["training_validation"] = quality
    data_metadata.setdefault("system", {key: family[key] for key in ("system_id", "city", "mode", "operator")})
    data_metadata.setdefault("source", "verified observed station-hour demand")

    model_report = {
        "project": "INDIA TRANSIT CROWD AI",
        "tagline": "PREDICT THE CROWD. PLAN THE JOURNEY.",
        "model_version": MODEL_VERSION,
        "training_timestamp_utc": created_at,
        "model_family": family,
        "dataset": {
            **data_metadata,
            "observed_entity_hour_rows": int(len(hourly)),
            "supervised_rows": int(len(supervised)),
            "columns": list(hourly.columns),
            "entity_ids": entity_ids,
            "entity_names": entity_names,
            "entity_count": int(len(entity_ids)),
            "explicit_zero_observations": int(hourly["demand_count"].eq(0).sum()),
            "missing_observations_filled": 0,
            "timestamp_min": pd.Timestamp(hourly["timestamp"].min()).isoformat(),
            "timestamp_max": pd.Timestamp(hourly["timestamp"].max()).isoformat(),
            "target_measure": family["measure"],
            "target_semantics": "next consecutive station-hour boardings; not onboard load or physical occupancy",
        },
        "feature_schema": {
            "feature_count": len(FEATURE_COLUMNS), "features": FEATURE_COLUMNS,
            "time_features": TIME_FEATURES, "historical_features": HISTORY_FEATURES,
            "target": TARGET,
            "target_semantics": "observed station boardings in target hour T, using only observations strictly before T",
        },
        "split": {
            "strategy": "Chronological global target-time split over unique station-hour timestamps: earliest 70% train, next 15% validation, latest 15% test; same timestamp never crosses partitions.",
            "train": {"rows": int(len(train)), "start": str(train["timestamp"].min()), "end": str(train["timestamp"].max()), "unique_target_hours": int(train["timestamp"].nunique())},
            "validation": {"rows": int(len(validation)), "start": str(validation["timestamp"].min()), "end": str(validation["timestamp"].max()), "unique_target_hours": int(validation["timestamp"].nunique())},
            "test": {"rows": int(len(test)), "start": str(test["timestamp"].min()), "end": str(test["timestamp"].max()), "unique_target_hours": int(test["timestamp"].nunique())},
            "train_cutoff": train_cut.isoformat(),
            "validation_cutoff": validation_cut.isoformat(),
            "time_series_cross_validation": "Three expanding-window TimeSeriesSplit folds within train; thresholds fitted separately on each fold's training rows only.",
            "leakage_controls": [
                "Target features for hour T use entity-hour observations strictly before T.",
                "Only consecutive observed hourly histories train; missing station-hours stay missing and are not zero-filled.",
                "Explicit source zeros are retained as observations; no entity is discarded solely for low or zero demand.",
                "Risk thresholds are fitted from chronological train targets only and frozen for validation, test and inference.",
                "Validation selects the champion; the latest test window is reported once and never used for selection.",
                "PCA/DBSCAN behaviour features are fitted from observations through the training cutoff only.",
            ],
        },
        "cross_validation": _cross_validate(train),
        "regression": {
            "selection_metric": "validation MAE; tie-break on validation RMSE",
            "champion_key": champion_reg_key,
            "champion_name": champion_reg_key.replace("_", " ").title(),
            "ranking_by_validation": regression_ranked,
            "models": [
                {"key": key, "name": key.replace("_", " ").title(),
                 "validation": benchmark_regression[key]["validation"], "test": regression_test_metrics[key],
                 "fit_seconds": benchmark_regression[key]["fit_seconds"], "validation_rank": regression_ranked.index(key) + 1}
                for key in REGRESSION_KEYS
            ],
        },
        "classification": {
            "selection_metric": "validation macro F1; tie-break on HIGH recall; model key breaks remaining ties",
            "champion_key": champion_clf_key,
            "champion_name": champion_clf_key.replace("_", " ").title(),
            "ranking_by_validation": classification_ranked,
            "models": [
                {"key": key, "name": key.replace("_", " ").title(),
                 "validation": benchmark_classification[key]["validation"], "test": classification_test_metrics[key],
                 "fit_seconds": benchmark_classification[key]["fit_seconds"], "validation_rank": classification_ranked.index(key) + 1}
                for key in CLASSIFICATION_KEYS
            ],
        },
        "demand_risk": thresholds,
        "explainability": {
            "global_method": "Permutation importance on chronological validation observations, scoring increase in MAE; associational, not causal.",
            "native_method": "Native tree feature importance for the selected regression model when supported.",
            "local_method": "At inference, one feature at a time is replaced with its training median and the selected model is re-run; not SHAP and not causal attribution.",
            "global_feature_importance": global_importance,
            "native_feature_importance": native_importance,
            "uncertainty": "No calibrated prediction interval or confidence percentage is produced.",
        },
        "station_analytics": station_analytics,
        "artifacts": {
            "bundle": "transitcrowd.joblib", "report": "model_report.json",
            "station_analytics": "station_analytics.json",
        },
        "limitations": [
            "Only the verified Bengaluru BMRCL/Namma Metro hourly station-boardings family has a trained model; no India-wide, bus, live or other-operator prediction is implied.",
            "This source is a historical snapshot ending 2025-09-30, with a documented 2025-08-19 through 2025-08-31 gap and a changing station roster during August.",
            "The holdout is a short late-period check; it does not establish yearly seasonality or generalization to current 2026 service conditions.",
            "Counts are station boardings, not onboard vehicle load or physical occupancy; capacity data is unavailable.",
            "No current timetable, disruption, weather, event, transfer, passenger-origin or service-frequency variables are joined to the model.",
            "Forecasts beyond the most recent observation are recursive one-hour model calls, limited to 336 hours from the data frontier; uncertainty is not calibrated.",
            "No confidence percentage is produced; missing target-period source observations must not be read as zero actual demand.",
        ],
    }

    bundle = {
        "model_version": MODEL_VERSION,
        "system_id": system_id,
        "model_family": family,
        "created_at_utc": created_at,
        "regression_model": final_regression_model,
        "regression_model_key": champion_reg_key,
        "classification_model": final_classification_model,
        "classification_model_key": champion_clf_key,
        "classification_label_encoding": champion_clf_key == "xgboost",
        "feature_columns": FEATURE_COLUMNS,
        "numeric_features": [feature for feature in FEATURE_COLUMNS if feature != "entity_id"],
        "entity_ids": entity_ids,
        "entity_names": entity_names,
        "risk_thresholds": thresholds,
        "training_distributions": training_distributions,
        "training_medians": training_medians,
        "training_cutoff": train_cut.isoformat(),
        "validation_cutoff": validation_cut.isoformat(),
        "max_recursive_horizon_hours": 336,
        "global_feature_importance": global_importance,
        "native_feature_importance": native_importance,
        "dataset_metadata": data_metadata,
        "model_report": model_report,
    }
    joblib.dump(bundle, output_dir / "transitcrowd.joblib", compress=3)
    (output_dir / "model_report.json").write_text(json.dumps(_jsonable(model_report), indent=2, allow_nan=False), encoding="utf-8")
    (output_dir / "station_analytics.json").write_text(json.dumps(_jsonable(station_analytics), indent=2, allow_nan=False), encoding="utf-8")
    print(f"Training rows={len(train):,}, validation={len(validation):,}, test={len(test):,}; entities={len(entity_ids)}; system={system_id}")
    return model_report
