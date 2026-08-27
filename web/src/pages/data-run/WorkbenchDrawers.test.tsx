import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { DataRunNewsDetailView, MarketSectorView, MarketSnapshotSummary } from '../../dataRunsApi'
import MarketDetailDrawer from './MarketDetailDrawer'
import NewsDetailDrawer from './NewsDetailDrawer'

const market: MarketSectorView = {
  sector_id: '881101', name: '农业', kind: 'INDUSTRY', pct_change: '3.2',
  turnover_rate: null, total_market_cap: null, advancers: 21, decliners: 5,
  leader_name: '示例股份', leader_pct_change: '8.6', breadth_ratio: '0.8',
  field_availability: { pct_change: true, turnover_rate: false },
}
const snapshot: MarketSnapshotSummary = {
  kind: 'INDUSTRY', provider_id: 'akshare-ths', classification_version: 'v1',
  source_version: '2.3.0', observed_at: '2026-08-28T08:00:00Z',
  collected_at: '2026-08-28T08:01:00Z', sector_count: 90,
  available_fields: ['pct_change'], raw_artifact_sha256: 'abc123',
}
const news: DataRunNewsDetailView = {
  document_id: 'doc-1', source_id: 'cls', citation_url: 'https://example.com/news',
  title: '盘中快讯', publisher: '财联社', summary: '农业板块异动。',
  content_kind: 'FLASH', content: '农业板块异动。', content_available: true,
  published_at: '2026-08-28T08:00:00Z', source_observed_at: '2026-08-28T08:00:05Z',
  collected_at: '2026-08-28T08:00:10Z', source_grade: 'REPUTABLE_MEDIA',
}

describe('workbench detail drawers', () => {
  it('shows market availability and collection provenance', () => {
    render(<MarketDetailDrawer item={market} snapshot={snapshot} onClose={vi.fn()} />)

    expect(screen.getByRole('dialog', { name: '农业行情详情' })).toBeInTheDocument()
    expect(screen.getByText('akshare-ths')).toBeInTheDocument()
    expect(screen.getByText('Provider 未返回')).toBeInTheDocument()
    expect(screen.getByText('abc123')).toBeInTheDocument()
  })

  it('labels saved flash text without claiming full article storage', async () => {
    const trigger = document.createElement('button')
    document.body.append(trigger)
    trigger.focus()
    const onClose = vi.fn()
    const { unmount } = render(<NewsDetailDrawer detail={news} loading={false} error={null} onClose={onClose} />)

    expect(screen.getByRole('dialog', { name: '盘中快讯' })).toBeInTheDocument()
    expect(screen.getByText('快讯')).toBeInTheDocument()
    expect(screen.getByText('系统未保存新闻全文')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '打开安全原文链接' })).toHaveAttribute('href', 'https://example.com/news')
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
    unmount()
    expect(trigger).toHaveFocus()
    trigger.remove()
  })
})
