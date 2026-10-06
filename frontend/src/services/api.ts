import type {
  AppMetadata, DemandSourcesResponse, HeatmapResponse, HistoryResponse, ModelReport,
  PredictionResult, StationAnalytics, StationComparison, StationSummary, TransitSystem,
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

export const api = {
  health: () => requestJson<{ status: string; model_ready: boolean; data_ready: boolean; system_id?: string; detail?: string | null }>('/health'),
  systems: () => requestJson<TransitSystem[]>('/systems'),
  demandSources: () => requestJson<DemandSourcesResponse>('/demand-sources'),
  metadata: () => requestJson<AppMetadata>('/metadata'),
  stations: (systemId: string) => requestJson<StationSummary[]>(`/stations?system_id=${encodeURIComponent(systemId)}`),
  predict: (payload: { system_id: string; station_id: string; target_date: string; target_hour: number }) =>
    requestJson<PredictionResult>('/predict', { method: 'POST', body: JSON.stringify(payload) }),
  history: (systemId: string, stationId: string, hours = 168) => {
    const params = new URLSearchParams({ system_id: systemId, station_id: stationId, hours: String(hours) })
    return requestJson<HistoryResponse>(`/history?${params.toString()}`)
  },
  heatmap: (systemId: string, stationId: string) => {
    const params = new URLSearchParams({ system_id: systemId, station_id: stationId })
    return requestJson<HeatmapResponse>(`/heatmap?${params.toString()}`)
  },
  stationAnalytics: () => requestJson<StationAnalytics>('/station-analytics'),
  modelPerformance: () => requestJson<ModelReport>('/model-performance'),
  stationComparison: (systemId: string, date: string, hour: number, selectedStationId: string) => {
    const params = new URLSearchParams({ system_id: systemId, target_date: date, target_hour: String(hour), selected_station_id: selectedStationId })
    return requestJson<StationComparison>(`/station-comparison?${params.toString()}`)
  },
}
