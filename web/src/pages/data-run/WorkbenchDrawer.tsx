import { useEffect, useRef, type ReactNode } from 'react'

export default function WorkbenchDrawer({ title, children, onClose }: {
  title: string
  children: ReactNode
  onClose: () => void
}) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    previousFocusRef.current = document.activeElement as HTMLElement | null
    closeRef.current?.focus()
    return () => previousFocusRef.current?.focus()
  }, [])

  return <div className="workbench-drawer-layer" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose()
  }}>
    <aside
      className="workbench-drawer"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault()
          onClose()
        }
      }}
    >
      <header className="workbench-drawer__header"><div><span>工作台详情</span><h2>{title}</h2></div><button ref={closeRef} className="button button-secondary" type="button" onClick={onClose}>关闭</button></header>
      <div className="workbench-drawer__body">{children}</div>
    </aside>
  </div>
}
