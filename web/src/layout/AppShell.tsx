import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import SidebarNav from './SidebarNav'
import TopBar from './TopBar'
import { NAV_ITEMS } from './navigation'
import FeedbackProvider from '../components/ui/FeedbackProvider'

export default function AppShell() {
  const [navOpen, setNavOpen] = useState(false)

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setNavOpen(false) }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [])

  return (
    <div className="app-shell">
      <SidebarNav items={NAV_ITEMS} open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="app-shell__body">
        <TopBar navOpen={navOpen} onToggleNavigation={() => setNavOpen((open) => !open)} />
        <FeedbackProvider><main className="app-main" id="main-content" tabIndex={0}><Outlet /></main></FeedbackProvider>
      </div>
    </div>
  )
}
