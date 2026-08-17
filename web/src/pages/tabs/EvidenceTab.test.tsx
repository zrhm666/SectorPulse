import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { fetchEvidence } from '../../api'
import EvidenceTab from './EvidenceTab'

vi.mock('../../api', () => ({ fetchEvidence: vi.fn() }))

describe('EvidenceTab', () => {
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
})
