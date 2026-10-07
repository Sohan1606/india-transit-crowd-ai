import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, expect, it } from 'vitest'
import { Navigation } from '../src/components/Navigation'
import { PredictSection } from '../src/sections/PredictSection'
import { StationDemandSection } from '../src/sections/DemandSection'
import type { AppMetadata, PredictionResult, StationSummary, TransitSystem } from '../src/types/api'

const metadata: AppMetadata = {
  project: 'INDIA TRANSIT CROWD AI',
  tagline: 'PREDICT THE CROWD. PLAN THE JOURNEY.',
  system_id: 'bengaluru-namma-metro', city: 'Bengaluru', mode: 'METRO', operator: 'BMRCL',
  model_scope: 'Historical BMRCL station-hour boardings only.', timezone: 'Asia/Kolkata',
  dataset: {
    title: 'BMRCL/Namma Metro station-hour ridership', source_url: 'https://github.com/Vonter/bmrcl-ridership-hourly',
    source_data_url: 'https://example.org/pinned.csv.zip', source_commit: '6c44579b5ff3428a88bddc44baf84e436a940612',
    source_sha256: 'sha256', license: 'ODbL-1.0', license_url: 'https://opendatacommons.org/licenses/odbl/1-0/',
    attribution: 'BMRCL; compiled by Vonter.', granularity: 'one observed station-hour', measure: 'boardings',
    timestamp_min: '2025-08-01T00:00:00+05:30', timestamp_max: '2025-09-30T23:00:00+05:30',
    observed_rows: 92280, station_count: 83, station_ids: ['central', 'majestic'],
    station_names: { central: 'Central', majestic: 'Majestic' },
    source_periods: [{ start_inclusive: '2025-08-01', end_inclusive: '2025-08-18' }, { start_inclusive: '2025-09-01', end_inclusive: '2025-09-30' }],
    explicit_zero_observations: 18200, missing_observations_filled: 0, source_metadata: {}, is_live: false,
  },
  features: { count: 18, columns: ['entity_id', 'hour'] },
  primary_target: 'target_next_hour_demand',
  risk_definition: 'Historical-relative demand bands, not occupancy.',
  default_station_id: 'central', default_target_date: '2025-10-01', default_target_hour: 0,
  default_target_timestamp: '2025-10-01T00:00:00+05:30', prediction_max_recursive_horizon_hours: 336,
  regression_champion: 'xgboost', classification_champion: 'random_forest',
}

const systems: TransitSystem[] = [
  {
    system_id: 'bengaluru-namma-metro', system_name: 'Namma Metro', city: 'Bengaluru', state: 'Karnataka', mode: 'METRO', operator: 'BMRCL',
    prediction_available: true, prediction_status: 'AVAILABLE', observed_demand_status: 'Verified station-hour boardings.',
    demand_source_url: 'https://github.com/Vonter/bmrcl-ridership-hourly', network_reference_url: 'https://github.com/Vonter/bmrcl-ridership-hourly',
    network_reference_kind: 'observed station-hour source', network_reference_note: 'No live data.', prediction_unavailable_reason: null,
    station_count: 83, data_period: [{ start_inclusive: '2025-08-01', end_inclusive: '2025-09-30' }],
  },
  {
    system_id: 'delhi-dmrc-metro', system_name: 'Delhi Metro', city: 'Delhi', state: 'Delhi', mode: 'METRO', operator: 'DMRC',
    prediction_available: false, prediction_status: 'UNAVAILABLE_NO_VERIFIED_DEMAND_MODEL', observed_demand_status: 'No station-hour demand file.',
    demand_source_url: 'https://otd.delhi.gov.in/data/staticDMRC/', network_reference_url: 'https://otd.delhi.gov.in/data/staticDMRC/',
    network_reference_kind: 'static GTFS schedule reference', network_reference_note: 'GTFS is schedule data only.',
    prediction_unavailable_reason: 'No verified observed passenger-demand history and trained DMRC model are available. Static DMRC GTFS is not demand.',
    station_count: null, data_period: [],
  },
]

const stations: StationSummary[] = [
  { station_id: 'central', station_name: 'Central', mean_hourly_boardings: 321, latest_observation: '2025-09-30T23:00:00+05:30', observed_hours: 1152, system_id: 'bengaluru-namma-metro' },
  { station_id: 'majestic', station_name: 'Majestic', mean_hourly_boardings: 250, latest_observation: '2025-09-30T23:00:00+05:30', observed_hours: 1152, system_id: 'bengaluru-namma-metro' },
]

