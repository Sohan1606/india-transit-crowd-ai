import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PredictSection } from '../src/sections/PredictSection'
import { StationDemandSection } from '../src/sections/DemandSection'
import { api } from '../src/services/api'
import type { AppMetadata, PredictionResult, StationSummary, TransitSystem } from '../src/types/api'

const metadata: AppMetadata = {
  project: 'INDIA TRANSIT CROWD AI',
  tagline: 'PREDICT THE CROWD. PLAN THE JOURNEY.',
  system_id: 'chennai-cmrl-metro', city: 'Chennai', mode: 'METRO', operator: 'CMRL',
  model_scope: 'Verified observed-demand prediction for Chennai Metro (CMRL) station-day entries.',
  timezone: 'Asia/Kolkata', granularity: 'day',
  dataset: {
    title: 'Chennai Metro (CMRL) official passenger-flow station data, archived daily',
    source_url: 'https://github.com/PratyushBalaji/chennai-metro-ridership-tracker',
    granularity: 'one observed calendar day per station-line', measure: 'daily_station_entries',
    timestamp_min: '2026-01-24T00:00:00+05:30', timestamp_max: '2026-10-05T00:00:00+05:30',
    observed_rows: 10965, station_count: 43, station_ids: ['line-01-sal'],
    station_names: { 'line-01-sal': 'Alandur (Blue Line)' },
    source_periods: [{ start: '2026-01-24', end: '2026-10-05', granularity: 'day', basis: 'observed' }],
    explicit_zero_observations: 0, missing_observations_filled: 0, unique_days: 255, is_live: false,
  },
  features: { count: 17, columns: ['entity_id', 'lag_1'] },
  primary_target: 'target_next_day_demand',
  risk_definition: 'Historical-relative daily-entry bands fitted on training-partition targets.',
  default_station_id: 'line-01-sal', default_target_date: '2026-10-06',
  default_target_timestamp: '2026-10-06T00:00:00+05:30', prediction_max_recursive_horizon_days: 60,
  data_freshness_days: 1, genuine_future_prediction_available: true, training_cutoff: '2026-07-28',
  regression_champion: 'xgboost', classification_champion: 'xgboost',
}

const system: TransitSystem = {
  system_id: 'chennai-cmrl-metro', system_name: 'Chennai Metro', city: 'Chennai', state: 'Tamil Nadu', mode: 'METRO', operator: 'CMRL',
  prediction_available: true, prediction_status: 'AVAILABLE', observed_demand_status: 'Verified station-day entries.',
  demand_source_url: 'https://github.com/PratyushBalaji/chennai-metro-ridership-tracker', network_reference_url: null,
  network_reference_kind: 'official passenger-flow API', network_reference_note: 'Not a live feed.', prediction_unavailable_reason: null,
  station_count: 43, data_period: [{ start_inclusive: '2026-01-24', end_inclusive: '2026-10-05' }], granularity: 'day',
}

const stations: StationSummary[] = [
  { station_id: 'line-01-sal', station_name: 'Alandur (Blue Line)', mean_hourly_boardings: 4550.9, latest_observation: '2026-10-05T00:00:00+05:30', observed_hours: 255, system_id: 'chennai-cmrl-metro', granularity: 'day', mean_daily_entries: 4550.9, observed_days: 255 },
]

