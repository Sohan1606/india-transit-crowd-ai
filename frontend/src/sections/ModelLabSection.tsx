import { useMemo, useState } from 'react'
import { Activity, ArrowDown, BadgeCheck, GitCompareArrows } from 'lucide-react'
import type { MetricSet, ModelReport } from '../types/api'
import { NumberTicker, Reveal, SectionHeading } from '../components/ui'

function format(value: unknown, digits = 3): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return value.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function ModelRow({ name, keyName, validation, test, rank, champion, type, scoreWidth }: {
  name: string; keyName: string; validation: MetricSet; test: MetricSet; rank: number; champion: boolean; type: 'regression' | 'classification'; scoreWidth: number
}) {
  const primary = type === 'regression' ? validation.mae : validation.f1_macro
  const metricName = type === 'regression' ? 'VAL MAE · LOWER IS BETTER' : 'VAL MACRO F1 · HIGHER IS BETTER'
  const validationDetail = type === 'regression'
    ? `RMSE ${format(validation.rmse, 1)} · R² ${format(validation.r2, 2)}`
    : `ACC ${format(validation.accuracy, 3)} · W-F1 ${format(validation.f1_weighted, 3)}`
  const testDetail = type === 'regression'
    ? `MAE ${format(test.mae, 1)} · RMSE ${format(test.rmse, 1)} · R² ${format(test.r2, 2)}`
    : `F1 ${format(test.f1_macro, 3)} · ACC ${format(test.accuracy, 3)} · W-F1 ${format(test.f1_weighted, 3)}`
  return (
    <div className={`model-row ${champion ? 'is-champion' : ''}`}>
      <div className="model-rank">{String(rank).padStart(2, '0')}</div>
      <div className="model-name"><strong>{name}</strong><span>{keyName === 'xgboost' ? 'BOOSTED TREES' : keyName === 'random_forest' ? 'BAGGING / ENSEMBLE' : keyName === 'svr' || keyName === 'svm' ? 'SUPPORT VECTOR MACHINE' : keyName.replaceAll('_', ' ').toUpperCase()}</span></div>
      <div className="model-bar-wrap"><div className="model-bar-label"><span>{metricName}</span><strong>{format(primary, type === 'regression' ? 1 : 3)}</strong></div><div className="model-bar"><span style={{ width: `${scoreWidth}%` }} /></div></div>
      <div className="model-val-cell"><span>{type === 'regression' ? 'VALIDATION RMSE / R²' : 'VALIDATION ACC / WEIGHTED F1'}</span><strong>{validationDetail}</strong></div>
      <div className="model-val-cell model-test-cell"><span>{type === 'regression' ? 'UNTOUCHED TEST · MAE / RMSE / R²' : 'UNTOUCHED TEST · MACRO F1 / ACC / W-F1'}</span><strong>{testDetail}</strong></div>
      {champion && <span className="champion-chip"><BadgeCheck size={13} /> VALIDATION CHAMPION</span>}
    </div>
  )
}

function ConfusionMatrix({ metrics }: { metrics: MetricSet }) {
  const matrix = metrics.confusion_matrix
  const labels = metrics.class_order ?? ['LOW', 'MODERATE', 'HIGH', 'SEVERE']
  if (!matrix || !matrix.length) return <p className="data-empty-inline">No confusion matrix is available.</p>
  const max = Math.max(...matrix.flat(), 1)
  return (
    <div className="confusion-wrap">
      <p className="matrix-caption">TEST CONFUSION MATRIX <span>ROWS = ACTUAL · COLUMNS = PREDICTED</span></p>
      <div className="confusion-matrix" role="table" aria-label="Test confusion matrix">
        <div className="matrix-corner">A ↓ / P →</div>{labels.map((label) => <div className="matrix-axis" key={`head-${label}`}>{label.slice(0, 3)}</div>)}
        {matrix.map((row, rowIndex) => <div className="matrix-row" key={labels[rowIndex]}>
          <span className="matrix-axis">{labels[rowIndex].slice(0, 3)}</span>
          {row.map((value, colIndex) => <span key={`${rowIndex}-${colIndex}`} className={`matrix-cell ${rowIndex === colIndex ? 'is-diagonal' : ''}`} style={{ '--matrix-alpha': value / max } as React.CSSProperties} aria-label={`Actual ${labels[rowIndex]}, predicted ${labels[colIndex]}: ${value}`}>{value.toLocaleString()}</span>)}
        </div>)}
      </div>
    </div>
  )
}

