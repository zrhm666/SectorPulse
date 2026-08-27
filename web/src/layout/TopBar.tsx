import type { RefObject } from 'react'
import { useLocation } from 'react-router-dom'
import Button from '../components/ui/Button'
import { resolveRouteContext } from './routeContext'

export type TopBarProps = {
  navOpen: boolean
  onToggleNavigation: () => void
  menuButtonRef: RefObject<HTMLButtonElement>
}

export default function TopBar({ menuButtonRef, navOpen, onToggleNavigation }: TopBarProps) {
  const context = resolveRouteContext(useLocation().pathname)

  return (
    <header className="top-bar">
      <a className="skip-link" href="#main-content">跳到主内容</a>
      <Button ref={menuButtonRef} className="top-bar__menu" variant="secondary" size="compact" type="button" onClick={onToggleNavigation} aria-label="打开导航" aria-expanded={navOpen} aria-controls="primary-navigation" icon="menu">
        菜单
      </Button>
      <div className="top-bar__context" aria-label="当前位置">
        <strong>{context.group}</strong><span aria-hidden="true">/</span><span>{context.label}</span>
      </div>
    </header>
  )
}
