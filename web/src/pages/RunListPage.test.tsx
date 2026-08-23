import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { fetchRuns } from '../api'
import RunListPage from './RunListPage'
import { fetchDataRuns } from '../dataRunsApi'

vi.mock('../api', () => ({ fetchRuns: vi.fn() }))
vi.mock('../dataRunsApi', () => ({ fetchDataRuns: vi.fn() }))

beforeEach(() => vi.mocked(fetchRuns).mockResolvedValue([
  { run_id: 'run-running', requested_at: '2026-08-23T01:00:00Z', provider: 'live', status: 'RUNNING', elapsed_ms: null, total_cost_cny: null, draft_id: null },
  { run_id: 'run-failed', requested_at: '2026-08-22T01:00:00Z', provider: 'fixture', status: 'FAILED', elapsed_ms: 1200, total_cost_cny: '0', draft_id: null },
]))
beforeEach(() => vi.mocked(fetchDataRuns).mockResolvedValue([
  { run_id: 'data-post-close', mode: 'post_close', status: 'READY_FOR_ATTRIBUTION', requested_at: '2026-08-23T02:00:00Z', quality: {}, downgrade_reasons: [] },
]))

it('renders a scan-friendly run table and filters status', async () => {
  render(<MemoryRouter><RunListPage /></MemoryRouter>)
  expect(await screen.findByTitle('run-running')).toBeVisible()
  expect(screen.getByTitle('run-failed')).toBeVisible()
  expect(screen.getByText('盘后复盘')).toBeVisible()
  fireEvent.change(screen.getByLabelText('按状态筛选'), { target: { value: 'FAILED' } })
  expect(screen.queryByTitle('run-running')).not.toBeInTheDocument()
  expect(screen.getByTitle('run-failed')).toBeVisible()
})
