import { AnimatePresence, motion } from 'framer-motion'
import { ArrowDownRight, ArrowRight, CalendarDays, Clock3, MapPin, Sparkles, TrainFront } from 'lucide-react'
import { useEffect, useRef, type FormEvent } from 'react'
import type { AppMetadata, PredictionResult, StationComparison, StationSummary, TransitSystem } from '../types/api'
import { NumberTicker, RiskBadge, SectionHeading } from '../components/ui'

function plusHoursInIst(isoTimestamp: string, hours: number): string {
  const milliseconds = Date.parse(isoTimestamp)
  if (!Number.isFinite(milliseconds)) return isoTimestamp.slice(0, 10)
  // The source and form use IST wall-clock dates; shift to IST before formatting.
  return new Date(milliseconds + hours * 3_600_000 + 330 * 60_000).toISOString().slice(0, 10)
}

function clock(hour: number) {
  return `${String(hour).padStart(2, '0')}:00`
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

function ResultCard({ result }: { result: PredictionResult }) {
  const resultRef = useRef<HTMLElement>(null)
  useEffect(() => {
    const card = resultRef.current
    if (!card || typeof card.scrollIntoView !== 'function' || typeof window.requestAnimationFrame !== 'function') return
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
    const frame = window.requestAnimationFrame(() => card.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' }))
    return () => window.cancelAnimationFrame(frame)
  }, [])
  const riskClass = `result-risk-${result.relative_demand_band.toLowerCase()}`
  const time = result.target_timestamp.replace('T', ' ').slice(0, 16)
  const thresholdBasis = result.risk_method === 'entity_training_distribution'
    ? 'Station-specific training percentiles'
    : result.risk_method === 'system_training_fallback'
      ? 'System-level training fallback'
      : 'Global training-only fallback'
  return (
    <motion.article ref={resultRef} className={`result-card ${riskClass}`} initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }} transition={{ duration: 0.45 }} aria-live="polite" aria-label="Station demand forecast result">
      <div className="result-card-top">
        <div><p className="eyebrow"><span className="eyebrow-dot" /> MODEL OUTPUT · {result.forecast_kind.replaceAll('_', ' ').toUpperCase()}</p><p className="result-route">{result.station_name}<span> / </span>{time} <small>IST</small></p></div>
        <span className="result-model-label">{result.regression_model.replaceAll('_', ' ').toUpperCase()} · REGRESSION</span>
      </div>
      <div className="result-main">
        <div className="result-demand-block">
          <p className="result-caption">ESTIMATED STATION BOARDINGS <span>· TARGET HOUR</span></p>
          <div className="result-number"><NumberTicker value={result.predicted_boardings} /> <small>boardings / hour</small></div>
          <p className="result-context">A model estimate of entries at this station during the selected hour—not the number currently onboard a train.</p>
        </div>
        <div className="result-risk-block">
          <p className="result-caption">HISTORICAL-RELATIVE DEMAND BAND</p>
          <RiskBadge risk={result.relative_demand_band} className="risk-badge-large" />
          <p className="risk-basis">{thresholdBasis} · {result.threshold_sample_count.toLocaleString()} training targets</p>
        </div>
      </div>
      <div className="result-detail-grid">
        <div className="result-percentile">
          <div className="result-percentile-header"><span>TRAINING-DISTRIBUTION PERCENTILE</span><strong>{result.historical_percentile === null ? '—' : `≈ ${result.historical_percentile}th`}</strong></div>
          <RiskMeter percentile={result.historical_percentile} />
          <p>Compared with this station's training history where sample support allows; never an occupancy measure.</p>
        </div>
        <div className="result-thresholds">
          <span className="result-caption">FROZEN RISK CUTS · BOARDINGS / HOUR</span>
          <div className="threshold-values"><span>Q50 <b>{Math.round(result.risk_thresholds.q50).toLocaleString()}</b></span><span>Q80 <b>{Math.round(result.risk_thresholds.q80).toLocaleString()}</b></span><span>Q95 <b>{Math.round(result.risk_thresholds.q95).toLocaleString()}</b></span></div>
          <p>Fit on chronological training targets only, then frozen.</p>
        </div>
      </div>
      <div className="classification-check">
        <div className="check-icon"><Sparkles size={15} /></div>
        <div><strong>Independent classifier check</strong><span>{result.classification_model.replaceAll('_', ' ')} predicts <b>{result.classification_check}</b>. {result.classification_agrees ? 'It agrees with the percentile-derived band.' : 'It differs from the threshold-derived band; the badge follows the documented percentile rule.'}</span></div>
      </div>
      <div className="forecast-note"><span>DATA-SNAPSHOT NOTE</span><p>{result.forecast_note}</p></div>
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
                  <div className="driver-label"><span>{driver.label}</span><strong>{driver.delta_boardings > 0 ? '+' : ''}{Math.round(driver.delta_boardings).toLocaleString()} boardings</strong></div>
                  <div className="driver-track"><span style={{ width: `${width}%` }} /></div>
                </div>
              )
            })}
          </div>
        )}
        <p className="explain-footnote">{result.explanation_method}</p>
      </section>
      <section className="recommendation-panel" aria-label="Nearby lower-demand recommendation">
        <div className="recommendation-icon"><ArrowDownRight size={19} /></div>
        <div className="recommendation-copy">
          <p className="eyebrow">NEARBY LOWER-DEMAND WINDOWS</p>
          {result.recommendation.status === 'available' && result.recommendation.recommended ? (
            <><h3>{clock(result.recommendation.recommended.hour)} <span>→</span> {clock((result.recommendation.recommended.hour + 1) % 24)}</h3>
              <p>Lowest model-predicted nearby window: <b>{Math.round(result.recommendation.recommended.predicted_boardings).toLocaleString()} boardings</b> · {result.recommendation.recommended.relative_demand_band} relative band.</p></>
          ) : <><h3>{result.recommendation.status === 'no_lower_demand_window' ? 'No lower window found.' : 'Not enough history.'}</h3><p>{result.recommendation.message}</p></>}
          <small>{result.recommendation.basis}</small>
        </div>
        {result.recommendation.status === 'available' && result.recommendation.recommended && (
          <div className="recommendation-delta"><span>MODELLED CHANGE</span><b>{result.recommendation.reduction_percent === null || result.recommendation.reduction_percent === undefined ? '—' : `−${result.recommendation.reduction_percent.toFixed(0)}%`}</b></div>
        )}
      </section>
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
  metadata, systems, selectedSystem, systemId, city, mode, operator,
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
  const minDate = metadata.dataset.timestamp_min.slice(0, 10)
  const maxDate = plusHoursInIst(metadata.dataset.timestamp_max, metadata.prediction_max_recursive_horizon_hours)
  return (
    <section id="predict" className="predict-section section-anchor section-pad">
      <div className="section-shell">
        <div className="predict-intro">
          <SectionHeading eyebrow="THE PREDICTIVE ENGINE" title={<>The station-hour<br /><em>signal, made visible.</em></>} copy="Discover a city, mode and operator. Forecasts appear only where verified observed passenger-demand history and matching model artifacts exist." />
          <div className="engine-status"><span className="status-ring" /><span>{isAvailable ? 'MODEL READY' : 'NO MODEL'}</span><small>{isAvailable ? 'BMRCL SNAPSHOT · IST · NOT LIVE' : 'NETWORK DISCOVERY ONLY'}</small></div>
        </div>
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
                <label className="field-label" htmlFor="station-select">STATION · BMRCL OBSERVED DATA</label>
                <div className="control-wrap"><TrainFront size={16} aria-hidden="true" /><select id="station-select" name="station_id" value={stationId} onChange={(event) => setStationId(event.target.value)} required disabled={!isAvailable || stations.length === 0}>
                  {stations.map((item) => <option value={item.station_id} key={item.station_id}>{item.station_name} · {item.observed_hours.toLocaleString()} observed hours</option>)}
                </select><span className="select-caret">⌄</span></div>
                <div className="form-split">
                  <div><label className="field-label" htmlFor="target-date">TARGET DATE · IST</label><div className="control-wrap"><CalendarDays size={16} aria-hidden="true" /><input id="target-date" name="date" type="date" value={date} min={minDate} max={maxDate} onChange={(event) => setDate(event.target.value)} required disabled={!isAvailable} /></div></div>
                  <div><label className="field-label" htmlFor="target-hour">TARGET HOUR</label><div className="control-wrap"><Clock3 size={16} aria-hidden="true" /><select id="target-hour" name="hour" value={hour} onChange={(event) => setHour(Number(event.target.value))} required disabled={!isAvailable}>
                    {Array.from({ length: 24 }, (_, index) => <option key={index} value={index}>{clock(index)} – {clock((index + 1) % 24)}</option>)}
                  </select><span className="select-caret">⌄</span></div></div>
                </div>
                <p className="form-hint"><span className="form-hint-dot" /> Historical BMRCL snapshot · {metadata.dataset.timestamp_max.slice(0, 10)} latest source date · no live data.</p>
                <button className="predict-button" type="submit" disabled={loading || !isAvailable || !stationId || !date}>
                  <span>{loading ? 'ANALYSING STATION DEMAND' : 'PREDICT STATION DEMAND'}</span>
                  {loading ? <span className="button-spinner" aria-hidden="true" /> : <ArrowRight size={17} aria-hidden="true" />}
                </button>
                <p className="form-privacy">Observed station boardings only. No live train positions, occupancy, capacity or confidence score.</p>
              </>
            )}
          </form>
          <div className="result-stage" aria-live="polite">
            <div className="result-stage-top"><span>02 / MODEL OUTPUT</span><span className="stage-horizon">{isAvailable ? 'NEXT-HOUR STATION BOARDINGS' : 'PREDICTION UNAVAILABLE'}</span></div>
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
                  <p className="eyebrow">ANALYSING HISTORICAL SIGNAL</p><h3>Building the station-hour view.</h3>
                  <p>Using observed station boardings strictly before the selected target.</p>
                </motion.div>
              ) : error ? (
                <motion.div className="error-panel" key="error" initial={{ opacity: 0 }} animate={{ opacity: 1 }} role="alert">
                  <span className="error-mark">!</span><p className="eyebrow">FORECAST UNAVAILABLE</p><h3>We could not generate this view.</h3><p>{error}</p><button type="button" className="retry-button" onClick={() => document.getElementById('target-date')?.focus()}>Review your inputs <ArrowRight size={14} /></button>
                </motion.div>
              ) : result ? <ResultCard key={`${result.station_id}-${result.target_timestamp}`} result={result} /> : (
                <motion.div className="empty-result" key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                  <div className="empty-result-mark"><span>01</span><span>→</span><span>02</span></div>
                  <p className="eyebrow">BENGALURU · NAMMA METRO · BMRCL</p><h3>Observe first.<br /><em>Estimate next.</em></h3>
                  <p>Select a station and target hour. The only enabled passenger-demand model uses a verified historical BMRCL station-hour source.</p>
                  <span className="empty-rule" />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
        {result && comparison && (
          <div className="predict-comparison-note">
            <span className="eyebrow"><span className="eyebrow-dot" /> STATION CONTEXT</span>
            <p>{comparison.stations.length} station forecasts are available for this target. Station-relative percentiles appear in the <a href="#stations">station comparison</a>.</p>
          </div>
        )}
      </div>
    </section>
  )
}