const prediction: PredictionResult = {
  system_id: 'bengaluru-namma-metro', station_id: 'central', station_name: 'Central',
  target_timestamp: '2025-10-01T00:00:00+05:30', origin_timestamp: '2025-09-30T23:00:00+05:30',
  predicted_boardings: 412, measure: 'hourly_station_boardings', relative_demand_band: 'HIGH', risk: 'HIGH',
  risk_method: 'entity_training_distribution', risk_thresholds: { q50: 260, q80: 420, q95: 700 }, threshold_sample_count: 530,
  historical_percentile: 79.8, classification_check: 'HIGH', classification_agrees: true,
  regression_model: 'xgboost', classification_model: 'random_forest', forecast_horizon_hours: 1,
  is_recursive_forecast: true, forecast_kind: 'post_snapshot_projection',
  forecast_note: 'Projection from the latest published BMRCL observation; the archive is historical, not a live feed.',
  explanation: [{ feature: 'lag_1', label: 'Previous-hour station boardings', actual_value: 400, reference_value: 300, prediction_with_reference: 340, delta_boardings: 72, absolute_delta: 72, direction: 'raises the model output' }],
  explanation_method: 'Model-backed sensitivity, not SHAP.',
  recommendation: {
    status: 'available', message: 'Lower nearby forecast.', basis: 'Persisted model forecasts.',
    recommended: { timestamp: '2025-10-01T02:00:00+05:30', hour: 2, predicted_boardings: 300, relative_demand_band: 'MODERATE', historical_percentile: 55, offset_hours: 2 },
    selected_predicted_boardings: 412, reduction_percent: 27.2, candidates: [],
  },
}

function renderPredict(overrides: Partial<React.ComponentProps<typeof PredictSection>> = {}) {
  const onSubmit = vi.fn((event: React.FormEvent<HTMLFormElement>) => event.preventDefault())
  const props = {
    metadata, systems, selectedSystem: systems[0], systemId: 'bengaluru-namma-metro',
    city: 'Bengaluru', mode: 'METRO', operator: 'BMRCL',
    onCityChange: vi.fn(), onModeChange: vi.fn(), onOperatorChange: vi.fn(),
    stations, stationId: 'central', setStationId: vi.fn(), date: '2025-10-01', setDate: vi.fn(),
    hour: 8, setHour: vi.fn(), onSubmit, loading: false, result: null, error: null, comparison: null,
    ...overrides,
  }
  return { ...render(<PredictSection {...props} />), props }
}

