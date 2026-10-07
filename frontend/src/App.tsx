import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Activity, RefreshCw } from 'lucide-react'
import { Navigation } from './components/Navigation'
import { Footer } from './sections/Footer'
import { Hero } from './sections/Hero'
const StationDemandSection = lazy(() => import('./sections/DemandSection').then((module) => ({ default: module.StationDemandSection })))
import { PredictSection } from './sections/PredictSection'
import { StationSection } from './sections/StationSection'
const StationAnalyticsSection = lazy(() => import('./sections/StationAnalyticsSection').then((module) => ({ default: module.StationAnalyticsSection })))
import { ModelLabSection } from './sections/ModelLabSection'
import { MethodologySection, FinalCallToAction } from './sections/MethodologySection'
import { SignalTransition } from './sections/SignalTransition'
import { SystemsSection } from './sections/SystemsSection'
import { ApiError, api } from './services/api'
import type {
  AppMetadata, FuturePreviewResponse, HeatmapResponse, HistoryResponse,
  ModelReport, PredictionResult, SourceGapResponse, StationAnalytics, StationComparison, StationSummary, TransitSystem,
  WeeklyPatternResponse,
} from './types/api'

const ENABLED_SYSTEM_IDS = new Set(['bengaluru-namma-metro', 'mumbai-local-central', 'mumbai-metro'])

function SectionFallback({ label }: { label: string }) {
  return <div className="analytics-loading section-fallback" role="status"><span className="chart-spinner" />Loading {label}…</div>
}

