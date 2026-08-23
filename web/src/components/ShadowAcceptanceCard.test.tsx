import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ShadowAcceptanceCard from './ShadowAcceptanceCard'
import ShadowAcceptancePage from '../pages/ShadowAcceptancePage'
import * as api from '../shadowApi'

vi.mock('../shadowApi')

describe('ShadowAcceptanceCard', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.fetchShadowRuns).mockResolvedValue([])
    vi.mocked(api.fetchShadowProgress).mockResolvedValue({ trading_days: 1, passed: 1, failed: 0, blocked: 0, remaining: 19, complete: false })
  })

  it('shows 20 day progress', () => {
    render(<ShadowAcceptanceCard runs={[]} progress={{ trading_days: 1, passed: 1, failed: 0, blocked: 0, remaining: 19, complete: false }} />)
    expect(screen.getByText('交易日进度：1/20')).toBeInTheDocument()
  })

  it('shows every historical run in a read-only table', () => {
    const runs = Array.from({ length: 6 }, (_, index) => ({
      shadow_id: `shadow-${index}`,
      run_id: `run-${index}`,
      trading_date: `2026-08-${String(index + 1).padStart(2, '0')}`,
      mode: 'post_close',
      status: index === 5 ? 'BLOCKED' : 'PASSED',
      created_at: '2026-08-01T16:00:00Z',
    }))

    render(<ShadowAcceptanceCard runs={runs} progress={{ trading_days: 6, passed: 5, failed: 0, blocked: 1, remaining: 14, complete: false }} />)

    expect(screen.getByRole('table', { name: '影子运行历史' })).toBeInTheDocument()
    expect(screen.getByText('2026-08-06')).toBeInTheDocument()
    expect(screen.getByText('阻塞')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('marks shadow acceptance as paused while preserving API progress', async () => {
    render(<ShadowAcceptancePage />)

    expect(screen.getByText('影子验收已暂停')).toBeInTheDocument()
    expect(await screen.findByText('交易日进度：1/20')).toBeInTheDocument()
  })

  it('shows a loading state while historical progress is requested', () => {
    vi.mocked(api.fetchShadowProgress).mockReturnValue(new Promise(() => undefined))

    render(<ShadowAcceptancePage />)

    expect(screen.getByRole('status')).toHaveTextContent('正在加载影子验收记录')
  })

  it('shows a request error when historical progress cannot be loaded', async () => {
    vi.mocked(api.fetchShadowProgress).mockRejectedValue(new Error('offline'))

    render(<ShadowAcceptancePage />)

    expect(await screen.findByText('无法加载影子验收记录')).toBeInTheDocument()
  })
})
