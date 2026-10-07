import { ArrowUpRight, Database, ExternalLink, Map, TrainFront } from 'lucide-react'
import type { DemandSourceCandidate, TransitSystem } from '../types/api'
import { Reveal, SectionHeading } from '../components/ui'

export function SystemsSection({
  systems, candidates, selectedSystemId, onSelectSystem,
}: {
  systems: TransitSystem[]
  candidates: DemandSourceCandidate[]
  selectedSystemId: string
  onSelectSystem: (system: TransitSystem) => void
}) {
  const availableCount = systems.filter((system) => system.prediction_available).length
  return (
    <section id="systems" className="systems-section section-anchor section-pad">
      <div className="section-shell">
        <div className="systems-intro">
          <SectionHeading eyebrow="INDIA SYSTEM DISCOVERY" title={<>Many networks.<br /><em>One governed engine.</em></>} copy="Explore the Indian systems reviewed for this build. Timetables support discovery; forecasting is enabled only when a registered demand family has the data, provenance and artifacts needed to answer honestly." />
          <div className="systems-count-stamp"><Database size={17} /><span>{availableCount} MODEL FAMILY<br />{systems.length} SYSTEM REFERENCES</span></div>
        </div>
        <div className="systems-scope-banner"><span className="scope-signal"><i /></span><div><strong>Prediction is enabled only for registered model families with loaded demand history and artifacts.</strong><p>Unavailable networks remain discovery references. Synthetic demonstration families are labelled explicitly; static GTFS never becomes a passenger-demand target.</p></div><a href="#predict">Choose a system <ArrowUpRight size={13} /></a></div>
        <div className="system-card-grid">
          {systems.map((system, index) => (
            <Reveal key={system.system_id} className={`system-card ${system.prediction_available ? 'is-available' : ''} ${selectedSystemId === system.system_id ? 'is-selected' : ''}`} delay={Math.min(index % 4, 3) * 0.04}>
              <div className="system-card-top"><span className="system-index">{String(index + 1).padStart(2, '0')}</span><span className={`system-availability ${system.prediction_available ? 'is-available' : ''}`}><i />{system.prediction_available ? 'MODEL AVAILABLE' : 'NO DEMAND MODEL'}</span>{system.served_as === 'demo' ? <span className="demo-flag">synthetic demo</span> : null}</div>
              <p className="system-city">{system.city} · {system.state}</p>
              <h3>{system.system_name}</h3>
              <div className="system-tags"><span>{system.mode}</span><span>{system.operator}</span></div>
              <p className="system-status-copy">{system.prediction_available ? system.observed_demand_status : system.prediction_unavailable_reason}</p>
              <div className="system-reference-line"><Map size={13} /><span>{system.network_reference_kind}</span></div>
              <div className="system-card-actions">
                <button type="button" onClick={() => onSelectSystem(system)} aria-pressed={selectedSystemId === system.system_id}>
                  {selectedSystemId === system.system_id ? 'SELECTED' : system.prediction_available ? 'OPEN PREDICTOR' : 'VIEW UNAVAILABLE STATUS'}
                  <ArrowUpRight size={13} />
                </button>
                {system.network_reference_url && <a href={system.network_reference_url} target="_blank" rel="noreferrer" aria-label={`Open ${system.system_name} network reference`}><ExternalLink size={14} /></a>}
              </div>
            </Reveal>
          ))}
        </div>
        <Reveal className="demand-candidate-panel">
          <div className="candidate-panel-head"><div><p className="eyebrow"><span className="eyebrow-dot" /> OBSERVED-DEMAND SOURCES UNDER REVIEW</p><h3>Evidence before expansion.</h3></div><TrainFront size={19} /></div>
          <p className="candidate-intro">These are credible leads—not enabled training data. Files, granularity, source provenance and reuse terms must be rechecked before adding an adapter or model.</p>
          <div className="candidate-grid">
            {candidates.map((candidate) => (
              <article className="candidate-card" key={`${candidate.city}-${candidate.system}`}>
                <div className="candidate-city">{candidate.city} · {candidate.system}</div>
                <h4>{candidate.source_title}</h4>
                <p>{candidate.published_granularity}</p>
                <div className="candidate-access"><span>ACCESS / RIGHTS</span><strong>{candidate.access_status}</strong></div>
                <div className="candidate-suitability"><span>FORECAST SUITABILITY</span><p>{candidate.forecast_suitability}</p></div>
                <a href={candidate.url} target="_blank" rel="noreferrer">Open source reference <ExternalLink size={13} /></a>
              </article>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  )
}