function App() {
  const [metadata, setMetadata] = useState<AppMetadata | null>(null)
  const [systems, setSystems] = useState<TransitSystem[]>([])
  const [stations, setStations] = useState<StationSummary[]>([])
  const [report, setReport] = useState<ModelReport | null>(null)
  const [analytics, setAnalytics] = useState<StationAnalytics | null>(null)
  const [history, setHistory] = useState<HistoryResponse | null>(null)
  const [heatmap, setHeatmap] = useState<HeatmapResponse | null>(null)
  const [weekly, setWeekly] = useState<WeeklyPatternResponse | null>(null)
  const [gap, setGap] = useState<SourceGapResponse | null>(null)
  const [preview, setPreview] = useState<FuturePreviewResponse | null>(null)
  const [comparison, setComparison] = useState<StationComparison | null>(null)
  const [city, setCity] = useState('')
  const [mode, setMode] = useState('')
  const [operator, setOperator] = useState('')
  const [systemId, setSystemId] = useState('')
  const [stationId, setStationId] = useState('')
  const [targetDate, setTargetDate] = useState('')
  const [targetHour, setTargetHour] = useState(8)
  const [result, setResult] = useState<PredictionResult | null>(null)
  const [predictionError, setPredictionError] = useState<string | null>(null)
  const [bootstrapError, setBootstrapError] = useState<string | null>(null)
  const [booting, setBooting] = useState(true)
  const [predicting, setPredicting] = useState(false)
  const [comparing, setComparing] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [heatmapLoading, setHeatmapLoading] = useState(false)
  const [dataError, setDataError] = useState<string | null>(null)
  const [healthDetail, setHealthDetail] = useState<string | null>(null)
  const stationRequestId = useRef(0)
  const familyRequestId = useRef(0)

  const selectedSystem = useMemo(() => systems.find((item) => item.system_id === systemId) ?? null, [systems, systemId])
  const predictionAvailable = Boolean(selectedSystem?.prediction_available && metadata && selectedSystem.system_id === metadata.system_id)
  /** The observation resolution drives every label, window and input in the UI. */
  const granularity: 'hour' | 'day' = (selectedSystem?.granularity ?? metadata?.granularity ?? 'hour') === 'day' ? 'day' : 'hour'

  /** Load the per-family views. Hour and day families expose different endpoints. */
  const loadFamily = useCallback(async (system: TransitSystem) => {
    const requestId = ++familyRequestId.current
    const [meta, modelReport] = await Promise.all([api.metadata(system.system_id), api.modelPerformance(system.system_id)])
    const profiles = await api.stationAnalytics(system.system_id).catch(() => null)
    if (requestId !== familyRequestId.current) return null
    setMetadata(meta)
    setReport(modelReport)
    if (profiles) setAnalytics(profiles)
    setGap(await api.sourceGap(system.system_id).catch(() => null))
    if (meta.granularity === 'day' || system.granularity === 'day') {
      setPreview(await api.futurePreview(system.system_id, 3).catch(() => null))
    } else {
      setPreview(null)
    }
    return meta
  }, [])

  const loadApplication = useCallback(async () => {
    setBooting(true)
    setBootstrapError(null)
    try {
      const health = await api.health()
      setHealthDetail(health.detail ?? null)
      const catalog = await api.systems()
      const enabledCatalog = catalog.filter((item) => ENABLED_SYSTEM_IDS.has(item.system_id))
      setSystems(enabledCatalog)
      if (!health.model_ready || !health.data_ready) {
        throw new ApiError(health.detail ?? 'The backend has no verified model artifact or normalized observed-demand dataset loaded.', 503)
      }
      const activeSystem = enabledCatalog.find((item) => item.system_id === (health.system_id ?? metadata?.system_id) && item.prediction_available)
        ?? enabledCatalog.find((item) => item.prediction_available)
      if (!activeSystem) throw new ApiError('No catalogued system is marked as an available verified prediction family.', 503)
      const meta = await loadFamily(activeSystem)
      if (!meta) throw new ApiError('The loaded model family returned no metadata.', 503)
      const stationRows = await api.stations(activeSystem.system_id)
      if (stationRows.length === 0) throw new ApiError('The verified station list for this family is empty.', 503)
      setStations(stationRows)
      setCity(activeSystem.city)
      setMode(activeSystem.mode)
      setOperator(activeSystem.operator)
      setSystemId(activeSystem.system_id)
      setStationId(meta.default_station_id || stationRows[0].station_id)
      setTargetDate(meta.default_target_date)
      if (meta.default_target_hour !== undefined) setTargetHour(meta.default_target_hour)
    } catch (error) {
      setBootstrapError(error instanceof Error ? error.message : 'Could not connect to the India transit model service.')
    } finally {
      setBooting(false)
    }
  }, [loadFamily])

  useEffect(() => { void loadApplication() }, [loadApplication])

  // Observed history and the pattern view follow the family's granularity.
  useEffect(() => {
    if (!metadata || !predictionAvailable || !stationId) {
      setHistory(null)
      setHeatmap(null)
      setWeekly(null)
      setHistoryLoading(false)
      setHeatmapLoading(false)
      return
    }
    let alive = true
    setHistoryLoading(true)
    setHeatmapLoading(true)
    setDataError(null)
    const series = granularity === 'day' ? api.history(systemId, stationId, { days: 90 }) : api.history(systemId, stationId, { hours: 168 })
    const pattern = granularity === 'day' ? api.weeklyPattern(systemId, stationId) : api.heatmap(systemId, stationId)
    Promise.allSettled([series, pattern]).then(([historyResult, patternResult]) => {
      if (!alive) return
      if (historyResult.status === 'fulfilled') setHistory(historyResult.value)
      else setDataError(historyResult.reason instanceof Error ? historyResult.reason.message : 'Observed station history is unavailable.')
      if (patternResult.status === 'fulfilled') {
        if (granularity === 'day') setWeekly(patternResult.value as WeeklyPatternResponse)
        else setHeatmap(patternResult.value as HeatmapResponse)
      } else {
        setDataError((current) => current ?? (patternResult.reason instanceof Error ? patternResult.reason.message : 'Observed weekly profile is unavailable.'))
      }
    }).finally(() => {
      if (alive) { setHistoryLoading(false); setHeatmapLoading(false) }
    })
    return () => { alive = false }
  }, [granularity, metadata, predictionAvailable, stationId, systemId])

  const selectSystem = (system: TransitSystem) => {
    stationRequestId.current += 1
    const requestId = stationRequestId.current
    familyRequestId.current += 1
    setCity(system.city)
    setMode(system.mode)
    setOperator(system.operator)
    setSystemId(system.system_id)
    setStations([])
    setStationId(system.prediction_available && metadata?.system_id === system.system_id ? metadata.default_station_id : '')
    setResult(null)
    setComparison(null)
    setPredictionError(null)
    setPreview(null)
    if (!system.prediction_available) { setGap(null); return }
    void (async () => {
      try {
        const meta = metadata?.system_id === system.system_id ? metadata : await loadFamily(system)
        if (!meta) return
        const rows = await api.stations(system.system_id)
        if (requestId !== stationRequestId.current) return
        setStations(rows)
        setStationId((current) => rows.some((row) => row.station_id === current) ? current : meta?.default_station_id || rows[0]?.station_id || '')
        setTargetDate(meta.default_target_date)
        if (meta.default_target_hour !== undefined) setTargetHour(meta.default_target_hour)
      } catch (error) {
        if (requestId === stationRequestId.current) setDataError(error instanceof Error ? error.message : 'Verified station records are unavailable.')
      }
    })()
  }

  const handleCityChange = (nextCity: string) => {
    const first = systems.find((item) => item.city === nextCity)
    if (first) selectSystem(first)
  }
  const handleModeChange = (nextMode: string) => {
    const first = systems.find((item) => item.city === city && item.mode === nextMode)
    if (first) selectSystem(first)
  }
  const handleOperatorChange = (nextOperator: string) => {
    const next = systems.find((item) => item.city === city && item.mode === mode && item.operator === nextOperator)
    if (next) selectSystem(next)
  }

  const changeStation = (nextStationId: string) => {
    setStationId(nextStationId)
    setResult(null)
    setComparison(null)
    setPredictionError(null)
  }

  const handlePredict = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!predictionAvailable || !systemId || !stationId || !targetDate) return
    setPredicting(true)
    setPredictionError(null)
    setResult(null)
    setComparison(null)
    try {
      const prediction = await api.predict({
        system_id: systemId, station_id: stationId, target_date: targetDate,
        target_hour: granularity === 'hour' ? targetHour : undefined,
      })
      setResult(prediction)
      setPredicting(false)
      setComparing(true)
      try {
        const stationRows = await api.stationComparison(systemId, targetDate, granularity === 'hour' ? targetHour : null, stationId)
        setComparison(stationRows)
      } catch (comparisonError) {
        setDataError(comparisonError instanceof Error ? comparisonError.message : 'Station comparison is unavailable for this target.')
      } finally {
        setComparing(false)
      }
    } catch (error) {
      setPredictionError(error instanceof Error ? error.message : 'The model could not generate an estimate for this target.')
      setPredicting(false)
    }
  }

  const focusPrediction = () => {
    document.getElementById('predict')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    document.getElementById(predictionAvailable ? 'station-select' : 'city-select')?.focus({ preventScroll: true })
  }
  const chooseStationFromComparison = (nextStationId: string) => {
    changeStation(nextStationId)
    focusPrediction()
  }

  if (booting) {
    return <main className="app-boot" role="status"><span className="boot-mark"><Activity size={19} /></span><p className="eyebrow">CONNECTING TO THE INDIA TRANSIT CATALOG</p><h1>Opening the<br /><em>signal.</em></h1><span className="boot-line" /></main>
  }

  if (!metadata) {
    return (
      <div className="app-shell">
        <Navigation />
        <main id="home" className="connection-failure section-anchor">
          <span className="failure-icon">!</span><p className="eyebrow">VERIFIED MODEL SERVICE NOT READY</p><h1>The signal is<br /><em>unavailable.</em></h1>
          <p>{bootstrapError ?? healthDetail ?? 'The application could not load its observed source data and a trained model artifact.'}</p>
          <button type="button" className="arrow-link" onClick={() => void loadApplication()}>Retry connection <RefreshCw size={15} /></button>
          <div className="failure-foot">NO SAMPLE RESULTS · NO PLACEHOLDER FORECASTS · NETWORK REFERENCES ARE NOT DEMAND</div>
        </main>
        <Footer />
      </div>
    )
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <Navigation />
      <main id="main-content">
        <Hero onExplore={() => document.getElementById('systems')?.scrollIntoView({ behavior: 'smooth', block: 'start' })} />
        <SignalTransition />
        {dataError && <div className="data-warning" role="status"><span>DATA NOTICE</span><p>{dataError}</p><button type="button" onClick={() => setDataError(null)} aria-label="Dismiss data notice">×</button></div>}
        <SystemsSection systems={systems} selectedSystemId={systemId} onSelectSystem={selectSystem} />
        <PredictSection
          metadata={metadata} systems={systems} selectedSystem={selectedSystem} systemId={systemId}
          city={city} mode={mode} operator={operator} granularity={granularity} gap={gap}
          onCityChange={handleCityChange} onModeChange={handleModeChange} onOperatorChange={handleOperatorChange}
          stations={stations} stationId={stationId} setStationId={changeStation}
          date={targetDate} setDate={setTargetDate} hour={targetHour} setHour={setTargetHour}
          onSubmit={handlePredict} loading={predicting} result={result} error={predictionError} comparison={comparison}
        />
        <Suspense fallback={<SectionFallback label="observed station demand" />}><StationDemandSection history={historyLoading ? null : history} heatmap={heatmapLoading ? null : heatmap} weekly={weekly} granularity={granularity} preview={preview} stations={stations} stationId={stationId} onPickHour={setTargetHour} available={predictionAvailable} /></Suspense>
        <StationSection comparison={comparison} loading={comparing} selectedStationId={stationId} onSelectStation={chooseStationFromComparison} available={predictionAvailable} granularity={granularity} />
        <ModelLabSection report={report} activeSystemId={systemId} granularity={granularity} />
        <Suspense fallback={<SectionFallback label="station behaviour profiles" />}><StationAnalyticsSection analytics={analytics} available={predictionAvailable} /></Suspense>
        <MethodologySection metadata={metadata} report={report} activeSystemId={systemId} granularity={granularity} />
        <FinalCallToAction />
      </main>
      <Footer />
    </div>
  )
}

export default App
