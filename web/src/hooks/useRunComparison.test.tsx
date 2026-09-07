import { act, renderHook, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { fetchRunComparison } from '../runComparisonsApi'
import { comparison, pair } from '../testComparisonFixtures'
import useRunComparison from './useRunComparison'

vi.mock('../runComparisonsApi', () => ({ fetchRunComparison: vi.fn() }))
beforeEach(() => vi.resetAllMocks())
it('loads in StrictMode and does not query an incomplete pair', async () => {
  vi.mocked(fetchRunComparison).mockResolvedValue(comparison)
  const { result, rerender } = renderHook(({ value }) => useRunComparison(value), { initialProps: { value: pair as typeof pair | null }, wrapper: StrictMode })
  await waitFor(() => expect(result.current.data).toEqual(comparison))
  const count = vi.mocked(fetchRunComparison).mock.calls.length
  rerender({ value: null })
  expect(result.current.data).toBeNull()
  expect(fetchRunComparison).toHaveBeenCalledTimes(count)
})
it('cancels an old pair and ignores a late response even if fetch ignores abort', async () => {
  let finishOld!: (value: typeof comparison) => void
  vi.mocked(fetchRunComparison).mockReturnValueOnce(new Promise((resolve) => { finishOld = resolve }))
  const swapped = { ...comparison, base: comparison.compare, compare: comparison.base }
  vi.mocked(fetchRunComparison).mockResolvedValueOnce(swapped)
  const { result, rerender } = renderHook(({ value }) => useRunComparison(value), { initialProps: { value: pair } })
  const oldSignal = vi.mocked(fetchRunComparison).mock.calls[0][1]
  rerender({ value: { base: pair.compare, compare: pair.base } })
  expect(oldSignal.aborted).toBe(true)
  await waitFor(() => expect(result.current.data).toEqual(swapped))
  await act(async () => finishOld(comparison))
  expect(result.current.data).toEqual(swapped)
})
it('allows explicit retry after a failure', async () => {
  vi.mocked(fetchRunComparison).mockRejectedValueOnce(new Error('暂时不可用')).mockResolvedValueOnce(comparison)
  const { result } = renderHook(() => useRunComparison(pair))
  await waitFor(() => expect(result.current.error).toBe('暂时不可用'))
  act(() => result.current.reload())
  await waitFor(() => expect(result.current.data).toEqual(comparison))
  expect(result.current.error).toBeNull()
})