const futureForecast: PredictionResult = {
  system_id: 'chennai-cmrl-metro', station_id: 'line-01-sal', station_name: 'Alandur (Blue Line)',
  target_timestamp: '2026-10-07T00:00:00+05:30', origin_timestamp: '2026-10-06T00:00:00+05:30',
  granularity: 'day', target_date: '2026-10-07', predicted_demand: 6658.93, predicted_entries: 6658.93,
  unit: 'passengers entering the station on that calendar day (ticket-count derived)', measure: 'daily_station_entries',
  relative_demand_band: 'MODERATE', risk: 'MODERATE', risk_method: 'system_training_fallback',
  risk_thresholds: { q50: 5614.5, q80: 9425.4, q95: 16106.7 }, threshold_sample_count: 6794,
  historical_percentile: 99.4, classification_check: 'MODERATE', classification_agrees: true,
  regression_model: 'xgboost', classification_model: 'xgboost', model_version: '2.1.0-india-daily',
  forecast_horizon_days: 2, is_recursive_forecast: true, is_model_forecast: true,
  forecast_kind: 'post_frontier_projection',
  forecast_note: 'MODEL FORECAST. Day 2026-10-07 has not been observed by the source; 2 day(s) past the data frontier.',
  data_frontier: '2026-10-05T00:00:00+05:30', training_cutoff: '2026-07-28T00:00:00+05:30', data_freshness_days: 1,
  explanation: [{ feature: 'lag_1', label: 'Observed entries 1 day earlier', actual_value: 5000, reference_value: 4600, prediction_with_reference: 6400, delta_entries: 258.9, absolute_delta: 258.9, direction: 'raises the model output versus its training-median reference' }],
  explanation_method: 'One-feature counterfactual against the training-partition median.',
  recommendation: {
    advice_kind: 'day_level_forecast_comparison',
    summary: 'Two neighbouring days were projected with the same model for comparison.',
    caveat: 'Day granularity gives no time-of-day guidance; it cannot say which hour is quieter.',
    alternative_days: [
      { date: '2026-10-06', day_name: 'Tuesday', predicted_entries: 6420.4, relative_demand_band: 'MODERATE', delta_vs_selected: -238.5, forecast_horizon_days: 1 },
      { date: '2026-10-08', day_name: 'Thursday', predicted_entries: 6980.1, relative_demand_band: 'HIGH', delta_vs_selected: 321.2, forecast_horizon_days: 3 },
    ],
  },
}

const replay: PredictionResult = { ...futureForecast, target_date: '2026-06-15', target_timestamp: '2026-06-15T00:00:00+05:30', origin_timestamp: '2026-06-14T00:00:00+05:30', forecast_horizon_days: 0, is_model_forecast: false, is_recursive_forecast: false, forecast_kind: 'historical_replay', forecast_note: 'HISTORICAL REPLAY, not a future forecast: the target day is already observed by the source.' }

function renderPredict(overrides: Partial<Parameters<typeof PredictSection>[0]> = {}) {
  const props = {
    metadata, systems: [system], selectedSystem: system, systemId: system.system_id,
    city: 'Chennai', mode: 'METRO', operator: 'CMRL', granularity: 'day' as const, gap: null,
    onCityChange: vi.fn(), onModeChange: vi.fn(), onOperatorChange: vi.fn(),
    stations, stationId: 'line-01-sal', setStationId: vi.fn(),
    date: '2026-10-07', setDate: vi.fn(), hour: 8, setHour: vi.fn(),
    onSubmit: vi.fn(), loading: false, result: null as PredictionResult | null, error: null as string | null, comparison: null,
    ...overrides,
  }
  render(<PredictSection {...props} />)
  return props
}

