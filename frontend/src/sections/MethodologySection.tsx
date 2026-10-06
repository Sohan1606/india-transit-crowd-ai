import { ArrowRight, ExternalLink, ShieldAlert } from 'lucide-react'
import type { AppMetadata, ModelReport } from '../types/api'
import { ArrowLink, Reveal, SectionHeading } from '../components/ui'

const processSteps = [
  ['01', 'ADAPT', 'Pinned observed BMRCL station-hour source.'],
  ['02', 'NORMALIZE', 'One entity-hour record; absent hours remain absent.'],
  ['03', 'FEATURE', 'Calendar and station history strictly before target T.'],
  ['04', 'BENCHMARK', 'Regression and four-band classification candidates.'],
  ['05', 'VALIDATE', 'Chronological split; training-only thresholds frozen.'],
  ['06', 'PREDICT', 'Next-hour station boardings from a saved artifact.'],
  ['07', 'EXPLAIN', 'Validation permutation and model sensitivity.'],
  ['08', 'RECOMMEND', 'Same-station nearby windows from the fitted model.'],
]

const limitationItems = [
  ['Historical snapshot', 'The verified file covers 1–18 August and 1–30 September 2025, with an August 19–31 gap; its station roster varies during August.'],
  ['Not current service', 'There is no live BMRCL feed. The default projection begins after the last observation in the published snapshot and may be in the past relative to today.'],
  ['Not occupancy', 'The source records station boardings per hour. It contains no train capacity or onboard load, so the percentile bands are not physical crowding or safety thresholds.'],
  ['Short holdout', 'The latest chronological test period is only a few days. It does not establish annual seasonality or performance on current service patterns.'],
  ['Unobserved context', 'Disruptions, headways, weather, holidays, events, transfers and service changes are not joined model features.'],
  ['Decision support', 'Recommendations compare estimates at the same station; a lower predicted count is not a service guarantee, occupancy guarantee or substitute for official advisories.'],
]

function coverageText(metadata: AppMetadata) {
  const rows = metadata.dataset.source_periods ?? []
  const text = rows
    .map((period) => {
      const start = period.start_inclusive ?? period.start ?? ''
      const end = period.end_inclusive ?? period.end ?? start
      return [start, end].filter(Boolean).join('–')
    })
    .filter(Boolean)
    .join(' · ')
  return text || `${metadata.dataset.timestamp_min.slice(0, 10)}–${metadata.dataset.timestamp_max.slice(0, 10)}`
}

