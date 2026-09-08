import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { fetchRuns } from '../api'
import RunListPage from './RunListPage'
import { fetchDataRuns } from '../dataRunsApi'

vi.mock('../api', () => ({ fetchRuns: vi.fn() }))
vi.mock('../dataRunsApi', () => ({ fetchDataRuns: vi.fn() }))

beforeEach(() => { vi.mocked(fetchRuns).mockResolvedValue([
  { run_id: 'run-running', requested_at: new Date().toISOString(), provider: 'live', status: 'RUNNING', elapsed_ms: null, total_cost_cny: null, draft_id: null },
  { run_id: 'run-failed', requested_at: new Date(Date.now() - 60 * 86_400_000).toISOString(), provider: 'fixture', status: 'FAILED', elapsed_ms: 1200, total_cost_cny: '0', draft_id: null, error_message: '上游服务暂时不可用', retryable: true },
]) })
beforeEach(() => { vi.mocked(fetchDataRuns).mockResolvedValue([
  { run_id: 'data-post-close', mode: 'post_close', status: 'READY_FOR_ATTRIBUTION', requested_at: new Date().toISOString(), quality: {}, downgrade_reasons: [] },
]) })

it('renders a scan-friendly run table and filters status', async () => {
  render(<MemoryRouter><RunListPage /></MemoryRouter>)
  expect(screen.getByRole('link', { name: '运行对比' })).toHaveAttribute('href', '/runs/compare')
  expect(await screen.findByTitle('run-running')).toBeVisible()
  expect(screen.getByRole('region', { name: '运行筛选' })).toBeInTheDocument()
  expect(screen.getByTitle('run-failed')).toBeVisible()
  expect(screen.getAllByText('盘后复盘')).toHaveLength(2)
  fireEvent.change(screen.getByLabelText('按状态筛选'), { target: { value: 'FAILED' } })
  expect(screen.queryByTitle('run-running')).not.toBeInTheDocument()
  expect(screen.getByTitle('run-failed')).toBeVisible()
})

it('filters by scene and time range and exposes only stored failure detail', async () => {
  render(<MemoryRouter><RunListPage /></MemoryRouter>)
  await screen.findByTitle('run-running')

  fireEvent.change(screen.getByLabelText('按场景筛选'), { target: { value: 'post_close' } })
  expect(screen.getByTitle('data-post-close')).toBeVisible()
  expect(screen.queryByTitle('run-running')).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: '重置筛选' }))
  fireEvent.change(screen.getByLabelText('按时间范围筛选'), { target: { value: '7D' } })
  expect(screen.queryByTitle('run-failed')).not.toBeInTheDocument()
  expect(screen.getByText(/显示 2 条，共 3 条/)).toBeVisible()

  fireEvent.change(screen.getByLabelText('按时间范围筛选'), { target: { value: 'ALL' } })
  fireEvent.click(screen.getByRole('button', { name: '查看错误详情' }))
  expect(screen.getByText('上游服务暂时不可用')).toBeVisible()
  expect(screen.getByText('该运行支持从详情页重新运行。')).toBeVisible()
})

it('preserves actual data source and does not call finished data costs pending', async () => {
  vi.mocked(fetchDataRuns).mockResolvedValue([{ run_id: 'data-live', provider: 'live', mode: 'post_close', status: 'READY_FOR_ATTRIBUTION', requested_at: new Date().toISOString(), quality: {}, downgrade_reasons: [] }])
  render(<MemoryRouter><RunListPage /></MemoryRouter>)
  const id = await screen.findByTitle('data-live')
  const row = id.closest('tr')!
  expect(within(row).getByText('实时数据')).toBeVisible()
  expect(within(row).getByText('不适用')).toBeVisible()
  expect(within(row).queryByText('待完成')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('按 Provider 筛选'), { target: { value: 'live' } })
  expect(screen.getByTitle('data-live')).toBeVisible()
})

it('restores URL search and active collection filters, and resets them without reloading', async () => {
  vi.mocked(fetchDataRuns).mockResolvedValue([{ run_id: 'collect-market', provider: 'live', mode: 'post_close', status: 'FETCHING_MARKET', requested_at: new Date().toISOString(), quality: {}, downgrade_reasons: [] }])
  render(<MemoryRouter initialEntries={['/runs?q=collect&status=RUNNING']}><RunListPage /></MemoryRouter>)
  expect(await screen.findByTitle('collect-market')).toBeVisible()
  expect(screen.queryByTitle('run-running')).not.toBeInTheDocument()
  expect(screen.getByRole('searchbox', { name: '搜索近期运行' })).toHaveValue('collect')
  expect(screen.getByText(/每类最多 50 条/)).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '重置筛选' }))
  expect(screen.getByTitle('run-running')).toBeVisible()
})

it('paginates recent records and preserves them if refresh fails', async () => {
  vi.mocked(fetchRuns).mockResolvedValue(Array.from({ length: 25 }, (_, i) => ({ run_id: `history-${i.toString().padStart(2, '0')}`, requested_at: new Date(Date.now() - i * 1000).toISOString(), provider: 'live', status: 'FAILED', elapsed_ms: null, total_cost_cny: null, draft_id: null })))
  vi.mocked(fetchDataRuns).mockResolvedValue([])
  render(<MemoryRouter initialEntries={['/runs?status=FAILED']}><RunListPage /></MemoryRouter>)
  await screen.findByTitle('history-00')
  expect(screen.queryByTitle('history-24')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  expect(screen.getByTitle('history-24')).toBeVisible()
  expect(screen.queryByTitle('history-00')).not.toBeInTheDocument()
  vi.mocked(fetchRuns).mockRejectedValue(new Error('offline'))
  fireEvent.click(screen.getByRole('button', { name: '刷新记录' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('保留上次加载的记录')
  expect(screen.getByTitle('history-24')).toBeVisible()
  expect(screen.getByLabelText('按状态筛选')).toHaveValue('FAILED')
})
