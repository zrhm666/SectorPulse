import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import SidebarNav from './SidebarNav'
import TopBar from './TopBar'
import { NAV_ITEMS } from './navigation'

export default function AppShell() {
  const [navOpen, setNavOpen] = useState(false)

  return (
    <div className="app-shell">
      <SidebarNav items={NAV_ITEMS} open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="app-shell__body">
        <TopBar onOpenNavigation={() => setNavOpen(true)} />
        <main className="app-main" id="main-content"><Outlet /></main>
      </div>
    </div>
  )
}
