import type { ReactNode } from 'react'

export default function SummaryStrip({ label, items, className }: {
  label: string
  items: Array<{ label: string; value: ReactNode }>
  className?: string
}) {
  return (
    <section className={['summary-strip', className].filter(Boolean).join(' ')} aria-label={label}>
      {items.map((item) => <div className="summary-strip__item" key={item.label}><span>{item.label}</span><strong>{item.value}</strong></div>)}
    </section>
  )
}
