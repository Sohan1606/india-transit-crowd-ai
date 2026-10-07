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
  /** Observation resolution of the registered model family: 'hour' or 'day'. */
  granularity?: 'hour' | 'day' | string
  /** ``demo`` = served on synthetic/modelled data; every answer carries its disclosure. */
  served_as?: 'production' | 'demo' | 'internal' | null
  dataset_class?: string | null
  data_class?: 'verified_observed' | 'synthetic_development' | 'unverified' | null
  disclosure?: string | null
  metrics_are_demonstration_only?: boolean
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
  /** Day-granularity families report calendar days; hourly families report hours. */
  unique_days?: number
  observed_days?: number
  mean_daily_entries?: number
  measure_semantics_check?: Record<string, unknown>
  redistribution?: string
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
  /** ``demo`` means the family is served on synthetic/modelled data and must be labelled as such. */
  served_as?: 'production' | 'demo' | 'internal' | null
  dataset_class?: string | null
  data_class?: 'verified_observed' | 'synthetic_development' | 'unverified' | null
  disclosure?: string | null
  metrics_are_demonstration_only?: boolean
  /** Clock hours (or published slot labels) the family's data actually contains; absent or full-length
   *  means "any hour". Values come from the source file, never from a per-city list in the client. */
  supported_time_slots?: (number | string)[] | null
  supported_time_note?: string | null
  /** Ordered levels identifying one series when a family's entity is more than a single station - e.g.
   *  a corridor and a station, or a line, an origin, a destination and a published time slot. */
  entity_hierarchy?: { column: string; label: string }[] | null
  /** Journey context derived from the source's own ordering columns, when it publishes them. */
  route_context?: RouteContext | null
  entity_selection?: string | null
  entities_with_declared_attributes?: number
  time_slot_note?: string | null
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
  /** Only hour-granularity families take a target hour. */
  default_target_hour?: number
  default_target_timestamp: string
  /** 'hour' families project up to `..._hours`; 'day' families up to `..._days`. */
  granularity?: 'hour' | 'day' | string
  prediction_max_recursive_horizon_hours?: number
  prediction_max_recursive_horizon_days?: number
  genuine_future_prediction_available?: boolean
  data_freshness_days?: number | null
  training_cutoff?: string | null
  regression_champion: string
  classification_champion: string
  regression_champion_test?: { mae: number; rmse?: number; r2?: number | null }
  seasonal_naive_test_mae?: number
}

/** Corridor ordering, endpoints and per-entity TOWARDS choices, computed at registration from the
 *  file's own position column - no route table is duplicated in the client. */
export interface RouteContext {
  group_column: string
  station_column: string
  position_column: string
  routes: Record<string, { ordered_stations: string[]; endpoints: string[] }>
  towards_for_entity: Record<string, string[]>
  towards_kind?: string
}

export interface StationSummary {
  station_id: string
  station_name: string
  mean_hourly_boardings: number
  latest_observation: string
  observed_hours: number
  system_id: string
  granularity?: 'hour' | 'day' | string
  mean_daily_entries?: number
  observed_days?: number
  /** The source's own description of this series, keyed by the family's hierarchy columns. */
  attributes?: Record<string, string>
}

