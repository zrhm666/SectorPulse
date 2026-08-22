import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import * as api from './api'

vi.mock('./api')
vi.mock('./dataRunsApi')

describe('App routes', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.fetchRuns).mockResolvedValue([])
  })

  it('redirects the root route to the analysis run page', async () => {
    window.history.pushState({}, '', '/')

    render(<App />)

    expect(await screen.findByRole('heading', { level: 1, name: '分析运行' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '分析运行' })).toHaveAttribute('aria-current', 'page')
  })

  it('renders the runs route inside the main navigation shell', async () => {
    window.history.pushState({}, '', '/runs')

    render(<App />)

    expect(await screen.findByRole('heading', { level: 1, name: '分析运行' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: '主导航' })).toBeInTheDocument()
  })

  it('shows a loading state while runs are being requested', () => {
    vi.mocked(api.fetchRuns).mockReturnValue(new Promise(() => undefined))
    window.history.pushState({}, '', '/runs')

    render(<App />)

    expect(screen.getByRole('status')).toHaveTextContent('正在加载运行记录')
  })

  it('shows a request error instead of an empty run list', async () => {
    vi.mocked(api.fetchRuns).mockRejectedValue(new Error('offline'))
    window.history.pushState({}, '', '/runs')

    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent('无法加载运行记录')
  })

  it('shows a guided empty state after a successful empty response', async () => {
    window.history.pushState({}, '', '/runs')

    render(<App />)

    expect(await screen.findByRole('heading', { level: 2, name: '还没有运行记录' })).toBeInTheDocument()
  })
})
