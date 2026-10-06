import { useEffect, useState } from 'react'
import { Menu, X } from 'lucide-react'

const links = [
  ['home', 'Home'], ['systems', 'Systems'], ['predict', 'Forecast'], ['demand', 'Observed'],
  ['stations', 'Stations'], ['models', 'Models'], ['insights', 'Profiles'], ['methodology', 'Method'],
] as const

export function Navigation() {
  const [active, setActive] = useState('home')
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return
    const targets = links.map(([id]) => document.getElementById(id)).filter((node): node is HTMLElement => Boolean(node))
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
      if (visible) setActive(visible.target.id)
    }, { rootMargin: '-22% 0px -66% 0px', threshold: [0, 0.1, 0.25, 0.5] })
    targets.forEach((target) => observer.observe(target))
    return () => observer.disconnect()
  }, [])

  const close = () => setOpen(false)
  return (
    <header className="site-header">
      <a className="brand" href="#home" onClick={close} aria-label="India Transit Crowd AI home">
        <span className="brand-symbol" aria-hidden="true"><span /><span /><span /></span>
        <span>INDIA <span className="brand-light">TRANSIT</span><i> CROWD AI</i></span>
      </a>
      <button className="mobile-menu-toggle" aria-expanded={open} aria-controls="primary-navigation" aria-label={open ? 'Close navigation menu' : 'Open navigation menu'} onClick={() => setOpen(!open)}>
        {open ? <X size={20} /> : <Menu size={20} />}
      </button>
      <nav id="primary-navigation" className={`primary-navigation ${open ? 'is-open' : ''}`} aria-label="Primary navigation">
        {links.map(([id, label]) => (
          <a key={id} href={`#${id}`} className={active === id ? 'is-active' : ''} aria-current={active === id ? 'location' : undefined} onClick={close}>
            {label}
          </a>
        ))}
      </nav>
      <a className="nav-cta" href="#predict" onClick={close}>Explore forecast <span aria-hidden="true">↗</span></a>
    </header>
  )
}
