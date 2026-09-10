import { act, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import AgentTrace from './AgentTrace'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

it('restores saved evidence and stops polling after the run ends', async () => {
  vi.useFakeTimers()
  const fetcher = vi.fn()
  // A fresh Response is required for each actual HTTP response body.
  fetcher.mockImplementation(async () => new Response(JSON.stringify({ steps: [
    { sector_id: 's1', sector_kind: 'INDUSTRY', step: 0, recorded_at: '', event: { type: 'started', sector_name: '文化传媒' } },
    { sector_id: 's1', sector_kind: 'INDUSTRY', step: 1, recorded_at: '', event: { type: 'tool_result', action: { action: 'read_news_detail' }, observation: { status: 'partial', data: { availability: 'summary_only', content: '已保存的新闻摘要' } } } },
  ] }), { status: 200 }))
  vi.stubGlobal('fetch', fetcher)
  const view = render(<AgentTrace runId="r1" active />)
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  expect(screen.getByText(/文化传媒/)).toBeInTheDocument()
  expect(screen.getByText('已保存的新闻摘要')).toBeInTheDocument()
  expect(screen.getByText(/仅有摘要/)).toBeInTheDocument()
  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  expect(fetcher).toHaveBeenCalledTimes(2)
  view.rerender(<AgentTrace runId="r1" active={false} />)
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  const calls = fetcher.mock.calls.length
  await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
  expect(fetcher).toHaveBeenCalledTimes(calls)
})
