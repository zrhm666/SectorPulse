import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import * as api from '../api'
import * as editing from '../editingApi'
import useReviewWorkspace from './useReviewWorkspace'

vi.mock('../api')
vi.mock('../editingApi')

const pendingRun = {
  run_id: 'run-pending', requested_at: '2026-08-28T08:00:00Z', provider: 'fixture',
  status: 'READY_FOR_HUMAN_REVIEW', elapsed_ms: 100, total_cost_cny: '0', draft_id: 'draft-pending',
}
const approvedRun = {
  ...pendingRun, run_id: 'run-approved', draft_id: 'draft-approved', status: 'COMPLETED',
}
const version = {
  version: 1, status: 'READY_FOR_HUMAN_REVIEW', titles: ['标题'], introduction: '导语',
  sections: [], conclusion: '结论', risk_notice: '风险', sources: [], character_count: 10,
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchRuns).mockResolvedValue([approvedRun, pendingRun])
  vi.mocked(api.fetchDraft).mockResolvedValue({ versions: [version] })
  vi.mocked(editing.fetchGovernance).mockResolvedValue({ status: 'PASS', issues: [] })
  vi.mocked(editing.fetchApproval).mockResolvedValue(null)
  vi.mocked(editing.fetchEvidenceDecisions).mockResolvedValue([])
})

it('selects the first pending review and loads its complete workspace', async () => {
  const { result } = renderHook(() => useReviewWorkspace())
  await act(async () => { await Promise.resolve(); await Promise.resolve() })

  expect(result.current.selectedRun?.run_id).toBe('run-pending')
  expect(result.current.versions).toEqual([version])
  expect(result.current.governance?.status).toBe('PASS')
  expect(result.current.initialLoading).toBe(false)
})

it('prevents a stale run response from replacing the newer selection', async () => {
  let resolvePending: ((value: { versions: typeof version[] }) => void) | undefined
  vi.mocked(api.fetchDraft).mockImplementation((runId) => runId === 'run-pending'
    ? new Promise((resolve) => { resolvePending = resolve })
    : Promise.resolve({ versions: [{ ...version, titles: ['已批准标题'] }] }))
  const { result } = renderHook(() => useReviewWorkspace())
  await act(async () => { await Promise.resolve() })

  act(() => result.current.selectRun('run-approved'))
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
  await act(async () => { resolvePending?.({ versions: [version] }); await Promise.resolve() })

  expect(result.current.selectedRun?.run_id).toBe('run-approved')
  expect(result.current.versions[0].titles[0]).toBe('已批准标题')
})

it('preserves the current run when a queue refresh still contains it', async () => {
  const { result } = renderHook(() => useReviewWorkspace())
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
  act(() => result.current.selectRun('run-approved'))
  await act(async () => { await Promise.resolve(); await Promise.resolve() })

  vi.mocked(api.fetchRuns).mockResolvedValue([pendingRun, approvedRun])
  await act(async () => { await result.current.refreshQueue() })

  expect(result.current.selectedRun?.run_id).toBe('run-approved')
})

it('retains the last successful workspace after a recoverable reload failure', async () => {
  const { result } = renderHook(() => useReviewWorkspace())
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
  vi.mocked(api.fetchDraft).mockRejectedValueOnce(new Error('offline'))

  await act(async () => { await result.current.refreshWorkspace() })

  expect(result.current.versions).toEqual([version])
  expect(result.current.stale).toBe(true)
  expect(result.current.workspaceError).toBe('审核材料刷新失败，当前显示最近一次成功数据。')
})