export interface ExplanationItem {
  feature: string
  label: string
  actual_value: number
  reference_value: number
  prediction_with_reference: number
  /** Named per measure: `delta_boardings` hourly, `delta_entries` daily. */
  delta_boardings?: number
  delta_entries?: number
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

export interface RecommendationDayAlternative {
  date: string
  day_name: string
  predicted_entries: number
  relative_demand_band: Risk
  delta_vs_selected: number
  forecast_horizon_days: number
}

export interface Recommendation {
  status?: 'available' | 'no_lower_demand_window' | 'insufficient_data' | string
  message?: string
  basis?: string
  recommended?: RecommendationCandidate
  selected_predicted_boardings?: number
  reduction_percent?: number | null
  candidates?: RecommendationCandidate[]
  skipped_candidates_insufficient_history?: number
  /** Day-granularity families compare neighbouring days instead of hours. */
  advice_kind?: string
  summary?: string
  caveat?: string
  alternative_days?: RecommendationDayAlternative[]
}

export interface PredictionResult {
  /** What kind of data the answering family is built from; a demo family is never 'verified_observed'. */
  data_class?: 'verified_observed' | 'synthetic_development' | 'unverified' | null
  /** Set only for a demonstration family: the sentence that must be visible next to the answer. */
  disclosure?: string | null
  system_id: string
  station_id: string
  station_name: string
  target_timestamp: string
  origin_timestamp: string
  /** Hourly families answer in `predicted_boardings`; day families in `predicted_demand`. */
  predicted_boardings?: number
  predicted_demand?: number
  predicted_entries?: number
  unit?: string
  granularity?: 'hour' | 'day' | string
  target_date?: string
  model_version?: string
  data_frontier?: string | null
  training_cutoff?: string | null
  data_freshness_days?: number | null
  generated_at_utc?: string
  evaluation_context?: Record<string, unknown>
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
  forecast_horizon_hours?: number | null
  forecast_horizon_days?: number | null
  is_model_forecast?: boolean
  is_recursive_forecast: boolean
  forecast_kind: 'historical_replay' | 'unobserved_hour_estimate' | 'post_snapshot_projection' | string
  forecast_note: string
  /** 'data_frontier_recursive_seed' when a multi-day projection is seeded at the frontier rather than the day before. */
  origin_basis?: 'previous_observed_period' | 'data_frontier_recursive_seed' | string
  /** Scoring against the stored observation. Absent actual means the source never published that period. */
  actual_observed_demand?: number | null
  observation_status?: 'OBSERVED' | 'OBSERVED VALUE UNAVAILABLE' | string
  observation_rows?: number
  evaluation_status?: string
  absolute_error?: number | null
  signed_error?: number | null
  absolute_percentage_error?: number | null
  error_note?: string
  /** How far this answer reaches, and how accurate that far-out answer is known to be. */
  horizon_status?: 'within_validated_range' | 'beyond_validated_range' | 'unmeasured' | 'not_applicable_historical' | string
  horizon_validation?: HorizonValidation | null
  forecast_interval?: ForecastInterval | null
  explanation: ExplanationItem[]
  explanation_method: string
  recommendation: Recommendation
}

export interface HorizonValidation {
  status: string
  detail?: string
  measured_horizon_days?: number
  usable_horizon_days?: number
  serviceable_horizon_days?: number
  max_recursive_horizon_days?: number
  horizon_limit_days?: number
  evidence_horizon_days?: number
  band_basis?: 'measured_at_horizon' | 'worst_measured_horizon' | string
  mae_at_horizon?: number | null
  p90_absolute_error_at_horizon?: number | null
  p95_absolute_error_at_horizon?: number | null
  samples_at_horizon?: number
  reference_dispersion?: string | null
  beyond_measured_range_note?: string | null
  max_recursive_horizon_hours?: number
}

export interface ForecastInterval {
  lower: number
  upper: number
  level: string
  method: string
  horizon_days_used: number
  band_basis?: string
  calibrated: boolean
  is_confidence_interval: boolean
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

export interface WeeklyPatternCell {
  day_of_week: number
  day_name: string
  mean_observed_daily_entries: number | null
  median_observed_daily_entries?: number | null
  observations: number
}

export interface WeeklyPatternResponse {
  system_id: string
  station_id: string
  cells: WeeklyPatternCell[]
  measure: string
  source: string
  [key: string]: unknown
}

export interface FuturePreviewDay {
  date: string
  day_name: string
  forecast_horizon_days: number
  system_total_predicted_entries: number
  stations_projected: number
  weekend_indicator?: number
  busiest_station?: { station_id?: string; station_name?: string; predicted_entries?: number; relative_demand_band?: Risk; [key: string]: unknown } | null
}

export interface FuturePreviewResponse {
  kind: string
  statement: string
  system_id: string
  data_frontier: string | null
  training_cutoff: string | null
  days_requested: number
  days_projected: number
  model?: string
  days: FuturePreviewDay[]
  recent_observed_daily_total_mean_28d?: number | null
  expected_accuracy?: Record<string, number | string | null>
  generated_at_utc?: string
}

export interface SourceGapResponse {
  system_id: string
  data_frontier: string | null
  today_local?: string
  days_behind_today?: number | null
  next_unobserved_date?: string | null
  live_feed: boolean
  interpretation: string
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
  uses_test_metrics?: boolean
  selection_metric?: string
  ranking_by_validation?: string[]
  dataset: {
    observed_entity_hour_rows?: number
    observed_entity_day_rows?: number
    supervised_rows: number
    entity_ids: string[]
    entity_names: Record<string, string>
    entity_count?: number
    rows?: number
    unique_dates?: number
    timestamp_min?: string
    timestamp_max: string
    explicit_zero_observations: number
    target_measure: string
    [key: string]: unknown
  }
  feature_schema: { feature_count: number; features: string[]; target: string; target_semantics: string }
  split: {
    strategy: string
    holdout_days?: number
    train: { rows: number; unique_target_hours?: number; unique_days?: number; start: string; end: string }
    validation: { rows: number; unique_target_hours?: number; unique_days?: number; start: string; end: string }
    test: { rows: number; unique_target_hours?: number; unique_days?: number; start: string; end: string }
  }
  regression: { champion_key: string; champion_name: string; selection_metric?: string; uses_test_metrics?: boolean; ranking_by_validation: string[]; models: ModelResult[] }
  classification: { champion_key: string; champion_name: string; selection_metric?: string; uses_test_metrics?: boolean; ranking_by_validation: string[]; models: ModelResult[] }
  demand_risk: {
    global: { q50: number; q80: number; q95: number; sample_count: number }
    systems: Record<string, { q50: number; q80: number; q95: number; source: string; sample_count: number }>
    entities: Record<string, { q50: number; q80: number; q95: number; source: string; sample_count: number }>
    definitions: Record<string, string>
  }
  explainability: { global_method: string; global_feature_importance: Array<{ feature: string; importance: number; std: number }>; native_feature_importance?: unknown[] }
  station_analytics?: StationAnalytics
  cross_validation?: { n_splits: number; regression_mean_mae: number | null; classification_mean_macro_f1: number | null }
  limitations: string[]
}

export interface StationComparison {
  system_id: string
  target_timestamp: string
  comparison_basis: string
  forecast_horizon_days?: number | null
  is_model_forecast?: boolean
  stations: Array<{ station_id: string; station_name: string; predicted_boardings?: number; predicted_daily_entries?: number; relative_demand_band: Risk; historical_percentile: number | null; is_selected: boolean }>
  stations_without_estimate: number
}
