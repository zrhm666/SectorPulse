import { useEffect, useRef, useState } from 'react'
import { Outlet } from 'react-router-dom'
import SidebarNav from './SidebarNav'
import TopBar from './TopBar'
import { NAV_ITEMS } from './navigation'
import FeedbackProvider from '../components/ui/FeedbackProvider'
import useMediaQuery from '../hooks/useMediaQuery'

export default function AppShell() {
  const [navOpen, setNavOpen] = useState(false)
  const isNarrow = useMediaQuery('(max-width: 1024px)')
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const previousNavOpenRef = useRef(navOpen)

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setNavOpen(false) }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [])

  useEffect(() => {
    if (previousNavOpenRef.current && !navOpen) menuButtonRef.current?.focus()
    previousNavOpenRef.current = navOpen
  }, [navOpen])

  return (
    <div className="app-shell" data-navigation-open={navOpen}>
      <SidebarNav items={NAV_ITEMS} open={navOpen} isNarrow={isNarrow} onClose={() => setNavOpen(false)} />
      <div className="app-shell__body">
        <TopBar menuButtonRef={menuButtonRef} navOpen={navOpen} onToggleNavigation={() => setNavOpen((open) => !open)} />
        <FeedbackProvider><main className="app-main" id="main-content" tabIndex={0}><Outlet /></main></FeedbackProvider>
      </div>
    </div>
  )
}
