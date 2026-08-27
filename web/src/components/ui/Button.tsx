import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import AppIcon, { type AppIconName } from './AppIcon'

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'default' | 'compact'
  icon?: AppIconName
  loading?: boolean
  loadingLabel?: string
  children: ReactNode
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({
  variant = 'primary',
  size = 'default',
  icon,
  loading = false,
  loadingLabel = '处理中',
  className,
  disabled,
  children,
  ...buttonProps
}, ref) {
  return (
    <button
      {...buttonProps}
      ref={ref}
      className={['button', `button--${variant}`, `button--${size}`, className].filter(Boolean).join(' ')}
      data-variant={variant}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
    >
      {loading ? (
        <><span className="button__spinner" aria-hidden="true" /><span>{loadingLabel}</span></>
      ) : (
        <>{icon && <AppIcon name={icon} />}<span>{children}</span></>
      )}
    </button>
  )
})

export default Button