describe('day-granularity family presentation', () => {
  it('offers a target day and never a target hour', () => {
    renderPredict()
    expect(screen.getByLabelText('TARGET DATE · IST')).toBeInTheDocument()
    expect(screen.queryByLabelText('TARGET HOUR')).not.toBeInTheDocument()
    expect(screen.getByLabelText('STATION · CMRL')).toBeInTheDocument()
    expect(screen.getByText('NEXT DAY STATION ENTRIES')).toBeInTheDocument()
    expect(screen.getAllByText(/255 observed days/).length).toBeGreaterThan(0)
    expect(screen.getByText('CMRL DAILY SNAPSHOT · IST · NOT LIVE')).toBeInTheDocument()
    expect(screen.getAllByText(/one calendar day per station/).length).toBeGreaterThan(0)
  })

  it('labels a post-frontier answer as a model forecast for an unobserved day', () => {
    renderPredict({ result: futureForecast })
    const card = screen.getByLabelText('Station demand forecast result')
    expect(within(card).getAllByText(/MODEL FORECAST · POST FRONTIER PROJECTION/).length).toBe(1)
    expect(within(card).getByText('PREDICTED STATION ENTRIES')).toBeInTheDocument()
    expect(within(card).getAllByText(/has not been observed by the source yet/).length).toBeGreaterThan(0)
    expect(within(card).getAllByText(/2 days ahead/).length).toBeGreaterThan(0)
    expect(within(card).getByText('FROZEN RISK CUTS · ENTRIES / DAY')).toBeInTheDocument()
    expect(within(card).getByText('+259 entries')).toBeInTheDocument()
    expect(within(card).getAllByText(/System-level training fallback/).length).toBeGreaterThan(0)
    expect(screen.getByText('FORECAST · 2 DAYS AHEAD')).toBeInTheDocument()
  })

  it('does not call a replayed past day a forecast', () => {
    renderPredict({ result: replay })
    const card = screen.getByLabelText('Station demand forecast result')
    expect(within(card).getAllByText(/MODEL OUTPUT · NOT A FORECAST/).length).toBe(1)
    expect(within(card).queryByText(/has not been observed by the source yet/)).not.toBeInTheDocument()
    expect(screen.getByText('DATA-SNAPSHOT NOTE')).toBeInTheDocument()
  })

  it('compares neighbouring days instead of neighbouring hours', () => {
    renderPredict({ result: futureForecast })
    const panel = screen.getByLabelText('Neighbouring forecast days')
    expect(within(panel).getAllByText(/Tuesday/).length).toBeGreaterThan(0)
    expect(within(panel).getAllByText(/6,420/).length).toBeGreaterThan(0)
    expect(within(panel).getByText('6,980')).toBeInTheDocument()
    expect(within(panel).getByText('Day granularity gives no time-of-day guidance; it cannot say which hour is quieter.')).toBeInTheDocument()
    expect(screen.queryByText('NEARBY LOWER-DEMAND WINDOWS')).not.toBeInTheDocument()
  })
})

describe('day-granularity observed history', () => {
  const weekly = {
    system_id: 'chennai-cmrl-metro', station_id: 'line-01-sal', measure: 'daily_station_entries', source: 'observed CMRL days',
    cells: [
      { day_of_week: 0, day_name: 'Monday', mean_observed_daily_entries: 5021.6, median_observed_daily_entries: 5009, observations: 37 },
      { day_of_week: 1, day_name: 'Tuesday', mean_observed_daily_entries: 5089.2, median_observed_daily_entries: 5154, observations: 36 },
      { day_of_week: 2, day_name: 'Wednesday', mean_observed_daily_entries: null, median_observed_daily_entries: null, observations: 0 },
    ],
  }
  const history = {
    system_id: 'chennai-cmrl-metro', station_id: 'line-01-sal', measure: 'daily_station_entries', source: 'observed CMRL days',
    points: [
      { timestamp: '2026-10-04T00:00:00+05:30', observed_boardings: 4800, observation_type: 'observed' as const },
      { timestamp: '2026-10-05T00:00:00+05:30', observed_boardings: 5100, observation_type: 'observed' as const },
    ],
  }
  const preview = {
    kind: 'MODEL_FORECAST_NOT_LIVE_COUNT', statement: 'Every value below is a machine-learned forecast.',
    system_id: 'chennai-cmrl-metro', data_frontier: '2026-10-05', training_cutoff: '2026-07-28',
    days_requested: 2, days_projected: 2, model: 'xgboost',
    days: [
      { date: '2026-10-06', day_name: 'Tuesday', forecast_horizon_days: 1, system_total_predicted_entries: 346732.8, stations_projected: 43 },
      { date: '2026-10-07', day_name: 'Wednesday', forecast_horizon_days: 2, system_total_predicted_entries: 343356.4, stations_projected: 43 },
    ],
  }

  it('shows weekday bars, not an invented hour grid', () => {
    render(<StationDemandSection history={history} heatmap={null} weekly={weekly} granularity="day" preview={preview} stations={stations} stationId="line-01-sal" onPickHour={vi.fn()} available />)
    expect(screen.getByRole('heading', { name: /Observed, by day of week\./ })).toBeInTheDocument()
    expect(screen.queryByRole('grid')).not.toBeInTheDocument()
    expect(screen.getAllByText(/This family has no hour-of-day data/).length).toBeGreaterThan(0)
    expect(screen.getByText('5,022')).toBeInTheDocument()
    expect(screen.getByText('37 days · median 5,009')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.getByText('LATEST 7 OBSERVED DAYS · MEAN')).toBeInTheDocument()
    expect(screen.getByText('NEXT 2 UNOBSERVED DAYS · MODEL FORECAST')).toBeInTheDocument()
    expect(screen.getByText('OBSERVED STATION-DAY ENTRIES')).toBeInTheDocument()
  })

  it('keeps the hourly heatmap path intact for hour families', () => {
    render(<StationDemandSection history={history} heatmap={{ system_id: 'x', station_id: 'y', cells: [], measure: 'hourly', source: 'observed' }} stations={stations} stationId="line-01-sal" onPickHour={vi.fn()} available />)
    expect(screen.getByRole('grid')).toBeInTheDocument()
    expect(screen.getAllByText(/Select a populated cell to set the forecast hour\./).length).toBeGreaterThan(0)
    expect(screen.getByText('LATEST 24 OBSERVATIONS · MEAN')).toBeInTheDocument()
  })
})

