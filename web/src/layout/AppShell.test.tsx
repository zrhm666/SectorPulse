import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import AppShell from './AppShell'

function setNarrow(matches: boolean) {
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches,
    media: '(max-width: 900px)',
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })))
}

afterEach(() => vi.unstubAllGlobals())

function renderShellAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<h1>运营总览内容</h1>} />
          <Route path="/runs" element={<h1>分析运行内容</h1>} />
          <Route path="/review" element={<h1>审核工作台内容</h1>} />
          <Route path="/data-runs/:runId" element={<h1>数据运行内容</h1>} />
          <Route path="/schedules" element={<h1>定时任务内容</h1>} />
          <Route path="/system" element={<h1>系统状态内容</h1>} />
          <Route path="/shadow-acceptance" element={<h1>影子验收内容</h1>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

it('renders available navigation and marks the current route', () => {
  renderShellAt('/runs')

  expect(screen.getByRole('heading', { name: '运营', level: 2 })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '管理', level: 2 })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '分析运行' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByRole('link', { name: '运营总览' })).toHaveAttribute('href', '/')
  expect(screen.getByRole('link', { name: '定时任务' })).toHaveAttribute('href', '/schedules')
  expect(screen.getByRole('link', { name: '系统状态' })).toHaveAttribute('href', '/system')
  expect(screen.getByRole('link', { name: '影子验收' })).toHaveAttribute('href', '/shadow-acceptance')
})

it('opens and closes navigation on narrow layouts', async () => {
  setNarrow(true)
  const user = userEvent.setup()
  renderShellAt('/runs')

  const menuButton = screen.getByRole('button', { name: '打开导航' })
  expect(menuButton).toHaveAttribute('aria-expanded', 'false')
  await user.click(menuButton)
  expect(menuButton).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByRole('navigation', { name: '主导航' })).toHaveAttribute('data-open', 'true')

  await user.click(screen.getByRole('button', { name: '关闭导航' }))
  expect(menuButton).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByRole('navigation', { name: '主导航', hidden: true })).toHaveAttribute('data-open', 'false')
})

it('removes only a closed narrow navigation from accessibility and focus order', async () => {
  setNarrow(true)
  const user = userEvent.setup()
  renderShellAt('/runs')

  const sidebar = document.querySelector('aside.sidebar-nav') as HTMLElement
  expect(sidebar).toHaveAttribute('aria-hidden', 'true')
  expect(sidebar.inert).toBe(true)

  await user.click(screen.getByRole('button', { name: '打开导航' }))
  expect(sidebar).not.toHaveAttribute('aria-hidden')
  expect(sidebar.inert).toBe(false)
})

it('never hides the desktop sidebar', () => {
  setNarrow(false)
  renderShellAt('/runs')

  const sidebar = document.querySelector('aside.sidebar-nav') as HTMLElement
  expect(sidebar).not.toHaveAttribute('aria-hidden')
  expect(sidebar.inert).toBe(false)
})

it('renders one decorative outline icon for each navigation link', () => {
  renderShellAt('/')
  for (const link of screen.getAllByRole('link').filter((node) => node.closest('nav'))) {
    expect(link.querySelector('svg.app-icon')).toHaveAttribute('aria-hidden', 'true')
  }
})

it('makes the independently scrolling content region keyboard reachable', () => {
  renderShellAt('/')

  expect(screen.getByRole('main')).toHaveAttribute('tabindex', '0')
})

it('renders the approved product identity and current route context', () => {
  renderShellAt('/runs')

  expect(screen.getByText('智能板块研判平台')).toBeInTheDocument()
  expect(screen.getByLabelText('当前位置')).toHaveTextContent('运营/分析运行')
})

it('maps detail routes without adding them to primary navigation', () => {
  renderShellAt('/data-runs/data-1')

  expect(screen.getByLabelText('当前位置')).toHaveTextContent('运营/数据运行')
  expect(screen.queryByRole('link', { name: '数据运行' })).not.toBeInTheDocument()
})

it('moves focus into the opened navigation and closes it with Escape', async () => {
  setNarrow(true)
  const user = userEvent.setup()
  renderShellAt('/runs')

  const menuButton = screen.getByRole('button', { name: '打开导航' })
  await user.click(menuButton)
  expect(screen.getByRole('button', { name: '关闭导航' })).toHaveFocus()
  await user.keyboard('{Escape}')
  expect(menuButton).toHaveAttribute('aria-expanded', 'false')
  expect(menuButton).toHaveFocus()
})
