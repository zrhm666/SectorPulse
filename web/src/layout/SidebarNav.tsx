import { NavLink } from 'react-router-dom'
import type { NavigationItem } from './navigation'

export type SidebarNavProps = {
  items: NavigationItem[]
  open: boolean
  onClose: () => void
}

export default function SidebarNav({ items, open, onClose }: SidebarNavProps) {
  return (
    <>
      <aside className="sidebar-nav" data-open={open}>
        <nav aria-label="主导航" data-open={open}>
          <div className="sidebar-nav__header">
            <div>
              <p className="sidebar-nav__product">SectorPulse</p>
              <p className="sidebar-nav__context">运营后台</p>
            </div>
            <button className="sidebar-nav__close" type="button" onClick={onClose} aria-label="关闭导航">
              关闭
            </button>
          </div>
          <div className="sidebar-nav__links">
            {items.map((item) => (
              <NavLink
                className={({ isActive }) => `sidebar-nav__link${isActive ? ' sidebar-nav__link--active' : ''}`}
                end={item.exact}
                key={item.to}
                onClick={onClose}
                to={item.to}
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        </nav>
      </aside>
      <button className="sidebar-nav__backdrop" data-open={open} type="button" tabIndex={-1} aria-label="关闭导航遮罩" onClick={onClose} />
    </>
  )
}
