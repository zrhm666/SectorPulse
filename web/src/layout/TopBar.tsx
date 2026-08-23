export type TopBarProps = {
  onOpenNavigation: () => void
}

export default function TopBar({ onOpenNavigation }: TopBarProps) {
  return (
    <header className="top-bar">
      <a className="skip-link" href="#main-content">跳到主内容</a>
      <button className="top-bar__menu" type="button" onClick={onOpenNavigation} aria-label="打开导航">
        菜单
      </button>
      <div className="top-bar__context">
        <span className="top-bar__product">SectorPulse</span>
        <span className="top-bar__label">运营后台</span>
      </div>
    </header>
  )
}
