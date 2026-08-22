import type { ReactNode } from 'react'

export type InlineAlertProps = {
  tone: 'info' | 'warning' | 'error' | 'success'
  title: string
  children?: ReactNode
}

export default function InlineAlert({ tone, title, children }: InlineAlertProps) {
  return (
    <div className={`inline-alert inline-alert--${tone}`} role="alert">
      <p className="inline-alert__title">{title}</p>
      {children && <div className="inline-alert__content">{children}</div>}
    </div>
  )
}
