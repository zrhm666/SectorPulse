import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SystemStatusPage from './SystemStatusPage'
import * as operationsApi from '../operationsApi'

vi.mock('../operationsApi')

describe('SystemStatusPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('shows unavailable prerequisites without rendering secret values', async () => {
    vi.mocked(operationsApi.fetchOperationsSummary).mockResolvedValue({
      database: { backend: 'sqlite', name: 'local.db' },
      llm: { provider: 'openai-compatible', model: 'safe-model', budget_cny_per_run: '2.00', configured: false },
      consent: { live_data: false, live_llm: false },
      providers: { live_data_available: false, missing_requirements: ['live-data-consent'] },
      runs: { total: 0, running: 0, awaiting_review: 0, failed: 0, recent: [] },
    })

    render(<SystemStatusPage />)

    expect(await screen.findByRole('heading', { level: 1, name: '系统状态' })).toBeInTheDocument()
    expect(screen.getByText('缺少 live-data-consent')).toBeInTheDocument()
    expect(screen.queryByText(/api[_ -]?key/i)).not.toBeInTheDocument()
  })
})
