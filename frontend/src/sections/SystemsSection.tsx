import { ArrowUpRight, Database, Map } from 'lucide-react'
import type { TransitSystem } from '../types/api'
import { Reveal, SectionHeading } from '../components/ui'

export function SystemsSection({
  systems, selectedSystemId, onSelectSystem,
}: {
  systems: TransitSystem[]
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
        <div className="systems-scope-banner"><span className="scope-signal"><i /></span><div><strong>Prediction is enabled only for registered model families with loaded demand history and artifacts.</strong><p>Only the three registered forecasting families are shown in the product flow; unsupported network references stay out of the interface.</p></div><a href="#predict">Choose a system <ArrowUpRight size={13} /></a></div>
        <div className="system-card-grid">
          {systems.map((system, index) => (
            <Reveal key={system.system_id} className={`system-card ${system.prediction_available ? 'is-available' : ''} ${selectedSystemId === system.system_id ? 'is-selected' : ''}`} delay={Math.min(index % 4, 3) * 0.04}>
              <div className="system-card-top"><span className="system-index">{String(index + 1).padStart(2, '0')}</span><span className={`system-availability ${system.prediction_available ? 'is-available' : ''}`}><i />{system.prediction_available ? 'MODEL AVAILABLE' : 'NO DEMAND MODEL'}</span></div>
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

              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}
