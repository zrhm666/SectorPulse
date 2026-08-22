import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, it } from 'vitest'
import AppShell from './AppShell'

function renderShellAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/runs" element={<h1>分析运行内容</h1>} />
          <Route path="/schedules" element={<h1>定时任务内容</h1>} />
          <Route path="/shadow-acceptance" element={<h1>影子验收内容</h1>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

it('renders available navigation and marks the current route', () => {
  renderShellAt('/runs')

  expect(screen.getByRole('link', { name: '分析运行' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByRole('link', { name: '定时任务' })).toHaveAttribute('href', '/schedules')
  expect(screen.getByRole('link', { name: '影子验收' })).toHaveAttribute('href', '/shadow-acceptance')
})

it('opens and closes navigation on narrow layouts', async () => {
  const user = userEvent.setup()
  renderShellAt('/runs')

  await user.click(screen.getByRole('button', { name: '打开导航' }))
  expect(screen.getByRole('navigation', { name: '主导航' })).toHaveAttribute('data-open', 'true')

  await user.click(screen.getByRole('button', { name: '关闭导航' }))
  expect(screen.getByRole('navigation', { name: '主导航' })).toHaveAttribute('data-open', 'false')
})