describe('api client respects granularity', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function stubFetch(capture: (url: string, init?: RequestInit) => void) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      capture(String(input), init)
      return { ok: true, status: 200, json: async () => ({}) } as Response
    })
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('asks for days on a day family, hours on an hour family, and never a heatmap for days', async () => {
    const urls: string[] = []
    stubFetch((url) => urls.push(url))
    await api.history('chennai-cmrl-metro', 'line-01-sal', { days: 90 })
    await api.history('bengaluru-namma-metro', 'attiguppe')
    await api.weeklyPattern('chennai-cmrl-metro', 'line-01-sal')
    await api.sourceGap('chennai-cmrl-metro')
    await api.futurePreview('chennai-cmrl-metro', 3)
    expect(urls[0]).toContain('/history?system_id=chennai-cmrl-metro&station_id=line-01-sal&days=90')
    expect(urls[1]).toContain('hours=168')
    expect(urls[2]).toContain('/weekly-pattern?')
    expect(urls[3]).toContain('/source-gap?system_id=chennai-cmrl-metro')
    expect(urls[4]).toContain('/future-preview?system_id=chennai-cmrl-metro&days=3')
  })

  it('omits target_hour for a day-family prediction', async () => {
    let body: Record<string, unknown> = {}
    stubFetch((_url, init) => { body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown> })
    await api.predict({ system_id: 'chennai-cmrl-metro', station_id: 'line-01-sal', target_date: '2026-10-07', target_hour: undefined })
    expect(body).not.toHaveProperty('target_hour')
    await api.predict({ system_id: 'bengaluru-namma-metro', station_id: 'attiguppe', target_date: '2025-10-01', target_hour: 8 })
    expect(body.target_hour).toBe(8)
  })

  it('scopes metadata and report requests to the selected family', async () => {
    const urls: string[] = []
    stubFetch((url) => urls.push(url))
    await api.metadata('chennai-cmrl-metro')
    await api.modelPerformance('chennai-cmrl-metro')
    await api.stationComparison('chennai-cmrl-metro', '2026-10-07', null, 'line-01-sal')
    expect(urls[0]).toBe('/api/metadata?system_id=chennai-cmrl-metro')
    expect(urls[1]).toBe('/api/model-performance?system_id=chennai-cmrl-metro')
    expect(urls[2]).not.toContain('target_hour')
  })
})

