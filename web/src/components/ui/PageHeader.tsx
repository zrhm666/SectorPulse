import type { ReactNode } from 'react'

export type PageHeaderProps = {
  title: string
  description?: string
  eyebrow?: string
  meta?: ReactNode
  actions?: ReactNode
}

export default function PageHeader({ title, description, eyebrow, meta, actions }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-header__content">
        {eyebrow && <p className="page-header__eyebrow">{eyebrow}</p>}
        <h1 className="page-header__title">{title}</h1>
        {description && <p className="page-header__description">{description}</p>}
      </div>
      {(meta || actions) && (
        <div className="page-header__aside">
          {meta && <div className="page-header__meta">{meta}</div>}
          {actions && <div className="page-header__actions">{actions}</div>}
        </div>
      )}
    </header>
  )
}
