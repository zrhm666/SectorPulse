import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { fetchComparisonRuns } from '../../runComparisonsApi'
import { runA, runB } from '../../testComparisonFixtures'
import RunPickerDialog from './RunPickerDialog'

vi.mock('../../runComparisonsApi', () => ({ fetchComparisonRuns: vi.fn() }))
beforeEach(() => {
  vi.clearAllMocks()
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  vi.mocked(fetchComparisonRuns).mockImplementation(async (options) => ({ items: [runA, runB], total: 55, offset: options.offset ?? 0, limit: 20 }))
})
it('pages beyond fifty and excludes the already selected run', async () => {
  const onSelect = vi.fn()
  render(<RunPickerDialog title="选择对照运行" constraint={null} excludedRunId={runA.run_id} onSelect={onSelect} onClose={vi.fn()} />)
  expect(await screen.findByRole('dialog', { name: '选择对照运行' })).toBeVisible()
  await screen.findByRole('button', { name: `选择运行 ${runB.run_id}` })
  expect(screen.getByRole('button', { name: `选择运行 ${runA.run_id}` })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  await waitFor(() => expect(fetchComparisonRuns).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 20, limit: 20 }), expect.any(AbortSignal)))
  await screen.findByRole('button', { name: `选择运行 ${runB.run_id}` })
  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  await waitFor(() => expect(fetchComparisonRuns).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 40 }), expect.any(AbortSignal)))
  await screen.findByRole('button', { name: `选择运行 ${runB.run_id}` })
  fireEvent.click(screen.getByRole('button', { name: `选择运行 ${runB.run_id}` }))
  expect(onSelect).toHaveBeenCalledWith(runB)
})
it('locks source and scene to the other run and closes on cancel', async () => {
  const onClose = vi.fn()
  render(<RunPickerDialog title="选择运行" constraint={runA} excludedRunId={null} onSelect={vi.fn()} onClose={onClose} />)
  expect(screen.getByLabelText('数据来源')).toBeDisabled()
  expect(screen.getByLabelText('运行场景')).toBeDisabled()
  await waitFor(() => expect(fetchComparisonRuns).toHaveBeenCalledWith(expect.objectContaining({ provider: 'fixture', mode: 'post_close' }), expect.any(AbortSignal)))
  fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }))
  expect(onClose).toHaveBeenCalled()
})
