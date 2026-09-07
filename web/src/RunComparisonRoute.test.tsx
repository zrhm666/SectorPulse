import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, it } from 'vitest'
import { AppRoutes } from './App'

it('resolves the static comparison route in the real app and keeps run navigation active', () => {
  render(<MemoryRouter initialEntries={['/runs/compare']}><AppRoutes /></MemoryRouter>)
  expect(screen.getByRole('heading', { name: '运行对比' })).toBeVisible()
  expect(screen.getByRole('link', { name: '分析运行' })).toHaveAttribute('aria-current', 'page')
})
