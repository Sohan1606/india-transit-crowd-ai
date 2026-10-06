import { ArrowRight, ExternalLink, MoveUpRight, TrainFront } from 'lucide-react'
import type { StationComparison, Risk } from '../types/api'
import { Reveal, RiskBadge, SectionHeading } from '../components/ui'

export function StationSection({ comparison, loading, selectedStationId, onSelectStation, available, granularity = 'hour' }: {
  granularity?: 'hour' | 'day'
  comparison: StationComparison | null
  loading: boolean
  selectedStationId: string
  onSelectStation: (stationId: string) => void
  available: boolean
}) {
  const maxPercentile = Math.max(...(comparison?.stations ?? []).map((station) => station.historical_percentile ?? 0), 1)
  return (
    <section id="stations" className="station-section section-anchor section-pad">
      <div className="section-shell">
        <div className="station-section-head">
          <SectionHeading eyebrow="STATION INTELLIGENCE" title={<>One metro system.<br /><em>Different demand shapes.</em></>} copy="Compare model estimates against each station's own training-period distribution. The result is historical-relative—not a physical occupancy or safety ranking." />
          <div className="station-context-stamp"><TrainFront size={16} /><span>STATION-RELATIVE<br />COMPARISON</span></div>
        </div>
        <div className="station-compare-frame">
          <div className="station-compare-top"><span>01 / BMRCL STATION SNAPSHOT</span><span>{comparison ? comparison.target_timestamp.replace('T', ' ').slice(0, 16) : 'PREDICTION NEEDED'}</span></div>
          {!available ? (
            <div className="comparison-empty"><span className="comparison-empty-icon"><TrainFront size={20} /></span><div><p className="eyebrow">SYSTEM DISCOVERY ONLY</p><h3>No station forecasts for this system.</h3><p>Only verified Bengaluru Namma Metro/BMRCL station-hour observations are enabled. Schedule references do not create passenger-demand predictions.</p><a href="#systems">Explore system data <ExternalLink size={14} /></a></div></div>
          ) : !comparison && !loading ? (
            <div className="comparison-empty"><span className="comparison-empty-icon"><MoveUpRight size={20} /></span><div><p className="eyebrow">STATION-LEVEL CONTEXT</p><h3>Start with a single station.</h3><p>Run a forecast above. This view will compare the same target hour across stations using each station's training-period percentile.</p><a href="#predict">Choose a station <ArrowRight size={14} /></a></div></div>
          ) : loading ? <div className="station-loading"><span className="chart-spinner" />Scoring station forecasts for this target hour…</div> : (
            <>
              <div className="station-list-head"><span>STATION</span><span>DEMAND VS OWN HISTORY</span><span>MODELLED {granularity === 'day' ? 'ENTRIES' : 'BOARDINGS'}</span><span>RELATIVE BAND</span></div>
              <div className="station-compare-list">
                {comparison?.stations.map((item, index) => {
                  const percentile = item.historical_percentile ?? 0
                  const relativeWidth = Math.max(3, percentile / maxPercentile * 100)
                  return (
                    <button type="button" className={`station-compare-row ${item.station_id === selectedStationId ? 'is-selected' : ''}`} key={item.station_id} onClick={() => onSelectStation(item.station_id)} aria-label={`Select ${item.station_name}, model estimate ${Math.round(item.predicted_boardings ?? item.predicted_daily_entries ?? 0).toLocaleString()} ${granularity === 'day' ? 'entries per day' : 'boardings per hour'}, ${item.relative_demand_band} relative band`}>
                      <span className="station-rank">{String(index + 1).padStart(2, '0')}</span>
                      <strong className="station-name">{item.station_name}</strong>
                      <span className="station-relative"><span className="station-relative-track"><i style={{ width: `${relativeWidth}%` }} /></span><small>{item.historical_percentile === null ? '—' : `≈ ${item.historical_percentile}th percentile`}</small></span>
                      <strong className="station-forecast-value">{Math.round(item.predicted_boardings ?? item.predicted_daily_entries ?? 0).toLocaleString()} <small>{granularity === 'day' ? '/ day' : '/ h'}</small></strong>
                      <RiskBadge risk={item.relative_demand_band as Risk} />
                      <MoveUpRight className="station-row-arrow" size={14} aria-hidden="true" />
                    </button>
                  )
                })}
              </div>
              <div className="station-comparison-foot"><span>ORDERED BY STATION-RELATIVE TRAINING PERCENTILE</span><p>{comparison?.comparison_basis} {comparison?.stations_without_estimate ? `${comparison.stations_without_estimate} stations have insufficient contiguous history for this target.` : ''}</p></div>
            </>
          )}
        </div>
        <Reveal className="station-caveat" delay={0.08}>
          <span className="station-caveat-mark">≠</span><p>Percentile comparisons show where an estimate sits within each station's own history. They do <b>not</b> measure train capacity, onboard load or physical crowding.</p>
        </Reveal>
      </div>
    </section>
  )
}
