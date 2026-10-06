import type {
  AppMetadata, DemandSourcesResponse, FuturePreviewResponse, HeatmapResponse, HistoryResponse, ModelReport,
  PredictionResult, SourceGapResponse, StationAnalytics, StationComparison, StationSummary, TransitSystem,
  WeeklyPatternResponse,
} from '../types/api'

const API_ROOT = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
    })
  } catch {
    throw new ApiError('The prediction service is unreachable. Start the FastAPI backend and retry.', 0)
  }
  if (!response.ok) {
    let message = `Request failed (${response.status}).`
    try {
      const payload = await response.json() as { detail?: unknown }
      if (typeof payload.detail === 'string') message = payload.detail
      else if (Array.isArray(payload.detail)) message = payload.detail.map((item) => item.msg).filter(Boolean).join(' · ')
    } catch {
      // Keep a safe user-readable HTTP error if the server returned no JSON.
    }
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}

function withSystem(path: string, systemId?: string) {
  if (!systemId) return path
  return `${path}${path.includes('?') ? '&' : '?'}system_id=${encodeURIComponent(systemId)}`
}

export const api = {
  health: (systemId?: string) => requestJson<{ status: string; model_ready: boolean; data_ready: boolean; system_id?: string; detail?: string | null }>(withSystem('/health', systemId)),
  systems: () => requestJson<TransitSystem[]>('/systems'),
  demandSources: () => requestJson<DemandSourcesResponse>('/demand-sources'),
  metadata: (systemId?: string) => requestJson<AppMetadata>(withSystem('/metadata', systemId)),
  stations: (systemId: string) => requestJson<StationSummary[]>(`/stations?system_id=${encodeURIComponent(systemId)}`),
  /** Hour families require `target_hour`; day families must omit it (the API rejects it). */
  predict: (payload: { system_id: string; station_id: string; target_date: string; target_hour?: number | null }) =>
    requestJson<PredictionResult>('/predict', { method: 'POST', body: JSON.stringify(payload) }),
  history: (systemId: string, stationId: string, window: { hours?: number; days?: number } = { hours: 168 }) => {
    const params = new URLSearchParams({ system_id: systemId, station_id: stationId })
    if (window.days !== undefined) params.set('days', String(window.days))
    else params.set('hours', String(window.hours ?? 168))
    return requestJson<HistoryResponse>(`/history?${params.toString()}`)
  },
  heatmap: (systemId: string, stationId: string) => {
    const params = new URLSearchParams({ system_id: systemId, station_id: stationId })
    return requestJson<HeatmapResponse>(`/heatmap?${params.toString()}`)
  },
  /** Observed day-of-week means: the honest substitute for an hour heatmap on a day family. */
  weeklyPattern: (systemId: string, stationId: string) => {
    const params = new URLSearchParams({ system_id: systemId, station_id: stationId })
    return requestJson<WeeklyPatternResponse>(`/weekly-pattern?${params.toString()}`)
  },
  futurePreview: (systemId: string, days = 7) => {
    const params = new URLSearchParams({ system_id: systemId, days: String(days) })
    return requestJson<FuturePreviewResponse>(`/future-preview?${params.toString()}`)
  },
  sourceGap: (systemId: string) => requestJson<SourceGapResponse>(`/source-gap?system_id=${encodeURIComponent(systemId)}`),
  stationAnalytics: (systemId?: string) => requestJson<StationAnalytics>(withSystem('/station-analytics', systemId)),
  modelPerformance: (systemId?: string) => requestJson<ModelReport>(withSystem('/model-performance', systemId)),
  stationComparison: (systemId: string, date: string, hour: number | null, selectedStationId: string) => {
    const params = new URLSearchParams({ system_id: systemId, target_date: date, selected_station_id: selectedStationId })
    if (hour !== null && hour !== undefined) params.set('target_hour', String(hour))
    return requestJson<StationComparison>(`/station-comparison?${params.toString()}`)
  },
}
