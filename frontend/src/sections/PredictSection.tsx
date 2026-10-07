import { AnimatePresence, motion } from 'framer-motion'
import { ArrowDownRight, ArrowRight, CalendarDays, Clock3, MapPin, Sparkles, TrainFront } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import type { AppMetadata, PredictionResult, RouteContext, SourceGapResponse, StationComparison, StationSummary, TransitSystem } from '../types/api'
import { NumberTicker, RiskBadge, SectionHeading } from '../components/ui'


/**
 * A family whose series are identified by several columns gets one dependent select per column, in the
 * order the dataset declared. Every option list is derived from the station attributes the API published,
 * so an unpublished combination - a time slot the source never measured, a destination that is not on that
 * line - cannot even be chosen, and no city's structure is written into this client.
 */
function EntityCascade(props: {
  stations: StationSummary[]
  levels: { column: string; label: string }[]
  disabled: boolean
  onPick: (stationId: string) => void
}) {
  const { stations, levels, disabled, onPick } = props
  const [picks, setPicks] = useState<string[]>([])

  const optionsAt = (depth: number): string[] => {
    const column = levels[depth].column
    const matching = stations.filter((station) => levels.slice(0, depth)
      .every((level, index) => (station.attributes ?? {})[level.column] === picks[index]))
    return [...new Set(matching.map((station) => (station.attributes ?? {})[column]).filter((value): value is string => Boolean(value)))].sort()
  }

  const chosen = levels.length > 0 && picks.length === levels.length && picks.every(Boolean)
    ? stations.find((station) => levels.every((level, index) => (station.attributes ?? {})[level.column] === picks[index]))
    : undefined
  useEffect(() => { onPick(chosen ? chosen.station_id : '') }, [chosen, onPick])

  return (
    <div className="entity-cascade">
      <div className="cascade-levels">
        {levels.map((level, depth) => {
          const options = optionsAt(depth)
          const usable = options.length > 0
          const value = usable && (picks[depth] === undefined || !options.includes(picks[depth])) ? '' : (picks[depth] ?? '')
          return (
            <div className="cascade-level" key={level.column}>
              <span className="field-label">{level.label}{usable ? '' : ' · unavailable'}</span>
              <div className="control-wrap">
                <select value={value} disabled={disabled || !usable} aria-label={level.label}
                  onChange={(event) => setPicks((current) => {
                    const next = current.slice(0, depth)
                    next[depth] = event.target.value
                    return next
                  })}>
                  <option value="" disabled>{options.length ? 'select…' : 'no values'}</option>
                  {options.map((option) => <option value={option} key={option}>{option}</option>)}
                </select>
                <span className="select-caret">⌄</span>
              </div>
            </div>
          )
        })}
      </div>
      <p className="form-hint"><span className="form-hint-dot" /> {chosen
        ? `${chosen.station_name} · ${(chosen.observed_days ?? chosen.observed_hours).toLocaleString()} observed periods recorded`
        : `Choose ${levels.map((level) => level.label.toLowerCase()).join(', then ')} - the options are the values this source actually publishes.`}</p>
    </div>
  )
}

function plusHoursInIst(isoTimestamp: string, hours: number): string {
  const milliseconds = Date.parse(isoTimestamp)
  if (!Number.isFinite(milliseconds)) return isoTimestamp.slice(0, 10)
  // The source and form use IST wall-clock dates; shift to IST before formatting.
  return new Date(milliseconds + hours * 3_600_000 + 330 * 60_000).toISOString().slice(0, 10)
}

function clock(hour: number) {
  return `${String(hour).padStart(2, '0')}:00`
}

function plusDaysInIst(isoTimestamp: string, days: number): string {
  const milliseconds = Date.parse(isoTimestamp)
  if (!Number.isFinite(milliseconds)) return isoTimestamp.slice(0, 10)
  return new Date(milliseconds + days * 86_400_000 + 330 * 60_000).toISOString().slice(0, 10)
}

