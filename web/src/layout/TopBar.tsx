import AppIcon from '../components/ui/AppIcon'

export type TopBarProps = {
  navOpen: boolean
  onToggleNavigation: () => void
}

export default function TopBar({ navOpen, onToggleNavigation }: TopBarProps) {
  return (
    <header className="top-bar">
      <a className="skip-link" href="#main-content">跳到主内容</a>
      <button className="top-bar__menu" type="button" onClick={onToggleNavigation} aria-label="打开导航" aria-expanded={navOpen} aria-controls="primary-navigation">
        <AppIcon name="menu" /><span>菜单</span>
      </button>
      <div className="top-bar__context">
        <span className="top-bar__product">SectorPulse</span>
        <span className="top-bar__label">运营后台</span>
      </div>
    </header>
  )
}
