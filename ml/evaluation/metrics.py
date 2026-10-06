"""Evaluation metrics with fixed, explicit label order for reproducible reports."""
from __future__ import annotations
from typing import Any
import numpy as np
from sklearn.metrics import (
    accuracy_score, classification_report, cohen_kappa_score, confusion_matrix,
    f1_score, mean_absolute_error, mean_squared_error, precision_score,
    r2_score, recall_score, roc_auc_score,
)
from ml.training.risk import RISK_ORDER


def regression_metrics(y_true, y_pred) -> dict[str, float]:
    actual = np.asarray(y_true, dtype=float)
    predicted = np.asarray(y_pred, dtype=float)
    rmse = float(np.sqrt(mean_squared_error(actual, predicted)))
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": rmse,
        "r2": float(r2_score(actual, predicted)) if len(actual) > 1 else float("nan"),
    }


def classification_metrics(y_true, y_pred, probabilities: np.ndarray | None = None) -> dict[str, Any]:
    actual = np.asarray(y_true, dtype=str)
    predicted = np.asarray(y_pred, dtype=str)
    report = classification_report(actual, predicted, labels=RISK_ORDER, output_dict=True, zero_division=0)
    result: dict[str, Any] = {
        "accuracy": float(accuracy_score(actual, predicted)),
        "precision_macro": float(precision_score(actual, predicted, labels=RISK_ORDER, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(actual, predicted, labels=RISK_ORDER, average="macro", zero_division=0)),
        "f1_macro": float(f1_score(actual, predicted, labels=RISK_ORDER, average="macro", zero_division=0)),
        "f1_weighted": float(f1_score(actual, predicted, labels=RISK_ORDER, average="weighted", zero_division=0)),
        "cohen_kappa": float(cohen_kappa_score(actual, predicted, labels=RISK_ORDER)),
        "confusion_matrix": confusion_matrix(actual, predicted, labels=RISK_ORDER).tolist(),
        "class_order": RISK_ORDER,
        "classification_report": report,
        "high_recall": float(report["HIGH"]["recall"]),
        "severe_recall": float(report["SEVERE"]["recall"]),
        "roc_auc_ovr_macro": None,
        "roc_auc_note": "Not available: a probability score for every risk class and all four classes in the evaluation partition are required.",
    }
    if probabilities is not None and len(np.unique(actual)) == len(RISK_ORDER):
        try:
            # sklearn requires the `labels` argument to be ordered; the product's
            # presentation order is LOW/MODERATE/HIGH/SEVERE, not alphabetical.
            auc_order = sorted(RISK_ORDER)
            column_order = [RISK_ORDER.index(label) for label in auc_order]
            result["roc_auc_ovr_macro"] = float(roc_auc_score(
                actual, probabilities[:, column_order], labels=auc_order,
                multi_class="ovr", average="macro",
            ))
            result["roc_auc_note"] = "One-vs-rest macro ROC-AUC from predicted class probabilities; class order aligned alphabetically for sklearn."
        except (ValueError, TypeError):
            pass
    return result
