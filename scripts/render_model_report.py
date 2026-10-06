"""Render India model-family results as an auditable Markdown report."""
from __future__ import annotations
from typing import Any


def _fmt(value: Any, digits: int = 3) -> str:
    return f"{value:,.{digits}f}" if isinstance(value, (int, float)) else "—"


def _metric_rows(report: dict, task: str) -> list[str]:
    rows = ["| Rank | Candidate | Validation | Test | Fit (s) |", "|---:|---|---:|---:|---:|"]
    models = report[task]["models"]
    for item in sorted(models, key=lambda value: value["validation_rank"]):
        if task == "regression":
            validation = f"MAE {_fmt(item['validation'].get('mae'), 2)} · RMSE {_fmt(item['validation'].get('rmse'), 2)} · R² {_fmt(item['validation'].get('r2'), 3)}"
            test = f"MAE {_fmt(item['test'].get('mae'), 2)} · RMSE {_fmt(item['test'].get('rmse'), 2)} · R² {_fmt(item['test'].get('r2'), 3)}"
        else:
            validation = f"macro-F1 {_fmt(item['validation'].get('f1_macro'), 3)} · HIGH recall {_fmt(item['validation'].get('high_recall'), 3)}"
            test = f"macro-F1 {_fmt(item['test'].get('f1_macro'), 3)} · HIGH recall {_fmt(item['test'].get('high_recall'), 3)} · SEVERE recall {_fmt(item['test'].get('severe_recall'), 3)}"
        rows.append(f"| {item['validation_rank']} | {item['name']} | {validation} | {test} | {_fmt(item.get('fit_seconds'), 3)} |")
    return rows


def render(report: dict) -> str:
    family = report.get("model_family", {})
    dataset = report.get("dataset", {})
    split = report.get("split", {})
    risk = report.get("demand_risk", {})
    lines = [
        f"# {report.get('project', 'India Transit Crowd AI')} — Model report",
        "",
        f"> **{report.get('tagline', 'PREDICT THE CROWD. PLAN THE JOURNEY.')}**",
        "",
        "## Model scope",
        "",
        f"- **System:** {family.get('city', '—')} · {family.get('mode', '—')} · {family.get('operator', '—')} (`{family.get('system_id', '—')}`).",
        f"- **Model version:** `{report.get('model_version', '—')}`; trained {report.get('training_timestamp_utc', '—')}.",
        f"- **Observed source rows:** {dataset.get('observed_entity_hour_rows', 0):,}; **supervised rows:** {dataset.get('supervised_rows', 0):,}; **entities:** {dataset.get('entity_count', 0):,}.",
        f"- **Source window:** {dataset.get('timestamp_min', '—')} through {dataset.get('timestamp_max', '—')} (timestamps use the source timezone).",
        f"- **Explicit zero observations retained:** {dataset.get('explicit_zero_observations', 0):,}; **missing observations filled:** {dataset.get('missing_observations_filled', 0)}.",
        f"- **Target:** next consecutive station-hour boardings (`{dataset.get('target_measure', '—')}`), not onboard load or physical occupancy.",
        f"- **Source:** {dataset.get('source_title', 'verified BMRCL/Namma Metro station-hour snapshot')} — {dataset.get('source_url', 'see dataset documentation')}.",
        f"- **License:** {dataset.get('license', 'ODbL-1.0')} — {dataset.get('license_url', 'see data/licenses/ODbL-1.0.txt')}.",
        "",
        "Only this verified Bengaluru BMRCL/Namma Metro model family is enabled. No India-wide, bus, live, or other-operator predictions are represented by this report.",
        "",
        "## Chronological evaluation design",
        "",
        f"{split.get('strategy', 'Chronological split; see code for exact boundaries')}",
        "",
        "| Partition | Rows | Unique target hours | Start | End |",
        "|---|---:|---:|---|---|",
    ]
    for key, label in (("train", "Train"), ("validation", "Validation"), ("test", "Test")):
        part = split.get(key, {})
        lines.append(f"| {label} | {part.get('rows', 0):,} | {part.get('unique_target_hours', '—')} | {part.get('start', '—')} | {part.get('end', '—')} |")
    lines.extend([
        "",
        "The final holdout is not used to select the winning model. Three expanding-window `TimeSeriesSplit` folds run within training data. Thresholds are refitted using each fold's training rows only.",
        "",
        "The selected champions are refitted on train + validation; their reported test metrics are recomputed from the exact persisted champion objects and independently replayed without refitting. Other candidates are measured on their benchmark fits.",
        "",
        "### Leakage controls",
        "",
    ])
    lines.extend([f"- {item}" for item in split.get("leakage_controls", [])])
    lines.extend([
        "",
        "## Regression benchmark",
        "",
        f"**Validation-selected model:** {report['regression']['champion_name']} (MAE first; RMSE tie-break).",
        "",
        *_metric_rows(report, "regression"),
        "",
        "## Historical-relative classification benchmark",
        "",
        f"**Validation-selected model:** {report['classification']['champion_name']} (macro-F1, then HIGH recall).",
        "",
        *_metric_rows(report, "classification"),
        "",
        "Risk thresholds are trained-only historical percentiles, frozen for validation/test/inference:",
        "",
        f"- Global training cuts: P50 **{_fmt(risk.get('global', {}).get('q50'), 0)}**, P80 **{_fmt(risk.get('global', {}).get('q80'), 0)}**, P95 **{_fmt(risk.get('global', {}).get('q95'), 0)}** station boardings per hour.",
        f"- Threshold hierarchy: station/entity when adequately sampled → city/mode/operator system → global training fallback. Minimum entity targets: {risk.get('minimum_entity_training_targets', '—')}; minimum system targets: {risk.get('minimum_system_training_targets', '—')}.",
        "- Labels: LOW ≤ P50; MODERATE > P50 and ≤ P80; HIGH > P80 and ≤ P95; SEVERE > P95.",
        "- These labels express relative historical demand only; they are not calibrated physical crowding, capacity or safety levels.",
        "",
        "## PCA / DBSCAN station profiles",
        "",
    ])
    analytics = report.get("station_analytics", {})
    pca = analytics.get("pca", {})
    dbscan = analytics.get("dbscan", {})
    lines.extend([
        f"- Fitted on observed records through the training cutoff only; entities: {analytics.get('entity_count', '—')}.",
        f"- Two-component PCA variance retained: {_fmt(pca.get('total_explained_variance_ratio'), 4)}.",
        f"- DBSCAN groups (excluding noise): {dbscan.get('cluster_count_excluding_noise', '—')}; noise points: {dbscan.get('outlier_count', '—')}; ε={_fmt(dbscan.get('eps'), 4)}, min_samples={dbscan.get('min_samples', '—')}.",
        f"- {analytics.get('interpretation_note', '')}",
        "",
        "## Model-backed explanations",
        "",
        f"- Global: {report.get('explainability', {}).get('global_method', '—')}",
        f"- Local: {report.get('explainability', {}).get('local_method', '—')}",
        f"- Uncertainty: {report.get('explainability', {}).get('uncertainty', 'No calibrated interval or confidence is available.')}",
        "",
        "## Limitations",
        "",
    ])
    lines.extend([f"- {item}" for item in report.get("limitations", [])])
    lines.extend([
        "",
        "This report describes the specific source snapshot and trained model artifact only. It does not validate performance for another operator, mode, city, present-day service or the whole country.",
        "",
    ])
    return "\n".join(lines)
