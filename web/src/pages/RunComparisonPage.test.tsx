import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { fetchRunComparison } from '../runComparisonsApi'
import { fetchDataRun } from '../dataRunsApi'
import { comparison, pair, runA } from '../testComparisonFixtures'
import RunComparisonPage from './RunComparisonPage'

vi.mock('../runComparisonsApi', () => ({ fetchRunComparison: vi.fn(), fetchComparisonRuns: vi.fn() }))
vi.mock('../dataRunsApi', () => ({ fetchDataRun: vi.fn() }))
function Location() { const navigate = useNavigate(); return <><output data-testid="url">{useLocation().search}</output><button onClick={() => navigate(-1)}>测试后退</button></> }
function page(query = '') { return render(<MemoryRouter initialEntries={['/runs/compare' + query]}><Location /><RunComparisonPage /></MemoryRouter>) }
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchRunComparison).mockImplementation(async (value) => ({ ...comparison, base: value.base === pair.base ? comparison.base : comparison.compare, compare: value.compare === pair.compare ? comparison.compare : comparison.base }))
  vi.mocked(fetchDataRun).mockResolvedValue({ ...runA, quality: {}, downgrade_reasons: [], request: { ...runA } })
})
it('restores a URL, swaps direction and restores it with browser back', async () => {
  page(`?base=${pair.base}&compare=${pair.compare}`)
  expect(screen.getByRole('heading', { name: '运行对比' })).toBeVisible()
  await screen.findByRole('button', { name: '交换基准与对照' })
  await waitFor(() => expect(screen.getByRole('button', { name: '交换基准与对照' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '交换基准与对照' }))
  await waitFor(() => expect(screen.getByTestId('url')).toHaveTextContent(`base=${pair.compare}`))
  fireEvent.click(screen.getByRole('button', { name: '测试后退' }))
  await waitFor(() => expect(screen.getByTestId('url')).toHaveTextContent(`base=${pair.base}`))
})
it('prefills a base beyond the first history page without creating a run', async () => {
  page(`?base=${pair.base}`)
  await waitFor(() => expect(fetchDataRun).toHaveBeenCalledWith(pair.base, expect.any(AbortSignal)))
  expect(await screen.findByTitle(pair.base)).toBeVisible()
  expect(screen.getByRole('button', { name: '开始对比' })).toBeDisabled()
  expect(fetchRunComparison).not.toHaveBeenCalled()
})
it.each(['?base=bad', `?base=${pair.base}&compare=${pair.base}`])('rejects invalid or identical input %s', async (query) => {
  page(query)
  expect(screen.getByRole('button', { name: '开始对比' })).toBeDisabled()
  expect(fetchRunComparison).not.toHaveBeenCalled()
  expect(screen.getByRole('alert')).toBeVisible()
})
it('exposes retry while preserving a rejected selection', async () => {
  vi.mocked(fetchRunComparison).mockRejectedValueOnce(new Error('请选择相同来源的运行'))
  page(`?base=${pair.base}&compare=${pair.compare}`)
  expect(await screen.findByText('请选择相同来源的运行')).toBeVisible()
  expect(screen.getByTestId('url')).toHaveTextContent(pair.base)
  fireEvent.click(screen.getByRole('button', { name: '重试对比' }))
  await waitFor(() => expect(fetchRunComparison).toHaveBeenCalledTimes(2))
})
