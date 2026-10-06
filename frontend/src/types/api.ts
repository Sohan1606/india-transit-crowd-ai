export type Risk = 'LOW' | 'MODERATE' | 'HIGH' | 'SEVERE'

export interface TransitSystem {
  system_id: string
  system_name: string
  city: string
  state: string
  mode: string
  operator: string
  prediction_available: boolean
  prediction_status: string
  observed_demand_status: string
  demand_source_url: string | null
  network_reference_url: string | null
  network_reference_kind: string
  network_reference_note: string
  prediction_unavailable_reason: string | null
  station_count: number | null
  data_period: Array<Record<string, string>>
}

export interface DemandSourceCandidate {
  city: string
  system: string
  source_title: string
  url: string
  published_granularity: string
  access_status: string
  forecast_suitability: string
  prediction_enabled: boolean
}

export interface DemandSourcesResponse {
  verified_prediction_source_ids: string[]
  additional_observed_demand_candidates: DemandSourceCandidate[]
  policy: string
}

export interface DatasetMetadata {
  title: string
  source_url: string
  source_data_url?: string
  source_commit?: string
  source_sha256?: string
  license?: string
  license_url?: string
  attribution?: string
  granularity: string
  measure?: string
  timestamp_min: string
  timestamp_max: string
  observed_rows: number
  station_count: number
  station_ids: string[]
  station_names: Record<string, string>
  source_periods: Array<Record<string, string>>
  explicit_zero_observations: number
  missing_observations_filled: number
  source_metadata?: Record<string, unknown>
  is_live: boolean
}

export interface AppMetadata {
  project: string
  tagline: string
  system_id: string
  city: string
  mode: string
  operator: string
  model_scope: string
  timezone: string
  dataset: DatasetMetadata
  features: { count: number; columns: string[] }
  primary_target: string
  risk_definition: string
  default_station_id: string
  default_target_date: string
  default_target_hour: number
  default_target_timestamp: string
  prediction_max_recursive_horizon_hours: number
  regression_champion: string
  classification_champion: string
}

export interface StationSummary {
  station_id: string
  station_name: string
  mean_hourly_boardings: number
  latest_observation: string
  observed_hours: number
  system_id: string
}

export interface ExplanationItem {
  feature: string
  label: string
  actual_value: number
  reference_value: number
  prediction_with_reference: number
  delta_boardings: number
  absolute_delta: number
  direction: string
}

export interface RecommendationCandidate {
  timestamp: string
  hour: number
  predicted_boardings: number
  relative_demand_band: Risk
  historical_percentile: number | null
  offset_hours: number
}

export interface Recommendation {
  status: 'available' | 'no_lower_demand_window' | 'insufficient_data'
  message: string
  basis: string
  recommended?: RecommendationCandidate
  selected_predicted_boardings?: number
  reduction_percent?: number | null
  candidates: RecommendationCandidate[]
  skipped_candidates_insufficient_history?: number
}

export interface PredictionResult {
  system_id: string
  station_id: string
  station_name: string
  target_timestamp: string
  origin_timestamp: string
  predicted_boardings: number
  measure: string
  relative_demand_band: Risk
  risk: Risk
  risk_method: string
  risk_thresholds: { q50: number; q80: number; q95: number }
  threshold_sample_count: number
  historical_percentile: number | null
  classification_check: Risk
  classification_agrees: boolean
  regression_model: string
  classification_model: string
  forecast_horizon_hours: number
  is_recursive_forecast: boolean
  forecast_kind: 'historical_replay' | 'unobserved_hour_estimate' | 'post_snapshot_projection' | string
  forecast_note: string
  explanation: ExplanationItem[]
  explanation_method: string
  recommendation: Recommendation
}

export interface HistoryPoint {
  timestamp: string
  observed_boardings: number
  observation_type: 'observed'
}

export interface HistoryResponse {
  system_id: string
  station_id: string
  points: HistoryPoint[]
  measure: string
  source: string
}

export interface HeatmapCell {
  day_of_week: number
  day_name: string
  hour: number
  mean_observed_boardings: number | null
  observations: number
}

export interface HeatmapResponse {
  system_id: string
  station_id: string
  cells: HeatmapCell[]
  measure: string
  source: string
}

export interface StationAnalyticsPoint {
  entity_id: string
  entity_name: string
  pc1: number
  pc2: number
  cluster_id: number
  is_outlier: boolean
  behaviour: Record<string, number>
}

export interface StationAnalytics {
  system_id: string
  method: string
  entity_count: number
  features_used: string[]
  pca: { components: number; explained_variance_ratio: number[]; total_explained_variance_ratio: number }
  dbscan: {
    eps: number
    min_samples: number
    metric: string
    eps_selection: string
    cluster_count_excluding_noise: number
    outlier_count: number
    outlier_entity_ids: string[]
    clusters: Array<{ cluster_id: number; entity_count: number; entities: string[] }>
  }
  entities: StationAnalyticsPoint[]
  interpretation_note: string
}

export interface MetricSet {
  mae?: number
  rmse?: number
  r2?: number | null
  accuracy?: number
  precision_macro?: number
  recall_macro?: number
  f1_macro?: number
  f1_weighted?: number
  high_recall?: number
  severe_recall?: number
  cohen_kappa?: number | null
  roc_auc_ovr_macro?: number | null
  confusion_matrix?: number[][]
  class_order?: string[]
  classification_report?: Record<string, { precision: number; recall: number; f1_score?: number; support?: number }>
  [key: string]: unknown
}

export interface ModelResult {
  key: string
  name: string
  validation: MetricSet
  test: MetricSet
  validation_rank: number
  fit_seconds: number
}

export interface ModelReport {
  project: string
  tagline: string
  model_version: string
  training_timestamp_utc: string
  model_family: { system_id: string; city: string; mode: string; operator: string; [key: string]: unknown }
  dataset: {
    observed_entity_hour_rows: number
    supervised_rows: number
    entity_ids: string[]
    entity_names: Record<string, string>
    entity_count: number
    timestamp_min: string
    timestamp_max: string
    explicit_zero_observations: number
    target_measure: string
    [key: string]: unknown
  }
  feature_schema: { feature_count: number; features: string[]; target: string; target_semantics: string }
  split: {
    strategy: string
    train: { rows: number; unique_target_hours?: number; start: string; end: string }
    validation: { rows: number; unique_target_hours?: number; start: string; end: string }
    test: { rows: number; unique_target_hours?: number; start: string; end: string }
  }
  regression: { champion_key: string; champion_name: string; ranking_by_validation: string[]; models: ModelResult[] }
  classification: { champion_key: string; champion_name: string; ranking_by_validation: string[]; models: ModelResult[] }
  demand_risk: {
    global: { q50: number; q80: number; q95: number; sample_count: number }
    systems: Record<string, { q50: number; q80: number; q95: number; source: string; sample_count: number }>
    entities: Record<string, { q50: number; q80: number; q95: number; source: string; sample_count: number }>
    definitions: Record<string, string>
  }
  explainability: { global_method: string; global_feature_importance: Array<{ feature: string; importance: number; std: number }>; native_feature_importance?: unknown[] }
  station_analytics: StationAnalytics
  cross_validation: { n_splits: number; regression_mean_mae: number | null; classification_mean_macro_f1: number | null }
  limitations: string[]
}

export interface StationComparison {
  system_id: string
  target_timestamp: string
  comparison_basis: string
  stations: Array<{ station_id: string; station_name: string; predicted_boardings: number; relative_demand_band: Risk; historical_percentile: number | null; is_selected: boolean }>
  stations_without_estimate: number
}
