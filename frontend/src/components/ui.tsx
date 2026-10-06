import { useEffect, useRef, type ReactNode } from 'react'
import { animate, motion, useInView, useMotionValue, useReducedMotion, useTransform } from 'framer-motion'
import { ArrowDownRight, ArrowUpRight } from 'lucide-react'
import type { Risk } from '../types/api'

export function Reveal({ children, className = '', delay = 0, once = true, id }: { children: ReactNode; className?: string; delay?: number; once?: boolean; id?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const visible = useInView(ref, { once, margin: '0px 0px -12% 0px' })
  const reduce = useReducedMotion()
  return (
    <motion.div
      ref={ref}
      className={className}
      id={id}
      initial={reduce ? false : { opacity: 0, y: 22 }}
      animate={reduce || visible ? { opacity: 1, y: 0 } : { opacity: 0, y: 22 }}
      transition={{ duration: reduce ? 0 : 0.72, ease: [0.2, 0.75, 0.2, 1], delay: reduce ? 0 : delay }}
    >
      {children}
    </motion.div>
  )
}

export function NumberTicker({ value, decimals = 0, className = '' }: { value: number; decimals?: number; className?: string }) {
  const motionValue = useMotionValue(0)
  const rounded = useTransform(motionValue, (latest) => latest.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }))
  const reduce = useReducedMotion()
  useEffect(() => {
    const controls = animate(motionValue, value, { duration: reduce ? 0 : 0.85, ease: 'easeOut' })
    return () => controls.stop()
  }, [motionValue, reduce, value])
  return <motion.span className={className} aria-label={value.toLocaleString('en-US', { maximumFractionDigits: decimals })}>{rounded}</motion.span>
}

export function SectionHeading({ eyebrow, title, copy, className = '' }: { eyebrow: string; title: ReactNode; copy?: ReactNode; className?: string }) {
  return (
    <div className={`section-heading ${className}`}>
      <p className="eyebrow"><span className="eyebrow-dot" />{eyebrow}</p>
      <h2>{title}</h2>
      {copy && <p className="section-copy">{copy}</p>}
    </div>
  )
}

export function RiskBadge({ risk, className = '' }: { risk: Risk; className?: string }) {
  return (
    <span className={`risk-badge risk-${risk.toLowerCase()} ${className}`}>
      <span className="risk-pip" aria-hidden="true" />
      {risk}
    </span>
  )
}

export function ArrowLink({ children, href, onClick, secondary = false, className = '' }: {
  children: ReactNode; href?: string; onClick?: () => void; secondary?: boolean; className?: string
}) {
  const content = <>{children}<span className="button-arrow" aria-hidden="true">{secondary ? <ArrowDownRight size={16} /> : <ArrowUpRight size={16} />}</span></>
  if (href) return <a className={`arrow-link ${secondary ? 'arrow-link-secondary' : ''} ${className}`} href={href}>{content}</a>
  return <button type="button" className={`arrow-link ${secondary ? 'arrow-link-secondary' : ''} ${className}`} onClick={onClick}>{content}</button>
}

export function DataLine({ label, value }: { label: string; value: ReactNode }) {
  return <div className="data-line"><span>{label}</span><strong>{value}</strong></div>
}