export function MethodologySection({ metadata, report, activeSystemId, granularity = 'hour' }: { metadata: AppMetadata; report: ModelReport | null; activeSystemId: string; granularity?: 'hour' | 'day' }) {
  const isDay = granularity === 'day'
  const countWord = isDay ? 'day' : 'hour'
  const reportMatchesSystem = Boolean(report && report.model_family.system_id === activeSystemId)
  return (
    <section id="methodology" className="methodology-section section-anchor section-pad">
      <div className="section-shell">
        <div className="methodology-head">
          <SectionHeading eyebrow="THE METHOD / THE BOUNDARIES" title={<>Clear inputs.<br /><em>Honest outputs.</em></>} copy="Every enabled estimate begins with an observed-demand source, a strict time boundary and an explicitly historical-relative measure." />
          <div className="method-index">METHODOLOGY<br />SERIES / 08</div>
        </div>
        <Reveal className="method-timeline">
          <div className="timeline-heading"><span>THE MODELLING PIPELINE</span><span>NO FUTURE DEMAND IN INPUTS</span></div>
          <div className="timeline-grid">
            {processSteps.map(([number, title, copy], index) => (
              <article className="timeline-step" key={number}>
                <div className="timeline-step-top"><span>{number}</span><i className={index === 7 ? 'last' : ''} /></div>
                <h3>{title}</h3><p>{copy}</p>
                {index < processSteps.length - 1 && <ArrowRight className="timeline-arrow" size={14} aria-hidden="true" />}
              </article>
            ))}
          </div>
          <div className="pipeline-note"><span>AT ORIGIN T−1</span><b>observed station history only</b><ArrowRight size={14} /><b>estimate boardings at target T</b><span>RISK CUTS: TRAIN ONLY</span></div>
        </Reveal>
        <div className="method-explainer-grid">
          <Reveal className="risk-method-card">
            <p className="eyebrow"><span className="eyebrow-dot" /> RISK IS A DISTRIBUTION</p>
            <h3>Percentiles, not capacity.</h3>
            <p>Observed or predicted boardings are compared with frozen training-target percentiles: station/entity when support is sufficient, then its city/mode/operator system, then global. Validation and test values never set the production thresholds.</p>
            <div className="risk-threshold-list">
              <div><span className="risk-step risk-low" /><span>LOW</span><b>≤ P50</b></div>
              <div><span className="risk-step risk-moderate" /><span>MODERATE</span><b>&gt; P50 · ≤ P80</b></div>
              <div><span className="risk-step risk-high" /><span>HIGH</span><b>&gt; P80 · ≤ P95</b></div>
              <div><span className="risk-step risk-severe" /><span>SEVERE</span><b>&gt; P95</b></div>
            </div>
            {reportMatchesSystem && report && <div className="global-thresholds"><span>FITTED GLOBAL FALLBACK · TRAINING ONLY</span><strong>P50 {Math.round(report.demand_risk.global.q50).toLocaleString('en-IN')} <i>/</i> P80 {Math.round(report.demand_risk.global.q80).toLocaleString('en-IN')} <i>/</i> P95 {Math.round(report.demand_risk.global.q95).toLocaleString('en-IN')}</strong><small>{isDay ? 'station entries per day' : 'station boardings per hour'} · adequately sampled station cuts take precedence</small></div>}
          </Reveal>
          <Reveal className="data-transparency-card" delay={0.08} id="data-source">
            <p className="eyebrow"><span className="eyebrow-dot" /> DATA TRANSPARENCY</p>
            <h3>One verified system.<br /><em>A precise scope.</em></h3>
            <div className="source-info-row"><span>DATA SOURCE</span><b>{metadata.dataset.title}</b></div>
            <div className="source-info-row"><span>OBSERVED WINDOWS</span><b>{coverageText(metadata)}</b></div>
            <div className="source-info-row"><span>VERIFIED RECORDS</span><b>{metadata.dataset.observed_rows.toLocaleString()} station-{countWord}s · {metadata.dataset.station_count} source stations{metadata.dataset.unique_days ? ` · ${metadata.dataset.unique_days} distinct days` : ''}</b></div>
            <div className="source-info-row"><span>PRIMARY SIGNAL</span><b>Station boardings · one observed hour</b></div>
            <div className="source-info-row"><span>LICENSE</span><b>{metadata.dataset.license ?? 'ODbL-1.0'}</b></div>
            <div className="source-info-row"><span>FORECAST SCOPE</span><b>{metadata.city} · {metadata.mode} · {metadata.operator} only · {isDay ? 'next-day and future-day' : 'next-hour'} horizon</b></div>
            <a className="source-link" href={metadata.dataset.source_url} target="_blank" rel="noreferrer">Open source repository <ExternalLink size={14} /></a>
            {metadata.dataset.license_url && <a className="source-link secondary-source-link" href={metadata.dataset.license_url} target="_blank" rel="noreferrer">Read the license <ExternalLink size={14} /></a>}
          </Reveal>
        </div>
        <Reveal className="limitations-block">
          <div className="limitations-title"><ShieldAlert size={19} /><div><p className="eyebrow">WHAT THIS MODEL CANNOT KNOW</p><h3>Useful, because it is honest.</h3></div></div>
          <div className="limitations-grid">{limitationItems.map(([title, copy], index) => <div className="limitation-item" key={title}><span>{String(index + 1).padStart(2, '0')}</span><div><strong>{title}</strong><p>{copy}</p></div></div>)}</div>
          <p className="future-note"><b>Future work:</b> an approved, reproducible observed-demand extract with suitable hourly station granularity, explicit reuse terms, longer evaluation history, service-context features, capacity data and calibrated prediction intervals would be prerequisites for expansion. What ships today is an
          empirical per-horizon error band measured on validation days, labelled uncalibrated in every response. GTFS can enrich network discovery, never supply the demand target.</p>
        </Reveal>
      </div>
    </section>
  )
}

export function FinalCallToAction() {
  return (
    <section className="final-cta">
      <div className="cta-topline"><span>INDIA TRANSIT · VERIFIED DATA FIRST</span><span>YOUR NEXT JOURNEY, BETTER INFORMED</span></div>
      <div className="cta-main"><p className="eyebrow"><span className="eyebrow-dot" /> PREDICT THE CROWD. PLAN THE JOURNEY.</p><h2>BEFORE THE<br /><em>CROWD</em> ARRIVES.</h2><ArrowLink href="#predict">Explore the forecast</ArrowLink></div>
      <div className="cta-bottom"><span>INDIA TRANSIT CROWD AI / BMRCL HISTORICAL DEMAND</span><a href="#home">BACK TO TOP <span>↑</span></a></div>
    </section>
  )
}
