import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchEvidence } from '../../api'
import EvidenceTab from './EvidenceTab'

vi.mock('../../api', () => ({ fetchEvidence: vi.fn() }))

describe('EvidenceTab', () => {
  beforeEach(() => { vi.resetAllMocks() })

  it('distinguishes request failure from empty evidence and allows retry', async () => {
    vi.mocked(fetchEvidence)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ sectors: [], events: [], invocations: [] })

    render(<EvidenceTab runId="run-1" />)

    expect(await screen.findByText('无法加载证据与调用审计')).toBeVisible()
    expect(screen.queryByText('暂无关联新闻事件。')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(await screen.findByText('暂无关联新闻事件。')).toBeVisible()
    expect(fetchEvidence).toHaveBeenCalledTimes(2)
  })

  it('renders the source link for a news event', async () => {
    vi.mocked(fetchEvidence).mockResolvedValue({
      sectors: [],
      events: [
        {
          event_id: 'event-1',
          canonical_title: '政策事实',
          documents: [
            {
              title: '公告原文',
              citation_url: 'https://example.test/a',
              publisher: '示例来源',
            },
          ],
        },
      ],
      invocations: [],
    })

    render(<EvidenceTab runId="run-1" />)

    expect(await screen.findByText('政策事实')).toBeVisible()
    expect(screen.getByRole('link', { name: '公告原文' })).toHaveAttribute(
      'href',
      'https://example.test/a',
    )
  })

  it('does not render a fake link when a source URL is unavailable', async () => {
    vi.mocked(fetchEvidence).mockResolvedValue({
      sectors: [],
      events: [{
        event_id: 'event-2',
        canonical_title: '仅存档标题',
        documents: [{ title: '无链接来源', citation_url: null, publisher: null }],
      }],
      invocations: [],
    })

    render(<EvidenceTab runId="run-2" />)

    expect(await screen.findByText('无链接来源')).toBeVisible()
    expect(screen.queryByRole('link', { name: '无链接来源' })).not.toBeInTheDocument()
  })
})
