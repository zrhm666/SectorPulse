import { useId, type ReactNode } from 'react'

export type PanelProps = {
  title?: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
}

export default function Panel({ title, description, actions, children, className }: PanelProps) {
  const titleId = useId()

  return (
    <section className={['panel', className].filter(Boolean).join(' ')} aria-labelledby={title ? titleId : undefined}>
      {(title || description || actions) && (
        <header className="panel__header">
          <div className="panel__heading">
            {title && <h2 className="panel__title" id={titleId}>{title}</h2>}
            {description && <p className="panel__description">{description}</p>}
          </div>
          {actions && <div className="panel__actions">{actions}</div>}
        </header>
      )}
      <div className="panel__body">{children}</div>
    </section>
  )
}
