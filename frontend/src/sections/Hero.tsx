import { motion, useReducedMotion } from 'framer-motion'
import { ArrowDown } from 'lucide-react'

function SignalMap() {
  return (
    <div className="signal-visual" aria-label="Abstract animated transit-demand motif; not a live map or observed station geography">
      <div className="signal-topline"><span>DEMAND SIGNAL / 01</span><span className="signal-live"><i /> MODEL INPUT</span></div>
      <svg className="signal-svg" viewBox="0 0 620 500" role="img" aria-labelledby="signal-title signal-desc">
        <title id="signal-title">Abstract transit-demand signal</title>
        <desc id="signal-desc">A decorative, non-geographic network motif; lines and nodes are not real routes or stations.</desc>
        <defs>
          <linearGradient id="routeGradient" x1="0" x2="1" y1="1" y2="0">
            <stop offset="0%" stopColor="#c7ee7b" stopOpacity=".12" />
            <stop offset="55%" stopColor="#c7ee7b" stopOpacity=".75" />
            <stop offset="100%" stopColor="#e9eee0" stopOpacity=".22" />
          </linearGradient>
          <radialGradient id="pulseGlow"><stop stopColor="#c7ee7b" stopOpacity=".5" /><stop offset="1" stopColor="#c7ee7b" stopOpacity="0" /></radialGradient>
        </defs>
        <g className="signal-grid-lines">
          <path d="M55 60H570M55 120H570M55 180H570M55 240H570M55 300H570M55 360H570M55 420H570" />
          <path d="M100 35V450M190 35V450M280 35V450M370 35V450M460 35V450M550 35V450" />
        </g>
        <g className="signal-routes">
          <path className="route-path route-path-main" d="M38 362 C110 360 108 278 181 278 S246 199 309 199 S394 224 432 148 S504 107 585 108" />
          <path className="route-path route-path-secondary" d="M93 73 C165 74 156 153 225 153 S284 230 346 230 S420 327 487 327 S548 390 588 390" />
          <path className="route-path route-path-tertiary" d="M89 439 C155 428 175 367 226 367 S286 308 335 308 S402 354 450 354 S520 268 587 259" />
          <path className="route-path route-path-fine" d="M39 160 C93 160 119 205 169 205 S231 123 272 123 S338 79 376 79 S435 120 474 120 S530 182 587 182" />
        </g>
        <g className="signal-pulses">
          <circle cx="180" cy="278" r="42" fill="url(#pulseGlow)" />
          <circle cx="309" cy="199" r="55" fill="url(#pulseGlow)" />
          <circle cx="432" cy="148" r="38" fill="url(#pulseGlow)" />
        </g>
        <g className="signal-nodes">
          {[[38,362],[181,278],[309,199],[432,148],[585,108],[93,73],[225,153],[346,230],[487,327],[588,390],[89,439],[226,367],[335,308],[450,354],[587,259],[39,160],[169,205],[272,123],[376,79],[474,120],[587,182]].map(([cx, cy], index) => (
            <g key={`${cx}-${cy}`} className={index % 5 === 0 ? 'node node-highlight' : 'node'}>
              <circle className="node-halo" cx={cx} cy={cy} r="8" />
              <circle className="node-core" cx={cx} cy={cy} r={index % 5 === 0 ? '3.5' : '2.3'} />
            </g>
          ))}
        </g>
        <circle className="data-traveler" r="4" fill="#c7ee7b">
          <animateMotion dur="8s" repeatCount="indefinite" path="M38 362 C110 360 108 278 181 278 S246 199 309 199 S394 224 432 148 S504 107 585 108" />
        </circle>
      </svg>
      <div className="signal-foot"><span>HISTORICAL DEMAND → FORECAST</span><span>01 — 24H</span></div>
      <p className="signal-caption">Abstract data motif · not a geographic or live service map</p>
    </div>
  )
}

export function Hero({ onExplore }: { onExplore: () => void }) {
  const reduce = useReducedMotion()
  const transition = { duration: reduce ? 0 : 0.8, ease: [0.2, 0.75, 0.2, 1] as const }
  return (
    <section id="home" className="hero section-anchor">
      <div className="hero-kicker"><span className="eyebrow-dot" /> TRANSIT INTELLIGENCE <span className="hero-kicker-right">INDIA / MULTIMODAL / 01</span></div>
      <div className="hero-grid-layout">
        <div className="hero-copy">
          <motion.p className="hero-index" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.6 }}>A CLEARER WAY THROUGH THE CITY</motion.p>
          <h1 aria-label="Know the crowd before you enter it">
            <motion.span initial={{ opacity: 0, y: 36 }} animate={{ opacity: 1, y: 0 }} transition={{ ...transition, delay: reduce ? 0 : 0.1 }}>KNOW THE</motion.span>
            <motion.span className="hero-word-accent" initial={{ opacity: 0, y: 36 }} animate={{ opacity: 1, y: 0 }} transition={{ ...transition, delay: reduce ? 0 : 0.19 }}>CROWD</motion.span>
            <motion.span initial={{ opacity: 0, y: 36 }} animate={{ opacity: 1, y: 0 }} transition={{ ...transition, delay: reduce ? 0 : 0.28 }}>BEFORE YOU</motion.span>
            <motion.span initial={{ opacity: 0, y: 36 }} animate={{ opacity: 1, y: 0 }} transition={{ ...transition, delay: reduce ? 0 : 0.37 }}>ENTER IT<span className="hero-period">.</span></motion.span>
          </h1>
          <motion.div className="hero-under" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.7, delay: reduce ? 0 : 0.52 }}>
            <p>Discover the three registered Indian transit demand families. Forecasts are served from saved model artifacts at the resolution each family actually supports.</p>
            <div className="hero-actions">
              <button className="arrow-link" type="button" onClick={onExplore}>Explore prediction <span className="button-arrow" aria-hidden="true">↗</span></button>
              <a className="text-link" href="#methodology"><span className="text-link-icon"><ArrowDown size={14} /></span> How it works</a>
            </div>
          </motion.div>
        </div>
        <SignalMap />
      </div>
      <div className="hero-bottom"><span>DEMAND HAS A RHYTHM.</span><span>SCROLL TO ENTER THE ENGINE <span aria-hidden="true">↓</span></span><span>3 REGISTERED FAMILIES / MULTI-GRANULARITY</span></div>
    </section>
  )
}