/** Wording follows the family's granularity so a daily total is never described as an hourly rate. */
function vocabulary(granularity: 'hour' | 'day') {
  return granularity === 'day'
    ? { caption: 'PREDICTED STATION ENTRIES', scope: 'TARGET DAY', unit: 'entries / day', noun: 'entries', horizon: (value: number) => `${value} day${value === 1 ? '' : 's'} ahead`, pattern: 'day of week' }
    : { caption: 'ESTIMATED STATION BOARDINGS', scope: 'TARGET HOUR', unit: 'boardings / hour', noun: 'boardings', horizon: (value: number) => `${value} hour${value === 1 ? '' : 's'} ahead`, pattern: 'hour of day' }
}

function RiskMeter({ percentile }: { percentile: number | null }) {
  const width = percentile === null ? 0 : Math.min(100, Math.max(0, percentile))
  return (
    <div className="percentile-meter" aria-label={percentile === null ? 'Training percentile unavailable' : `Approximately ${percentile}th percentile of training demand`}>
      <div className="meter-track"><span style={{ width: `${width}%` }} /></div>
      <div className="meter-labels"><span>LOWER TRAINING DEMAND</span><span>HIGHER</span></div>
    </div>
  )
}

function ResultCard({ result, granularity }: { result: PredictionResult; granularity: 'hour' | 'day' }) {
  const resultRef = useRef<HTMLElement>(null)
  useEffect(() => {
    const card = resultRef.current
    if (!card || typeof card.scrollIntoView !== 'function' || typeof window.requestAnimationFrame !== 'function') return
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
    const frame = window.requestAnimationFrame(() => card.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' }))
    return () => window.cancelAnimationFrame(frame)
  }, [])
  const words = vocabulary(granularity)
  const riskClass = `result-risk-${result.relative_demand_band.toLowerCase()}`
  const time = granularity === 'day' ? (result.target_date ?? result.target_timestamp.slice(0, 10)) : result.target_timestamp.replace('T', ' ').slice(0, 16)
  const demand = result.predicted_demand ?? result.predicted_boardings ?? result.predicted_entries ?? 0
  const horizon = (granularity === 'day' ? result.forecast_horizon_days : result.forecast_horizon_hours) ?? null
  const isFuture = result.is_model_forecast === true
  const observed = result.actual_observed_demand ?? null
  const signedError = result.signed_error ?? null
  const absolutePercentage = result.absolute_percentage_error ?? null
  const validation = result.horizon_validation ?? null
  const interval = result.forecast_interval ?? null
  const horizonLabel = isFuture
    ? `HORIZON ACCURACY · ${(result.horizon_status ?? 'unmeasured').replaceAll('_', ' ').toUpperCase()}`
    : 'HORIZON ACCURACY · NOT A FUTURE FORECAST'

  const thresholdBasis = result.risk_method === 'entity_training_distribution'
    ? 'Station-specific training percentiles'
    : result.risk_method === 'system_training_fallback'
      ? 'System-level training fallback'
      : 'Global training-only fallback'
  return (
    <motion.article ref={resultRef} className={`result-card ${riskClass}`} initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }} transition={{ duration: 0.45 }} aria-live="polite" aria-label="Station demand forecast result">
      <div className="result-card-top">
        <div>
          <p className="eyebrow"><span className="eyebrow-dot" /> {isFuture ? 'MODEL FORECAST' : 'MODEL OUTPUT · NOT A FORECAST'} · {result.forecast_kind.replaceAll('_', ' ').toUpperCase()}</p>
          <p className="result-route">{result.station_name}<span> / </span>{time} <small>IST</small></p>
        </div>
        <span className="result-model-label">{result.regression_model.replaceAll('_', ' ').toUpperCase()} · REGRESSION</span>
      </div>
      <div className="result-main">
        <div className="result-demand-block">
          <p className="result-caption">{words.caption} <span>· {words.scope}</span></p>
          <div className="result-number"><NumberTicker value={demand} /> <small>{result.unit ? `${words.unit} · ${result.measure.replaceAll('_', ' ')}` : words.unit}</small></div>
          <p className="result-context">{isFuture
            ? `This day has not been observed by the source yet — ${horizon !== null ? words.horizon(horizon) : 'beyond the data frontier'} and produced entirely by the model. It can be checked against real counts once the source publishes the day.`
            : `A model estimate of ${words.noun} at this station for the selected ${granularity === 'day' ? 'day' : 'hour'} — not the number currently onboard a train.`}</p>
        </div>
        <div className="result-risk-block">
          <p className="result-caption">HISTORICAL-RELATIVE DEMAND BAND</p>
          <RiskBadge risk={result.relative_demand_band} className="risk-badge-large" />
          <p className="risk-basis">{thresholdBasis} · {result.threshold_sample_count.toLocaleString()} training targets · band compares {words.noun} with this system's training history</p>
        </div>
      </div>
      <div className="result-detail-grid">
        <div className="result-percentile">
          <div className="result-percentile-header"><span>TRAINING-DISTRIBUTION PERCENTILE</span><strong>{result.historical_percentile === null ? '—' : `≈ ${result.historical_percentile}th`}</strong></div>
          <RiskMeter percentile={result.historical_percentile} />
          <p>Compared with this station's training history where sample support allows; never an occupancy measure.</p>
        </div>
        <div className="result-thresholds">
          <span className="result-caption">FROZEN RISK CUTS · {words.unit.toUpperCase()}</span>
          <div className="threshold-values"><span>Q50 <b>{Math.round(result.risk_thresholds.q50).toLocaleString()}</b></span><span>Q80 <b>{Math.round(result.risk_thresholds.q80).toLocaleString()}</b></span><span>Q95 <b>{Math.round(result.risk_thresholds.q95).toLocaleString()}</b></span></div>
          <p>Fit on chronological training targets only, then frozen.</p>
        </div>
      </div>
      <div className="classification-check">
        <div className="check-icon"><Sparkles size={15} /></div>
        <div><strong>Independent classifier check</strong><span>{result.classification_model.replaceAll('_', ' ')} predicts <b>{result.classification_check}</b>. {result.classification_agrees ? 'It agrees with the percentile-derived band.' : 'It differs from the threshold-derived band; the badge follows the documented percentile rule.'}</span></div>
      </div>
      <div className="forecast-note"><span>{isFuture ? `FORECAST · ${horizon !== null ? words.horizon(horizon).toUpperCase() : 'BEYOND DATA FRONTIER'}` : 'DATA-SNAPSHOT NOTE'}</span><p>{result.forecast_note}</p>
        <small>{`Regression ${result.regression_model} · classifier check ${result.classification_model}${result.model_version ? ` · ${result.model_version}` : ''} · training cut-off ${(result.training_cutoff ?? '').slice(0, 10) || 'unknown'} · last observed ${granularity === 'day' ? 'day' : 'timestamp'} ${(result.data_frontier ?? '').slice(0, 10) || 'unknown'}`}</small>
      </div>
      <div className="result-detail-grid">
        <div className="result-percentile">
          <div className="result-percentile-header">
            <span>{result.observation_status === 'OBSERVED' ? 'OBSERVED VALUE FOR THIS PERIOD' : 'OBSERVED VALUE · NOT AVAILABLE'}</span>
            <strong>{observed === null ? 'UNAVAILABLE' : Math.round(observed).toLocaleString()}</strong>
          </div>
          {observed === null ? (
            <p>
              {isFuture
                ? `This ${granularity === 'day' ? 'day' : 'hour'} has not been observed yet, so no actual value exists to compare with. The answer above is a model output, never a count.`
                : 'The source published no value for this period. Nothing has been estimated, interpolated or replaced with zero.'}
            </p>
          ) : (
            <p>
              Model {signedError !== null && signedError < 0 ? 'under' : 'over'}-predicted by{' '}
              <b>{Math.round(Math.abs(signedError ?? 0)).toLocaleString()}</b> {words.noun} ({absolutePercentage?.toFixed(1) ?? '—'}% of the observed{' '}
              {granularity === 'day' ? 'day' : 'hour'}). {result.error_note}
            </p>
          )}
        </div>
        <div className="result-thresholds">
          <span className="result-caption">
            {horizonLabel}
          </span>
          <div className="threshold-values">
            <span>MEASURED MAE <b>{validation?.mae_at_horizon != null ? Math.round(validation.mae_at_horizon).toLocaleString() : '—'}</b></span>
            <span>PLAUSIBLE RANGE <b>{interval ? `${Math.round(interval.lower).toLocaleString()}–${Math.round(interval.upper).toLocaleString()}` : '—'}</b></span>
            <span>VALIDATED TO <b>{validation?.measured_horizon_days ? `${validation.measured_horizon_days} ${words.noun === 'entries' ? 'days' : 'hours'}` : '—'}</b></span>
          </div>
          <p>
            {interval
              ? `${interval.level} of absolute error at horizon day ${interval.horizon_days_used}${interval.band_basis === 'worst_measured_horizon' ? ' (widest measured band, because this horizon was not measured)' : ''} · empirical band, not a calibrated confidence interval`
              : (validation?.detail ?? 'No measured accuracy band is available for this artifact, so none is claimed.')}
          </p>
        </div>
      </div>
      {result.disclosure ? <p className="demo-note">{result.disclosure}</p> : null}
      <section className="result-explain" aria-labelledby="why-this-heading">
        <div className="result-section-heading"><div><p className="eyebrow"><span className="eyebrow-dot" /> MODEL SENSITIVITY</p><h3>Why this estimate?</h3></div><span className="explain-legend">REFERENCE = TRAIN MEDIAN</span></div>
        <p className="explain-disclaimer">Each driver below shows how the saved model output changes when one input is replaced with its training median. This is sensitivity, not causal attribution.</p>
        {result.explanation.length === 0 ? <p className="data-empty-inline">No local sensitivity values are available for this request.</p> : (
          <div className="driver-list">
            {result.explanation.map((driver) => {
              const range = Math.max(...result.explanation.map((item) => item.absolute_delta), 1)
              const width = Math.max(3, driver.absolute_delta / range * 100)
              return (
                <div className="driver-row" key={driver.feature}>
                  <div className="driver-label"><span>{driver.label}</span><strong>{(() => { const delta = driver.delta_entries ?? driver.delta_boardings ?? 0; return `${delta > 0 ? '+' : ''}${Math.round(delta).toLocaleString()} ${words.noun}` })()}</strong></div>
                  <div className="driver-track"><span style={{ width: `${width}%` }} /></div>
                </div>
              )
            })}
          </div>
        )}
        <p className="explain-footnote">{result.explanation_method}</p>
      </section>
      {result.recommendation.alternative_days && result.recommendation.alternative_days.length > 0 ? (
        <section className="recommendation-panel" aria-label="Neighbouring forecast days">
          <div className="recommendation-icon"><ArrowDownRight size={19} /></div>
          <div className="recommendation-copy">
            <p className="eyebrow">NEIGHBOURING FORECAST DAYS</p>
            <h3>{result.recommendation.alternative_days.reduce((quiet, item) => item.predicted_entries < quiet.predicted_entries ? item : quiet, result.recommendation.alternative_days[0]).day_name} <span>→</span> {Math.round(Math.min(...result.recommendation.alternative_days.map((item) => item.predicted_entries))).toLocaleString()} {words.noun}</h3>
            <ul className="alternative-day-list">
              {result.recommendation.alternative_days.map((item) => (
                <li key={item.date}><span>{item.day_name} · {item.date}</span><b>{Math.round(item.predicted_entries).toLocaleString()}</b><em>{item.relative_demand_band}</em><small>{item.delta_vs_selected > 0 ? '+' : ''}{Math.round(item.delta_vs_selected).toLocaleString()} vs selected day</small></li>
              ))}
            </ul>
            {result.recommendation.summary && <p>{result.recommendation.summary}</p>}
            {result.recommendation.caveat && <small>{result.recommendation.caveat}</small>}
          </div>
        </section>
      ) : (
        <section className="recommendation-panel" aria-label="Nearby lower-demand recommendation">
          <div className="recommendation-icon"><ArrowDownRight size={19} /></div>
          <div className="recommendation-copy">
            <p className="eyebrow">NEARBY LOWER-DEMAND WINDOWS</p>
            {result.recommendation.status === 'available' && result.recommendation.recommended ? (
              <><h3>{clock(result.recommendation.recommended.hour)} <span>→</span> {clock((result.recommendation.recommended.hour + 1) % 24)}</h3>
                <p>Lowest model-predicted nearby window: <b>{Math.round(result.recommendation.recommended.predicted_boardings).toLocaleString()} {words.noun}</b> · {result.recommendation.recommended.relative_demand_band} relative band.</p></>
            ) : <><h3>{result.recommendation.status === 'no_lower_demand_window' ? 'No lower window found.' : 'Not enough history.'}</h3><p>{result.recommendation.message ?? `This family cannot rank ${words.pattern} alternatives.`}</p></>}
            <small>{result.recommendation.basis}</small>
          </div>
          {result.recommendation.status === 'available' && result.recommendation.recommended && (
            <div className="recommendation-delta"><span>MODELLED CHANGE</span><b>{result.recommendation.reduction_percent === null || result.recommendation.reduction_percent === undefined ? '—' : `−${result.recommendation.reduction_percent.toFixed(0)}%`}</b></div>
          )}
        </section>
      )}
    </motion.article>
  )
}