describe('accuracy reporting for the requested period', () => {
  it('labels a future day as having no actual value and attaches the measured horizon band', () => {
    renderPredict({
      result: {
        ...futureForecast,
        actual_observed_demand: null, observation_status: 'OBSERVED VALUE UNAVAILABLE',
        evaluation_status: 'not_scored_future_period', absolute_error: null, signed_error: null,
        horizon_status: 'within_validated_range',
        horizon_validation: {
          status: 'measured_on_validation_partition', measured_horizon_days: 34, usable_horizon_days: 34,
          evidence_horizon_days: 2, mae_at_horizon: 702.22, p90_absolute_error_at_horizon: 1740.44,
        },
        forecast_interval: { lower: 4918, upper: 8399, level: 'p90_of_absolute_error', method: 'empirical',
                             horizon_days_used: 2, band_basis: 'measured_at_horizon', calibrated: false,
                             is_confidence_interval: false },
      },
    })
    const card = screen.getByLabelText('Station demand forecast result')
    expect(within(card).getByText('OBSERVED VALUE · NOT AVAILABLE')).toBeInTheDocument()
    expect(within(card).getByText('UNAVAILABLE')).toBeInTheDocument()
    expect(within(card).getAllByText(/has not been observed yet, so no actual value exists/).length).toBeGreaterThan(0)
    expect(within(card).getByText('HORIZON ACCURACY · WITHIN VALIDATED RANGE')).toBeInTheDocument()
    expect(within(card).getAllByText(/702/).length).toBeGreaterThan(0)
    expect(within(card).getAllByText(/4,918–8,399/).length).toBeGreaterThan(0)
    expect(within(card).getAllByText(/not a calibrated confidence interval/).length).toBeGreaterThan(0)
    // the forecast itself is still shown, and never presented as a count
    expect(within(card).getByText('PREDICTED STATION ENTRIES')).toBeInTheDocument()
  })

  it('scores a replayed day against the stored observation and states the error', () => {
    renderPredict({
      result: {
        ...replay, actual_observed_demand: 7100, observation_status: 'OBSERVED', observation_rows: 1,
        evaluation_status: 'scored_against_observation', absolute_error: 441.07, signed_error: -441.07,
        absolute_percentage_error: 6.21,
        error_note: 'Actual value is the observation stored by the source for this entity-day.',
      },
    })
    const card = screen.getByLabelText('Station demand forecast result')
    expect(within(card).getByText('OBSERVED VALUE FOR THIS PERIOD')).toBeInTheDocument()
    expect(within(card).getByText('7,100')).toBeInTheDocument()
    expect(within(card).getAllByText(/under-predicted by/).length).toBeGreaterThan(0)
    expect(within(card).getAllByText(/6.2% of the observed/).length).toBeGreaterThan(0)
    expect(within(card).getAllByText(/observation stored by the source/).length).toBeGreaterThan(0)
  })

  it('does not claim accuracy that the artifact has not measured', () => {
    renderPredict({ result: { ...futureForecast, horizon_status: 'unmeasured', horizon_validation: null, forecast_interval: null } })
    const card = screen.getByLabelText('Station demand forecast result')
    expect(within(card).getByText('HORIZON ACCURACY · UNMEASURED')).toBeInTheDocument()
    expect(within(card).getAllByText(/No measured accuracy band is available/).length).toBeGreaterThan(0)
    expect(within(card).getAllByText(/PLAUSIBLE RANGE/).length).toBe(1)
    expect(within(card).getAllByText('—').length).toBeGreaterThan(0)
  })
})

describe('serving mode and supported clock times', () => {
  it('labels a demonstration family and its answer without claiming live ridership', () => {
    renderPredict({
      metadata: {
        ...metadata,
        served_as: 'demo',
        supported_time_note: 'Supported times: 08:00, 09:00, 18:00.',
      },
    })
    expect(screen.getByRole('status').textContent).toContain('SYNTHETIC DEMONSTRATION DATA')
    expect(screen.getByRole('status').textContent).toContain('NOT LIVE PASSENGER RIDERSHIP')
  })

  it('offers only the clock times the family actually observed', () => {
    renderPredict({ granularity: 'hour', metadata: { ...metadata, supported_time_slots: [8, 9, 18] } as typeof metadata })
    const hour = document.getElementById('target-hour') as HTMLSelectElement | null
    expect(hour).not.toBeNull()
    expect(Array.from(hour!.options).map((option) => option.value)).toEqual(['8', '9', '18'])
  })

  it('keeps a full hourly family unrestricted and shows no demo label for verified data', () => {
    renderPredict({ granularity: 'hour', metadata: { ...metadata, served_as: 'production' } as typeof metadata })
    const hour = document.getElementById('target-hour') as HTMLSelectElement
    expect(hour.options.length).toBe(24)
    expect(document.querySelectorAll('.demo-note').length).toBe(0)
  })
})
