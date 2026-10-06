"""PCA + DBSCAN profiles for observed station/entity demand in the training window."""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

CLUSTER_FEATURES = [
    "mean_demand", "morning_mean", "afternoon_mean", "evening_mean", "weekend_mean",
    "peak_demand_q95", "variance", "coefficient_of_variation", "demand_concentration_top6_hours",
    "peak_to_average_ratio",
]


def entity_behaviour_features(hourly: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "entity_id", "demand_count"}
    if not required.issubset(hourly.columns):
        raise ValueError(f"Entity behaviour input must contain {sorted(required)}")
    df = hourly.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["demand_count"] = pd.to_numeric(df["demand_count"], errors="coerce")
    df = df.dropna(subset=["timestamp", "entity_id", "demand_count"])
    df["hour"] = df["timestamp"].dt.hour
    df["is_weekend"] = df["timestamp"].dt.dayofweek >= 5
    rows: list[dict[str, Any]] = []
    for entity_id, group in df.groupby("entity_id", sort=True):
        mean = float(group["demand_count"].mean())
        std = float(group["demand_count"].std(ddof=0))
        by_hour = group.groupby("hour")["demand_count"].mean().reindex(range(24))
        # Only clock hours with an actual source observation contribute; absent
        # hours are not converted into synthetic zero-demand profile features.
        hour_profile = by_hour.dropna().to_numpy(dtype=float)
        total_profile = float(hour_profile.sum())
        top_hours = min(6, len(hour_profile))
        concentration = float(np.sort(hour_profile)[-top_hours:].sum() / total_profile) if total_profile > 0 else 0.0
        q95 = float(group["demand_count"].quantile(0.95))
        rows.append({
            "entity_id": str(entity_id),
            "entity_name": str(group["entity_name"].iloc[0]) if "entity_name" in group.columns else str(entity_id),
            "mean_demand": mean,
            "morning_mean": float(group.loc[group["hour"].between(7, 10), "demand_count"].mean()),
            "afternoon_mean": float(group.loc[group["hour"].between(11, 15), "demand_count"].mean()),
            "evening_mean": float(group.loc[group["hour"].between(16, 19), "demand_count"].mean()),
            "weekend_mean": float(group.loc[group["is_weekend"], "demand_count"].mean()),
            "peak_demand_q95": q95,
            "variance": float(group["demand_count"].var(ddof=0)),
            "coefficient_of_variation": std / mean if mean > 0 else 0.0,
            "demand_concentration_top6_hours": concentration,
            "peak_to_average_ratio": q95 / mean if mean > 0 else 0.0,
        })
    result = pd.DataFrame(rows)
    result[CLUSTER_FEATURES] = result[CLUSTER_FEATURES].replace([np.inf, -np.inf], np.nan)
    result[CLUSTER_FEATURES] = result[CLUSTER_FEATURES].fillna(result[CLUSTER_FEATURES].median()).fillna(0.0)
    return result


def fit_pca_dbscan(hourly: pd.DataFrame, min_samples: int = 3) -> dict[str, Any]:
    features = entity_behaviour_features(hourly)
    if len(features) < 3:
        raise ValueError("PCA/DBSCAN requires at least three observed entities.")
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features[CLUSTER_FEATURES])
    pca = PCA(n_components=2, random_state=42)
    coordinates = pca.fit_transform(scaled)
    neighbors_n = min(min_samples + 1, len(features))
    distances, _ = NearestNeighbors(n_neighbors=neighbors_n).fit(coordinates).kneighbors(coordinates)
    k_distance = distances[:, -1]
    eps = float(np.quantile(k_distance, 0.75))
    if not np.isfinite(eps) or eps <= 0:
        positive = k_distance[k_distance > 0]
        eps = float(np.median(positive)) if len(positive) else 1e-6
    labels = DBSCAN(eps=eps, min_samples=min_samples, metric="euclidean").fit_predict(coordinates)
    output_entities: list[dict[str, Any]] = []
    for i, row in features.iterrows():
        label = int(labels[i])
        output_entities.append({
            "entity_id": str(row["entity_id"]),
            "entity_name": str(row["entity_name"]),
            "pc1": float(coordinates[i, 0]),
            "pc2": float(coordinates[i, 1]),
            "cluster_id": label,
            "is_outlier": label == -1,
            "behaviour": {column: float(row[column]) for column in CLUSTER_FEATURES},
        })
    cluster_labels = sorted(set(int(value) for value in labels if int(value) != -1))
    cluster_summary = [
        {"cluster_id": label, "entity_count": int(np.sum(labels == label)),
         "entities": sorted([item["entity_id"] for item in output_entities if item["cluster_id"] == label])}
        for label in cluster_labels
    ]
    return {
        "method": "StandardScaler → PCA (2 components) → DBSCAN in PCA space",
        "entity_count": int(len(features)),
        "features_used": CLUSTER_FEATURES,
        "pca": {
            "components": 2,
            "explained_variance_ratio": [float(value) for value in pca.explained_variance_ratio_],
            "total_explained_variance_ratio": float(pca.explained_variance_ratio_.sum()),
        },
        "dbscan": {
            "eps": eps,
            "min_samples": int(min_samples),
            "metric": "euclidean",
            "eps_selection": "75th percentile of observed distance to the min_samples-th nearest entity in the two-dimensional PCA projection",
            "cluster_count_excluding_noise": int(len(cluster_labels)),
            "outlier_count": int(np.sum(labels == -1)),
            "outlier_entity_ids": sorted([item["entity_id"] for item in output_entities if item["is_outlier"]]),
            "clusters": cluster_summary,
        },
        "entities": output_entities,
        "interpretation_note": "Cluster IDs and noise labels are algorithm outputs, not source-provided entity types. No manual cluster labels are assigned.",
    }
