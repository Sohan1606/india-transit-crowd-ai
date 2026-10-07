import { Scatter, ScatterChart, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, ZAxis } from 'recharts'
import { Binary, CircleDot, Focus } from 'lucide-react'
import type { StationAnalytics, StationAnalyticsPoint } from '../types/api'
import { Reveal, SectionHeading } from '../components/ui'

const clusterPalette = ['#c7ee7b', '#83b8a9', '#83a4cc', '#d4a681', '#bc9cbd', '#88bfca', '#d4c176']
const clusterColor = (id: number) => id === -1 ? '#e6ad6a' : clusterPalette[Math.abs(id) % clusterPalette.length]

function ProjectionTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: StationAnalyticsPoint }> }) {
  const point = payload?.[0]?.payload
  if (!active || !point) return null
  return (
    <div className="chart-tooltip pca-tooltip">
      <span>STATION PROFILE / {point.entity_name}</span>
      <strong>{point.is_outlier ? 'DBSCAN NOISE POINT' : `CLUSTER ${point.cluster_id}`}</strong>
      <div className="pca-tooltip-values"><span>Mean <b>{Math.round(point.behaviour.mean_demand).toLocaleString('en-IN')}</b></span><span>Peak / avg <b>{point.behaviour.peak_to_average_ratio.toFixed(2)}×</b></span><span>Weekend <b>{Math.round(point.behaviour.weekend_mean).toLocaleString('en-IN')}</b></span></div>
    </div>
  )
}

export function StationAnalyticsSection({ analytics, available }: { analytics: StationAnalytics | null; available: boolean }) {
  const clusters = analytics?.dbscan.clusters ?? []
  const noiseCount = analytics?.dbscan.outlier_count ?? 0
  return (
    <section id="insights" className="analytics-section section-anchor section-pad">
      <div className="section-shell">
        <div className="analytics-intro">
          <SectionHeading eyebrow="UNSUPERVISED STATION PROFILES" title={<>Different stations.<br /><em>Different rhythms.</em></>} copy="Summarize the selected family’s station/entity behavior, project observed-demand features with PCA and group density patterns using DBSCAN." />
          <div className="pca-stamp"><Binary size={22} /><span>UNSUPERVISED<br />LEARNING / 02</span></div>
        </div>
        {!available ? <div className="unsupported-panel analytics-unavailable" role="status"><p className="eyebrow">NO PROFILE FOR THIS SYSTEM</p><h3>Station profiles are not synthesized from schedules.</h3><p>Return to the selected model family to inspect its available station/entity profiles.</p></div> : !analytics ? <div className="analytics-loading"><span className="chart-spinner" />Loading PCA / DBSCAN result…</div> : (
          <Reveal className="projection-frame">
            <div className="projection-topline"><span>STATION BEHAVIOUR / PCA PROJECTION</span><span>{analytics.entity_count} OBSERVED STATIONS · TRAINING-PERIOD FEATURES</span></div>
            <div className="projection-layout">
              <div className="projection-chart" role="img" aria-label="PCA projection of station behaviour features coloured by DBSCAN cluster">
                <ResponsiveContainer width="100%" height="100%">
                  <ScatterChart margin={{ top: 18, right: 24, bottom: 14, left: 8 }}>
                    <CartesianGrid stroke="#2b2f28" strokeDasharray="2 6" />
                    <XAxis type="number" dataKey="pc1" name="Principal component 1" tick={{ fill: '#858980', fontSize: 10 }} tickLine={false} axisLine={{ stroke: '#41463e' }} label={{ value: 'PC 1', position: 'insideBottomRight', offset: -6, fill: '#858980', fontSize: 10 }} />
                    <YAxis type="number" dataKey="pc2" name="Principal component 2" tick={{ fill: '#858980', fontSize: 10 }} tickLine={false} axisLine={{ stroke: '#41463e' }} label={{ value: 'PC 2', angle: -90, position: 'insideLeft', fill: '#858980', fontSize: 10 }} />
                    <ZAxis range={[90, 90]} />
                    <Tooltip content={<ProjectionTooltip />} cursor={{ strokeDasharray: '3 4', stroke: '#777d70' }} />
                    {Array.from(new Set(analytics.entities.map((point) => point.cluster_id))).map((clusterId) => {
                      const subset = analytics.entities.filter((point) => point.cluster_id === clusterId)
                      return <Scatter key={clusterId} name={clusterId === -1 ? 'Noise / outlier' : `Cluster ${clusterId}`} data={subset} fill={clusterColor(clusterId)} isAnimationActive={false}>
                        {subset.map((point) => <Cell key={point.entity_id} fill={clusterColor(point.cluster_id)} stroke="#10120f" strokeWidth={2} />)}
                      </Scatter>
                    })}
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
              <aside className="projection-aside">
                <div className="projection-stat"><span>VARIANCE RETAINED</span><strong>{(analytics.pca.total_explained_variance_ratio * 100).toFixed(1)}<small>%</small></strong><p>Across principal components 1 + 2.</p></div>
                <div className="projection-stat"><span>DBSCAN GROUPS</span><strong>{analytics.dbscan.cluster_count_excluding_noise.toString().padStart(2, '0')}</strong><p>Density-derived clusters · min samples {analytics.dbscan.min_samples}.</p></div>
                <div className="projection-stat projection-stat-outlier"><span>NOISE / OUTLIERS</span><strong>{noiseCount.toString().padStart(2, '0')}</strong><p>Stations not assigned to a dense cluster.</p></div>
                <div className="projection-note"><Focus size={15} /><p>Hover a point for its observed station profile and algorithm-assigned cluster.</p></div>
              </aside>
            </div>
            <div className="cluster-meta">
              {clusters.map((cluster) => (
                <div className="cluster-meta-card" key={cluster.cluster_id}>
                  <span className="cluster-marker" style={{ background: clusterColor(cluster.cluster_id) }} /><span>CLUSTER {cluster.cluster_id}</span><strong>{cluster.entity_count.toString().padStart(2, '0')} stations</strong><small>{cluster.entities.map((id) => analytics.entities.find((item) => item.entity_id === id)?.entity_name ?? id).join(' · ')}</small>
                </div>
              ))}
              {noiseCount > 0 && <div className="cluster-meta-card is-noise"><span className="cluster-marker" style={{ background: clusterColor(-1) }} /><span>NOISE / OUTLIERS</span><strong>{noiseCount.toString().padStart(2, '0')} stations</strong><small>{analytics.dbscan.outlier_entity_ids.map((id) => analytics.entities.find((item) => item.entity_id === id)?.entity_name ?? id).join(' · ')}</small></div>}
              {clusters.length === 0 && noiseCount === 0 && <p className="cluster-none">DBSCAN found no dense clusters or noise points at the fitted parameters.</p>}
            </div>
            <div className="projection-method"><CircleDot size={14} /><span>{analytics.method}. ε = {analytics.dbscan.eps.toFixed(3)} · k = {analytics.dbscan.min_samples}. {analytics.interpretation_note}</span></div>
          </Reveal>
        )}
      </div>
    </section>
  )
}
