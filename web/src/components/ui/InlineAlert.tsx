import type { ReactNode } from 'react'
import AppIcon from './AppIcon'

export type InlineAlertProps = {
  tone: 'info' | 'warning' | 'error' | 'success'
  title: string
  children?: ReactNode
}

export default function InlineAlert({ tone, title, children }: InlineAlertProps) {
  return (
    <div className={`inline-alert inline-alert--${tone}`} role="alert">
      <span className="inline-alert__icon"><AppIcon name={tone === 'success' ? 'check' : 'warning'} /></span>
      <div><p className="inline-alert__title">{title}</p>
      {children && <div className="inline-alert__content">{children}</div>}</div>
    </div>
  )
}
