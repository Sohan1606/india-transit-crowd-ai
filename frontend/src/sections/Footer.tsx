import { ArrowUpRight, ExternalLink } from 'lucide-react'

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="footer-main">
        <a className="brand footer-brand" href="#home" aria-label="India Transit Crowd AI, back to top">
          <span className="brand-symbol" aria-hidden="true"><span /><span /><span /></span>
          <span>INDIA <span className="brand-light">TRANSIT</span><i> CROWD AI</i></span>
        </a>
        <p>PREDICT THE CROWD.<br />PLAN THE JOURNEY.</p>
        <div className="footer-links">
          <a href="#systems">Data source <ArrowUpRight size={12} /></a>
          <a href="#methodology">Methodology <ArrowUpRight size={12} /></a>
          <a href="#methodology">Model notes <ArrowUpRight size={12} /></a>
          <a href="https://github.com/Sohan1606/india-transit-crowd-ai" target="_blank" rel="noreferrer">GitHub <ExternalLink size={12} /></a>
        </div>
      </div>
      <div className="footer-bottom"><span>© 2026 INDIA TRANSIT CROWD AI / ACADEMIC PROJECT</span><span>PASSENGER DEMAND FORECASTS / NOT PHYSICAL OCCUPANCY</span><a href="#home">TOP ↑</a></div>
    </footer>
  )
}