export function ModelLabSection({ report, activeSystemId }: { report: ModelReport | null; activeSystemId: string }) {
  const [tab, setTab] = useState<'regression' | 'classification'>('regression')
  const reportMatchesSystem = Boolean(report && report.model_family.system_id === activeSystemId)
  const regressionModels = reportMatchesSystem ? report?.regression.models ?? [] : []
  const classificationModels = reportMatchesSystem ? report?.classification.models ?? [] : []
  const championClass = classificationModels.find((model) => model.key === report?.classification.champion_key)
  const highReport = championClass?.test.classification_report?.HIGH
  const severeReport = championClass?.test.classification_report?.SEVERE
  const selectedModels = tab === 'regression' ? regressionModels : classificationModels
  const scoreValues = selectedModels.map((model) => Number(tab === 'regression' ? model.validation.mae : model.validation.f1_macro)).filter(Number.isFinite)
  const scoreMin = scoreValues.length ? Math.min(...scoreValues) : 0
  const scoreMax = scoreValues.length ? Math.max(...scoreValues) : 0
  const scoreWidth = (value: number | undefined) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) return 4
    if (tab === 'regression') return scoreMax === scoreMin ? 100 : Math.max(14, 100 - ((value - scoreMin) / (scoreMax - scoreMin)) * 78)
    return scoreMax === 0 ? 4 : Math.max(4, Math.min(100, value / scoreMax * 100))
  }
  const bestRegression = useMemo(() => reportMatchesSystem ? report?.regression.models.find((model) => model.key === report.regression.champion_key) : undefined, [report, reportMatchesSystem])
  const bestClassifier = championClass
  return (
    <section id="models" className="model-section section-anchor section-pad">
      <div className="section-shell">
        <div className="model-intro-row">
          <SectionHeading eyebrow="THE MODEL LAB" title={<>Measured, not<br /><em>assumed.</em></>} copy="Six regression candidates and six classifiers. Champions are selected on chronological validation—not on a label or a promise." />
          <div className="model-eval-note"><GitCompareArrows size={17} /><span>FINAL TEST<br />REMAINS UNTOUCHED</span></div>
        </div>
        {!reportMatchesSystem ? <div className="unsupported-panel analytics-unavailable" role="status"><p className="eyebrow">NO BENCHMARK FOR THIS SYSTEM</p><h3>Model results are system-specific.</h3><p>The displayed benchmark is only for Bengaluru Namma Metro/BMRCL's verified historical station-hour boardings. No scores are inferred for this selected system.</p></div> : !report ? <div className="analytics-loading"><span className="chart-spinner" />Loading saved model evaluation…</div> : (
          <Reveal className="model-lab-frame">
            <div className="model-lab-top"><span>MODEL PERFORMANCE / {report.model_version.toUpperCase()}</span><span>{report.training_timestamp_utc.slice(0, 10)} · CHRONOLOGICAL HOLDOUT</span></div>
            <div className="model-overview">
              <div className="model-stat"><span>SUPERVISED ROWS</span><strong><NumberTicker value={report.dataset.supervised_rows} /></strong><small>station-hour targets</small></div>
              <div className="model-stat"><span>ENGINEERED INPUTS</span><strong>{report.feature_schema.feature_count.toString().padStart(2, '0')}</strong><small>calendar + lagged demand</small></div>
              <div className="model-stat"><span>TRAIN / VALIDATE / TEST</span><strong>{report.split.train.rows.toLocaleString()} <i>/</i> {report.split.validation.rows.toLocaleString()} <i>/</i> {report.split.test.rows.toLocaleString()}</strong><small>chronological samples</small></div>
              <div className="model-stat"><span>TIME-SERIES CV</span><strong>{report.cross_validation.n_splits} folds</strong><small>expanding window · no shuffle</small></div>
            </div>
            <div className="champion-spotlight-grid">
              <article className="champion-spotlight"><span className="champion-number">01</span><div><p className="eyebrow"><BadgeCheck size={13} /> VALIDATION CHAMPION · REGRESSION</p><h3>{report.regression.champion_name}</h3><p>Chosen by lowest validation MAE. Latest-period test metrics remain a separate final measure.</p></div><div className="champion-metric"><span>TEST MAE</span><strong>{bestRegression ? format(bestRegression.test.mae, 1) : '—'}</strong><small>boardings / hour</small></div></article>
              <article className="champion-spotlight champion-classifier"><span className="champion-number">02</span><div><p className="eyebrow"><BadgeCheck size={13} /> VALIDATION CHAMPION · CLASSIFICATION</p><h3>{report.classification.champion_name}</h3><p>Chosen by validation macro F1; HIGH and SEVERE class recall is shown below.</p></div><div className="champion-metric"><span>TEST MACRO F1</span><strong>{bestClassifier ? format(bestClassifier.test.f1_macro) : '—'}</strong><small>four historical-relative bands</small></div></article>
            </div>
            <div className="model-tab-row" role="tablist" aria-label="Model task">
              <button type="button" role="tab" aria-selected={tab === 'regression'} className={tab === 'regression' ? 'is-current' : ''} onClick={() => setTab('regression')}><Activity size={14} /> REGRESSION <span>06</span></button>
              <button type="button" role="tab" aria-selected={tab === 'classification'} className={tab === 'classification' ? 'is-current' : ''} onClick={() => setTab('classification')}><GitCompareArrows size={14} /> CLASSIFICATION <span>06</span></button>
            </div>
            <div className="model-table" role="tabpanel" aria-label={`${tab} benchmark results`}>
              <div className="model-table-heading"><span>MODEL</span><span>VALIDATION SIGNAL</span><span>SECONDARY METRIC</span><span>UNTOUCHED TEST</span><span>RANK</span></div>
              {selectedModels.map((model) => <ModelRow key={model.key} name={model.name} keyName={model.key} validation={model.validation} test={model.test} rank={model.validation_rank} champion={model.key === (tab === 'regression' ? report.regression.champion_key : report.classification.champion_key)} type={tab} scoreWidth={scoreWidth(Number(model.validation[tab === 'regression' ? 'mae' : 'f1_macro']))} />)}
            </div>
            {tab === 'classification' && championClass && (
              <div className="class-diagnostics">
                <ConfusionMatrix metrics={championClass.test} />
                <div className="class-recall-panel"><p className="matrix-caption">CLASS-SPECIFIC TEST RECALL <span>DO NOT HIDE THE HARD CLASSES</span></p>
                  <div className="recall-pair"><div><span>HIGH</span><strong>{highReport ? `${(highReport.recall * 100).toFixed(1)}%` : '—'}</strong><small>{highReport?.support?.toLocaleString() ?? '0'} test samples</small></div><div><span>SEVERE</span><strong>{severeReport ? `${(severeReport.recall * 100).toFixed(1)}%` : '—'}</strong><small>{severeReport?.support?.toLocaleString() ?? '0'} test samples</small></div></div>
                  <p className="recall-note">Precision, recall, macro F1, weighted F1, Cohen's κ and ROC-AUC where probabilities are available are included in the model report.</p>
                </div>
              </div>
            )}
            <div className="cv-footnote"><ArrowDown size={14} /><p><b>Chronology:</b> {report.split.strategy} Split windows: train {report.split.train.start.slice(0, 10)}—{report.split.train.end.slice(0, 10)} · validation {report.split.validation.start.slice(0, 10)}—{report.split.validation.end.slice(0, 10)} · test {report.split.test.start.slice(0, 10)}—{report.split.test.end.slice(0, 10)}.</p></div>
          </Reveal>
        )}
        <div className="model-disclaimer"><span>INTERPRET WITH CARE</span><p>Holdout errors are from the most recent historical portion of a short, discontinuous 2025 snapshot—not a guarantee about 2026 service. They do not establish annual seasonality or physical occupancy.</p></div>
      </div>
    </section>
  )
}