describe('system discovery and prediction workflow', () => {
  it('renders accessible India navigation and toggles the mobile menu', async () => {
    const user = userEvent.setup()
    render(<><section id="home" /><section id="systems" /><section id="predict" /><Navigation /></>)
    const nav = screen.getByRole('navigation', { name: 'Primary navigation' })
    expect(within(nav).getByRole('link', { name: 'Systems' })).toHaveAttribute('href', '#systems')
    const toggle = screen.getByRole('button', { name: 'Open navigation menu' })
    await user.click(toggle)
    expect(screen.getByRole('button', { name: 'Close navigation menu' })).toHaveAttribute('aria-expanded', 'true')
    expect(nav).toHaveClass('is-open')
  })

  it('submits a selected city, mode, operator, station, date and target hour', async () => {
    const user = userEvent.setup()
    const { props } = renderPredict()
    await user.selectOptions(screen.getByLabelText('STATION · BMRCL'), 'majestic')
    fireEvent.change(screen.getByLabelText('TARGET DATE · IST'), { target: { value: '2025-09-03' } })
    await user.selectOptions(screen.getByLabelText('TARGET HOUR'), '11')
    await user.click(screen.getByRole('button', { name: 'PREDICT STATION DEMAND' }))
    expect(props.setStationId).toHaveBeenCalledWith('majestic')
    expect(props.setDate).toHaveBeenCalledWith('2025-09-03')
    expect(props.setHour).toHaveBeenCalledWith(11)
    expect(props.onSubmit).toHaveBeenCalledTimes(1)
  })

  it('clearly shows unsupported systems as unavailable rather than fabricating a forecast', () => {
    renderPredict({ selectedSystem: systems[1], systemId: systems[1].system_id, city: 'Delhi', operator: 'DMRC' })
    expect(screen.getByText('PREDICTION UNAVAILABLE')).toBeInTheDocument()
    expect(screen.getAllByText(/Static DMRC GTFS is not demand/).length).toBeGreaterThan(0)
    expect(screen.queryByLabelText('STATION · BMRCL OBSERVED DATA')).not.toBeInTheDocument()
  })

  it('shows the real pending state and disables duplicate requests', () => {
    renderPredict({ loading: true })
    expect(screen.getByRole('status')).toHaveTextContent('ANALYSING HISTORICAL SIGNAL')
    expect(screen.getByRole('button', { name: /ANALYSING STATION DEMAND/i })).toBeDisabled()
  })

  it('renders API errors without retaining a stale estimate', () => {
    renderPredict({ error: 'Insufficient contiguous 168-hour history for this station.' })
    expect(screen.getByRole('alert')).toHaveTextContent('Insufficient contiguous 168-hour history')
    expect(screen.getByText('FORECAST UNAVAILABLE')).toBeInTheDocument()
  })

  it('renders returned boardings, historical risk, model sensitivity and recommendation', () => {
    renderPredict({ result: prediction })
    expect(screen.getByLabelText('Station demand forecast result')).toBeInTheDocument()
    expect(screen.getByText('HISTORICAL-RELATIVE DEMAND BAND')).toBeInTheDocument()
    expect(screen.getByText('HIGH', { selector: '.risk-badge' })).toBeInTheDocument()
    expect(screen.getByText('Previous-hour station boardings')).toBeInTheDocument()
    expect(within(screen.getByLabelText('Nearby lower-demand recommendation')).getByRole('heading', { name: /02:00/ })).toBeInTheDocument()
    expect(screen.getByText(/Projection from the latest published BMRCL observation/)).toBeInTheDocument()
  })
})

describe('observed station data visualizations', () => {
  it('renders source observations and an exact-value weekday/hour profile', async () => {
    const user = userEvent.setup()
    const onPickHour = vi.fn()
    const points = Array.from({ length: 8 }, (_, index) => ({
      timestamp: `2025-09-01T${String(index).padStart(2, '0')}:00:00+05:30`, observed_boardings: 100 + index * 10, observation_type: 'observed' as const,
    }))
    const cells = Array.from({ length: 168 }, (_, index) => {
      const day = Math.floor(index / 24)
      const hour = index % 24
      return { day_of_week: day, day_name: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][day], hour, mean_observed_boardings: 100 + hour, observations: 12 }
    })
    render(<StationDemandSection
      history={{ system_id: 'bengaluru-namma-metro', station_id: 'central', points, measure: 'hourly_station_boardings', source: 'observed BMRCL source' }}
      heatmap={{ system_id: 'bengaluru-namma-metro', station_id: 'central', cells, measure: 'hourly_station_boardings', source: 'observed station-hour values' }}
      stations={stations} stationId="central" onPickHour={onPickHour} available
    />)
    expect(screen.getByRole('img', { name: /Central observed hourly boardings/ })).toBeInTheDocument()
    const cell = screen.getByRole('button', { name: 'Monday 05:00 · mean 105 boardings/hour · 12 observations' })
    expect(cell).toBeInTheDocument()
    await user.click(cell)
    expect(onPickHour).toHaveBeenCalledWith(5)
    expect(screen.getByText('OBSERVED STATION-HOUR BOARDINGS')).toBeInTheDocument()
  })

  it('does not draw a blank source cell as zero demand', () => {
    const cells = Array.from({ length: 168 }, (_, index) => ({
      day_of_week: Math.floor(index / 24), day_name: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][Math.floor(index / 24)], hour: index % 24,
      mean_observed_boardings: index === 0 ? null : 100, observations: index === 0 ? 0 : 3,
    }))
    render(<StationDemandSection history={null} heatmap={{ system_id: 'bengaluru-namma-metro', station_id: 'central', cells, measure: 'hourly_station_boardings', source: 'observed' }} stations={stations} stationId="central" onPickHour={vi.fn()} available />)
    const blank = screen.getByRole('button', { name: 'Monday 00:00 · no observations' })
    expect(blank).toBeDisabled()
    expect(blank).toHaveClass('heatmap-missing')
  })
})
