import { ArrowDown } from 'lucide-react'
import { Reveal } from '../components/ui'

const steps = [
  ['01', 'OBSERVED', 'Station boardings by hour'],
  ['02', 'ENGINEERED', 'History before target time'],
  ['03', 'FORECAST', 'A bounded model estimate'],
]

export function SignalTransition() {
  return (
    <section className="signal-transition" aria-label="Forecast sequence">
      <div className="transition-beam" aria-hidden="true"><span /><span /><span /><span /><span /><span /><span /></div>
      <Reveal className="transition-content">
        <div className="transition-heading">
          <p className="eyebrow"><span className="eyebrow-dot" /> FROM SIGNAL TO DECISION</p>
          <h2>OBSERVE. <span>UNDERSTAND.</span><br />MOVE WITH INTENT.</h2>
        </div>
        <div className="transition-sequence">
          {steps.map(([number, title, copy], index) => (
            <div className="transition-step" key={number}>
              <span className="transition-num">{number}</span>
              <strong>{title}</strong>
              <span>{copy}</span>
              {index < steps.length - 1 && <ArrowDown className="transition-arrow" size={16} aria-hidden="true" />}
            </div>
          ))}
        </div>
      </Reveal>
    </section>
  )
}
