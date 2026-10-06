import { useMemo } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Activity, ArrowUpRight, Waves } from 'lucide-react'
import type { HeatmapResponse, HistoryResponse, StationSummary } from '../types/api'
import { NumberTicker, Reveal, SectionHeading } from '../components/ui'

const compact = new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 })
const full = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })

function ObservedTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: { time?: string; demand?: number } }> }) {
  const point = payload?.[0]?.payload
  if (!active || typeof point?.demand !== 'number') return null
  return <div className="chart-tooltip"><span>OBSERVED · {point.time}</span><strong>{full.format(point.demand)} <small>boardings / hour</small></strong></div>
}

export function StationDemandSection({
  history, heatmap, stations, stationId, onPickHour, available,
}: {
  history: HistoryResponse | null
  heatmap: HeatmapResponse | null
  stations: StationSummary[]
  stationId: string
  onPickHour: (hour: number) => void
  available: boolean
}) {
  const chartData = useMemo(() => (history?.points ?? []).map((point) => {
    const date = point.timestamp.replace('T', ' ')
    return { time: date.slice(5, 16), timestamp: point.timestamp, demand: point.observed_boardings }
  }), [history])
  const dayStats = useMemo(() => {
    const points = history?.points ?? []
    if (!points.length) return null
    const recent = points.slice(-24)
    const mean = recent.reduce((sum, point) => sum + point.observed_boardings, 0) / recent.length
    return { mean, peak: Math.max(...points.map((point) => point.observed_boardings)), count: points.length, recentCount: recent.length }
  }, [history])
  const summary = stations.find((item) => item.station_id === stationId)
  const availableValues = (heatmap?.cells ?? []).map((cell) => cell.mean_observed_boardings).filter((value): value is number => value !== null)
  const maxDemand = Math.max(...availableValues, 1)

  return (
    <section id="demand" className="demand-section section-anchor section-pad">
      <div className="section-shell">
        <div className="demand-intro-row">
          <SectionHeading eyebrow="THE DEMAND STORY" title={<>Station demand<br /><em>has a rhythm.</em></>} copy="Explore the published BMRCL station-hour observations. Missing source hours remain missing; forecasts are never blended into the observed series." />
          <div className="demand-station-context"><span className="context-overline">SELECTED STATION</span><strong>{available ? summary?.station_name ?? '—' : 'Not available'}</strong><span>{available && summary ? `${summary.observed_hours.toLocaleString()} observed station-hours` : 'No verified history for this system'}</span><a href="#predict">Change station <ArrowUpRight size={13} /></a></div>
        </div>
        {!available ? <div className="unsupported-panel analytics-unavailable" role="status"><p className="eyebrow">NO OBSERVED-DEMAND VIEW</p><h3>Network discovery does not include passenger counts.</h3><p>Return to Bengaluru · Metro · BMRCL to explore the verified historical station-hour series.</p></div> : (
          <>
            <Reveal>
              <div className="history-story-card">
                <div className="story-card-header">
                  <div><p className="eyebrow"><span className="eyebrow-dot" /> OBSERVED STATION-HOUR BOARDINGS</p><h3>{summary?.station_name ?? 'Selected station'} · recent source history.</h3></div>
                  <div className="observed-key"><span /> OBSERVED <small>· SOURCE DATA</small></div>
                </div>
                <div className="chart-summary-row">
                  <div><span>LATEST 24 OBSERVATIONS · MEAN</span><strong>{dayStats ? <><NumberTicker value={dayStats.mean} /> <small>boardings / hour</small></> : '—'}</strong></div>
                  <div><span>PEAK IN VISIBLE WINDOW</span><strong>{dayStats ? <><NumberTicker value={dayStats.peak} /> <small>boardings / hour</small></> : '—'}</strong></div>
                  <div><span>OBSERVED RECORDS SHOWN</span><strong>{dayStats ? dayStats.count.toLocaleString() : '—'} <small>published hours</small></strong></div>
                </div>
                <div className="history-chart" role="img" aria-label={`${summary?.station_name ?? 'Selected station'} observed hourly boardings in the BMRCL historical snapshot`}>
                  {!history ? <div className="chart-state"><span className="chart-spinner" />Loading observed source records…</div> : chartData.length === 0 ? <div className="chart-state">No observed boardings are available in this time window.</div> : (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={chartData} margin={{ top: 12, right: 18, left: -12, bottom: 2 }}>
                        <defs><linearGradient id="demandFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#c7ee7b" stopOpacity={0.2} /><stop offset="95%" stopColor="#c7ee7b" stopOpacity={0} /></linearGradient></defs>
                        <CartesianGrid stroke="#2b2f28" strokeDasharray="2 6" vertical={false} />
                        <XAxis dataKey="time" tick={{ fill: '#858980', fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={42} />
                        <YAxis tickFormatter={(value: number) => compact.format(value)} tick={{ fill: '#858980', fontSize: 10 }} tickLine={false} axisLine={false} width={52} />
                        <Tooltip content={<ObservedTooltip />} cursor={{ stroke: '#c7ee7b', strokeDasharray: '3 4', strokeWidth: 1 }} />
                        <Area type="monotone" dataKey="demand" stroke="#c7ee7b" strokeWidth={1.7} fill="url(#demandFill)" activeDot={{ r: 4, stroke: '#10120f', strokeWidth: 2, fill: '#c7ee7b' }} isAnimationActive={false} />
                      </AreaChart>
                    </ResponsiveContainer>
                  )}
                </div>
                <div className="chart-bottom"><span><i className="observed-legend-line" /> OBSERVED BMRCL BOARDINGS · SOURCE DATA</span><span>HOURLY · ASIA/KOLKATA</span></div>
              </div>
            </Reveal>
            <div className="demand-lower-grid">
              <Reveal className="heatmap-panel">
                <div className="panel-heading"><div><p className="eyebrow"><span className="eyebrow-dot" /> WEEKLY PROFILE</p><h3>Observed, by weekday and hour.</h3></div><Waves size={18} /></div>
                <p className="panel-description">Mean of available station-hour records. Blank cells mean no source observations—not zero boardings. Select a populated cell to set the forecast hour.</p>
                <div className="heatmap-scroll">
                  <div className="heatmap-grid" role="grid" aria-label={`Observed demand heatmap for ${summary?.station_name ?? 'selected station'}`}>
                    <div className="heatmap-corner" role="columnheader">DAY / HOUR</div>
                    {Array.from({ length: 24 }, (_, hour) => <div className="heatmap-hour" role="columnheader" key={hour}>{hour % 3 === 0 ? String(hour).padStart(2, '0') : ''}</div>)}
                    {Array.from({ length: 7 }, (_, day) => (
                      <div className="heatmap-row" role="row" key={day}>
                        <span className="heatmap-day" role="rowheader">{['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'][day]}</span>
                        {Array.from({ length: 24 }, (_, hour) => {
                          const cell = heatmap?.cells.find((item) => item.day_of_week === day && item.hour === hour)
                          const value = cell?.mean_observed_boardings ?? null
                          const opacity = value === null ? 0 : 0.12 + (value / maxDemand) * 0.82
                          const title = value === null ? `${cell?.day_name ?? ''} ${String(hour).padStart(2, '0')}:00 · no observations` : `${cell?.day_name} ${String(hour).padStart(2, '0')}:00 · mean ${full.format(value)} boardings/hour · ${cell?.observations.toLocaleString()} observations`
                          return <button key={hour} type="button" className={`heatmap-cell ${value === null ? 'heatmap-missing' : ''}`} style={{ '--cell-alpha': opacity } as React.CSSProperties} title={title} aria-label={title} onClick={() => onPickHour(hour)} disabled={value === null} />
                        })}
                      </div>
                    ))}
                  </div>
                </div>
                <div className="heatmap-legend"><span>LESS OBSERVED DEMAND</span><i /><i /><i /><i /><span>MORE</span></div>
              </Reveal>
              <Reveal className="demand-note-panel" delay={0.08}>
                <div className="note-number">01<span> / 03</span></div>
                <Activity size={19} className="note-icon" />
                <p className="eyebrow">READING THE SIGNAL</p>
                <h3>History is a pattern.<br /><em>Not a promise.</em></h3>
                <p>The line above contains observed BMRCL boardings only. Model estimates are returned separately and are never blended into the source history.</p>
                <div className="note-data-line"><span>Observed</span><b>Published station-hour counts</b></div>
                <div className="note-data-line"><span>Predicted</span><b>Model output · distinct</b></div>
              </Reveal>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
