import { act, render, screen } from '@testing-library/react'
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
  expect(await screen.findAllByText('已降级')).toHaveLength(2)
  expect(screen.getByText('NEWS_SOURCE_PARTIAL')).toBeVisible()
  expect(screen.getByText('数据处理进度')).toBeVisible()
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

it('refreshes an active run every two seconds and stops after completion', async () => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  vi.mocked(api.fetchDataRun)
    .mockResolvedValueOnce({
      run_id: 'run-1', mode: 'post_close', status: 'FETCHING_MARKET', requested_at: '',
      quality: {}, downgrade_reasons: [],
    })
    .mockResolvedValue({
      run_id: 'run-1', mode: 'post_close', status: 'READY_FOR_ATTRIBUTION', requested_at: '',
      quality: {}, downgrade_reasons: [],
    })
  vi.mocked(api.fetchDataRunCandidates).mockResolvedValue([])

  render(<MemoryRouter initialEntries={['/data-runs/run-1']}><Routes><Route path="/data-runs/:runId" element={<DataRunPage />} /></Routes></MemoryRouter>)
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
  expect(screen.getByText('数据处理进度')).toBeVisible()
  expect(api.fetchDataRun).toHaveBeenCalledTimes(1)

  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  expect(api.fetchDataRun).toHaveBeenCalledTimes(2)

  await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
  expect(api.fetchDataRun).toHaveBeenCalledTimes(2)
  vi.useRealTimers()
})
