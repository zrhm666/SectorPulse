import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { vi, it, expect } from 'vitest'
import DataRunPage from './DataRunPage'
import * as api from '../dataRunsApi'

vi.mock('../dataRunsApi')

it('shows degraded reasons and source states', async () => {
  vi.mocked(api.fetchDataRun).mockResolvedValue({
    run_id: 'run-1', mode: 'intraday', status: 'DEGRADED', requested_at: '',
    quality: { news: 'DEGRADED' }, downgrade_reasons: ['NEWS_SOURCE_PARTIAL'],
  })
  vi.mocked(api.fetchDataRunCandidates).mockResolvedValue([])
  render(<MemoryRouter initialEntries={['/data-runs/run-1']}><Routes><Route path="/data-runs/:runId" element={<DataRunPage />} /></Routes></MemoryRouter>)
  expect(await screen.findByText('DEGRADED')).toBeVisible()
  expect(screen.getByText('NEWS_SOURCE_PARTIAL')).toBeVisible()
})

it('offers article generation only when attribution is ready', async () => {
  vi.mocked(api.fetchDataRun).mockResolvedValue({
    run_id: 'run-1', mode: 'intraday', status: 'READY_FOR_ATTRIBUTION', requested_at: '',
    quality: {}, downgrade_reasons: [],
  })
  vi.mocked(api.fetchDataRunCandidates).mockResolvedValue([])
  vi.mocked(api.generateDataRunArticle).mockResolvedValue({ run_id: 'run-1' })
  render(<MemoryRouter initialEntries={['/data-runs/run-1']}><Routes><Route path="/data-runs/:runId" element={<DataRunPage />} /></Routes></MemoryRouter>)
  expect(await screen.findByRole('button', { name: '生成分析稿' })).toBeVisible()
})