function UnavailablePanel({ system }: { system: TransitSystem }) {
  return (
    <div className="unsupported-panel" role="status">
      <span className="unsupported-icon"><TrainFront size={18} /></span>
      <p className="eyebrow">NETWORK REFERENCE ONLY · NO FORECAST</p>
      <h3>{system.city} · {system.mode} · {system.operator}</h3>
      <p>{system.prediction_unavailable_reason ?? 'Verified observed passenger-demand data and a trained model are not available for this system.'}</p>
      <div className="unsupported-source"><span>AVAILABLE DATA</span><strong>{system.network_reference_kind}</strong><small>{system.network_reference_note}</small></div>
      {system.network_reference_url && <a className="source-link" href={system.network_reference_url} target="_blank" rel="noreferrer">Open network reference <MapPin size={13} /></a>}
    </div>
  )
}

export function PredictSection({
  metadata, systems, selectedSystem, systemId, city, mode, operator, granularity = 'hour', gap = null,
  onCityChange, onModeChange, onOperatorChange, stations, stationId, setStationId,
  date, setDate, hour, setHour, onSubmit, loading, result, error, comparison,
}: {
  metadata: AppMetadata
  systems: TransitSystem[]
  selectedSystem: TransitSystem | null
  systemId: string
  city: string
  mode: string
  operator: string
  granularity?: 'hour' | 'day'
  gap?: SourceGapResponse | null
  onCityChange: (city: string) => void
  onModeChange: (mode: string) => void
  onOperatorChange: (operator: string) => void
  stations: StationSummary[]
  stationId: string
  setStationId: (stationId: string) => void
  date: string
  setDate: (date: string) => void
  hour: number
  setHour: (hour: number) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  loading: boolean
  result: PredictionResult | null
  error: string | null
  comparison: StationComparison | null
}) {
  const cities = Array.from(new Set(systems.map((item) => item.city))).sort()
  const modes = Array.from(new Set(systems.filter((item) => item.city === city).map((item) => item.mode))).sort()
  const operators = Array.from(new Set(systems.filter((item) => item.city === city && item.mode === mode).map((item) => item.operator))).sort()
  const isAvailable = Boolean(selectedSystem?.prediction_available && selectedSystem.system_id === metadata.system_id)
  // A family may be served on data it is honest about not being measurement. The flag comes from the
  // loaded family, never from a system name, so any future demo family is labelled the same way.
  const demoFamily = metadata.served_as === 'demo'
  const hierarchyLevels = useMemo(() => metadata.entity_hierarchy ?? [], [metadata.entity_hierarchy])
  const isDemonstration = metadata.data_class === 'synthetic_development' || metadata.served_as === 'demo'
  // The series label has to say what the file is. Calling modelled synthetic data "observed" is the exact
  // overclaim this project exists to avoid, so the wording switches on the family's own declared class.
  const dataClassLabel = isDemonstration ? 'SYNTHETIC DEMONSTRATION DATA' : 'OBSERVED DATA'
  // TOWARDS is journey context for families whose source publishes no destination-specific counts: it is
  // derived from the corridor's own station ordering, shown so the choice reads like a real trip, and never
  // sent as if it were a measured direction.
  const routeContext: RouteContext | null = metadata.route_context ?? null
  const [towards, setTowards] = useState('')
  const towardsOptions = stationId && routeContext ? (routeContext.towards_for_entity?.[stationId] ?? []) : []
  useEffect(() => { setTowards((current) => (towardsOptions.includes(current) ? current : '')) }, [stationId, towardsOptions.join('|')])
  const declaredSlots = metadata.supported_time_slots ?? null
  const slotLimited = Boolean(declaredSlots && declaredSlots.length > 0 && declaredSlots.length < 24)
  const hourOptions = slotLimited ? (declaredSlots as number[]) : Array.from({ length: 24 }, (_, index) => index)
  const words = vocabulary(granularity)
  const minDate = metadata.dataset.timestamp_min.slice(0, 10)
  const maxDate = granularity === 'day'
    ? plusDaysInIst(metadata.dataset.timestamp_max, metadata.prediction_max_recursive_horizon_days ?? 60)
    : plusHoursInIst(metadata.dataset.timestamp_max, metadata.prediction_max_recursive_horizon_hours ?? 336)
  const horizonLimit = granularity === 'day' ? (metadata.prediction_max_recursive_horizon_days ?? 60) : (metadata.prediction_max_recursive_horizon_hours ?? 336)
  return (
    <section id="predict" className="predict-section section-anchor section-pad">
      <div className="section-shell">
        <div className="predict-intro">
          <SectionHeading eyebrow="THE PREDICTIVE ENGINE" title={<>The station-<span className="headline-unit">{granularity === 'day' ? 'day' : 'hour'}</span><br /><em>signal, made visible.</em></>} copy="Select a registered transit model family and forecast only within the demand history and horizon that its data and artifacts support. Synthetic demonstration families are labelled clearly." />
          <div className="engine-status"><span className="status-ring" /><span>{isAvailable ? 'MODEL READY' : 'NO MODEL'}</span><small>{isAvailable ? `${metadata.operator} ${granularity === 'day' ? 'DAILY' : 'HOURLY'} SNAPSHOT · IST · NOT LIVE${demoFamily ? ' · SYNTHETIC DEMO' : ''}${gap?.days_behind_today !== null && gap?.days_behind_today !== undefined ? ` · ${gap.days_behind_today}D BEHIND TODAY` : ''}` : 'NETWORK DISCOVERY ONLY'}</small></div>
        </div>
        {demoFamily ? (
          <p className="demo-note" role="status">
            <strong>SYNTHETIC DEMONSTRATION DATA.</strong> This family is forecast from modelled data supplied to
            exercise the pipeline. <strong>NOT LIVE PASSENGER RIDERSHIP</strong> — not an operator measurement, not a
            crowd or occupancy statement, and not a real-world accuracy claim.{' '}
            {metadata.supported_time_note ?? ''}
          </p>
        ) : null}
        <div className="predict-layout">
          <form className="prediction-form" onSubmit={onSubmit} aria-label="India transit system demand prediction form">
            <div className="form-header"><span>01 / DISCOVER A SYSTEM</span><span>INDIA · CITY / MODE / OPERATOR</span></div>
            <label className="field-label" htmlFor="city-select">CITY</label>
            <div className="control-wrap"><MapPin size={16} aria-hidden="true" /><select id="city-select" value={city} onChange={(event) => onCityChange(event.target.value)}>
              {cities.map((item) => <option value={item} key={item}>{item}</option>)}
            </select><span className="select-caret">⌄</span></div>
            <div className="form-split system-field-split">
              <div><label className="field-label" htmlFor="mode-select">MODE</label><div className="control-wrap"><TrainFront size={16} aria-hidden="true" /><select id="mode-select" value={mode} onChange={(event) => onModeChange(event.target.value)}>
                {modes.map((item) => <option value={item} key={item}>{item}</option>)}
              </select><span className="select-caret">⌄</span></div></div>
              <div><label className="field-label" htmlFor="operator-select">OPERATOR</label><div className="control-wrap"><select id="operator-select" value={operator} onChange={(event) => onOperatorChange(event.target.value)}>
                {operators.map((item) => <option value={item} key={item}>{item}</option>)}
              </select><span className="select-caret">⌄</span></div></div>
            </div>
            {selectedSystem && !isAvailable ? <UnavailablePanel system={selectedSystem} /> : (
              <>
                {hierarchyLevels.length > 0 ? (
                  <>
                    <label className="field-label">SERIES · {metadata.operator} {dataClassLabel}</label>
                    <EntityCascade key={metadata.system_id} stations={stations} levels={hierarchyLevels}
                      disabled={!isAvailable || stations.length === 0} onPick={setStationId} />
                    {towardsOptions.length > 0 && (
                      <div className="towards-row">
                        <div className="cascade-level">
                          <span className="field-label">TOWARDS · ROUTE CONTEXT</span>
                          <div className="control-wrap">
                            <MapPin size={16} aria-hidden="true" />
                            <select value={towards} disabled={!isAvailable} aria-label="Towards"
                              onChange={(event) => setTowards(event.target.value)}>
                              {towardsOptions.map((option) => <option value={option} key={option}>{option}</option>)}
                            </select>
                            <span className="select-caret">⌄</span>
                          </div>
                        </div>
                        <p className="towards-note">{routeContext?.towards_kind ??
                          'route context only - the forecast is the corridor and station series this file measures'}.</p>
                      </div>
                    )}
                  </>
                ) : (<>
                <label className="field-label" htmlFor="station-select">STATION · {metadata.operator} {dataClassLabel}</label>
                <div className="control-wrap"><TrainFront size={16} aria-hidden="true" /><select id="station-select" name="station_id" value={stationId} onChange={(event) => setStationId(event.target.value)} required disabled={!isAvailable || stations.length === 0}>
                  {stations.map((item) => <option value={item.station_id} key={item.station_id}>
                    {item.station_name} · {(granularity === 'day' ? item.observed_days ?? item.observed_hours : item.observed_hours).toLocaleString()} observed {granularity === 'day' ? 'days' : 'hours'}
                  </option>)}
                </select><span className="select-caret">⌄</span></div>
                </>)}
                <div className={granularity === 'day' ? 'form-split single-field-split' : 'form-split'}>
                  <div><label className="field-label" htmlFor="target-date">TARGET DATE · IST</label><div className="control-wrap"><CalendarDays size={16} aria-hidden="true" /><input id="target-date" name="date" type="date" value={date} min={minDate} max={maxDate} onChange={(event) => setDate(event.target.value)} required disabled={!isAvailable} /></div></div>
                  {granularity === 'hour' && (
                    <div><label className="field-label" htmlFor="target-hour">TARGET HOUR</label><div className="control-wrap"><Clock3 size={16} aria-hidden="true" /><select id="target-hour" name="hour" value={hour} onChange={(event) => setHour(Number(event.target.value))} required disabled={!isAvailable}>
                      {hourOptions.map((index) => <option key={index} value={index}>{clock(index)} – {clock((index + 1) % 24)}</option>)}
                    </select><span className="select-caret">⌄</span></div></div>
                  )}
                </div>
                <p className="form-hint"><span className="form-hint-dot" /> {metadata.dataset.title.slice(0, 46)} · observed through {metadata.dataset.timestamp_max.slice(0, 10)} · {granularity === 'day' ? 'one calendar day per station' : 'one hour per station'} · projections to {horizonLimit} {granularity === 'day' ? 'days' : 'hours'} beyond it · no live data.</p>
                {gap && (
                  <p className="form-hint form-hint-future"><span className="form-hint-dot" /> {gap.days_behind_today === 0
                    ? 'The archive is current to today; any later date is a model forecast.'
                    : `The source publishes up to ${gap.data_frontier ?? '—'} (${gap.days_behind_today} day${gap.days_behind_today === 1 ? '' : 's'} behind today). A date after that is a forecast, not a reading.`}
                  </p>
                )}
                <button className="predict-button" type="submit" disabled={loading || !isAvailable || !stationId || !date}>
                  <span>{loading ? 'ANALYSING STATION DEMAND' : 'PREDICT STATION DEMAND'}</span>
                  {loading ? <span className="button-spinner" aria-hidden="true" /> : <ArrowRight size={17} aria-hidden="true" />}
                </button>
                <p className="form-privacy">Observed station boardings only. No live train positions, occupancy, capacity or confidence score.</p>
              </>
            )}
          </form>
          <div className="result-stage" aria-live="polite">
            <div className="result-stage-top"><span>02 / MODEL OUTPUT</span><span className="stage-horizon">{isAvailable ? `NEXT ${granularity === 'day' ? 'DAY' : 'HOUR'} STATION ${granularity === 'day' ? 'ENTRIES' : 'BOARDINGS'}` : 'PREDICTION UNAVAILABLE'}</span></div>
            <AnimatePresence mode="wait">
              {!isAvailable && selectedSystem ? (
                <motion.div className="unsupported-stage" key={`unsupported-${systemId}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} role="status">
                  <div className="unsupported-stage-mark"><span>DATA</span><span>≠</span><span>DEMAND</span></div>
                  <p className="eyebrow">SYSTEM STATUS · NO FORECAST</p>
                  <h3>Demand data<br /><em>not available.</em></h3>
                  <p>{selectedSystem.prediction_unavailable_reason}</p>
                  <span className="empty-rule" />
                </motion.div>
              ) : loading ? (
                <motion.div className="loading-panel" key="loading" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} role="status">
                  <div className="loading-orbit"><span /><span /><span /></div>
                  <p className="eyebrow">ANALYSING HISTORICAL SIGNAL</p><h3>Building the station-{granularity} view.</h3>
                  <p>Using observed station {words.noun} strictly before the selected target.</p>
                </motion.div>
              ) : error ? (
                <motion.div className="error-panel" key="error" initial={{ opacity: 0 }} animate={{ opacity: 1 }} role="alert">
                  <span className="error-mark">!</span><p className="eyebrow">FORECAST UNAVAILABLE</p><h3>We could not generate this view.</h3><p>{error}</p><button type="button" className="retry-button" onClick={() => document.getElementById('target-date')?.focus()}>Review your inputs <ArrowRight size={14} /></button>
                </motion.div>
              ) : result ? <ResultCard key={`${result.station_id}-${result.target_timestamp}`} result={result} granularity={granularity} /> : (
                <motion.div className="empty-result" key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                  <div className="empty-result-mark"><span>01</span><span>→</span><span>02</span></div>
                  <p className="eyebrow">{metadata.city.toUpperCase()} · {metadata.mode} · {metadata.operator.toUpperCase()}</p><h3>Observe first.<br /><em>Estimate next.</em></h3>
                  <p>Select a station and target {granularity}. {metadata.model_scope} A date past the source frontier is returned as a labelled model forecast; a date it has already observed is returned as a historical replay.</p>
                  <span className="empty-rule" />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
        {result && comparison && (
          <div className="predict-comparison-note">
            <span className="eyebrow"><span className="eyebrow-dot" /> STATION CONTEXT</span>
            <p>{comparison.stations.length} station forecasts are available for this target{comparison.is_model_forecast === true ? ' — none of them are observations' : ''}. Station-relative percentiles appear in the <a href="#stations">station comparison</a>.</p>
          </div>
        )}
      </div>
    </section>
  )
}
