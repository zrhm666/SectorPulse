import { act, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'

import RunTaskTree from './RunTaskTree'

afterEach(() => { vi.unstubAllGlobals() })

type TasksPayload = {
  recording: 'recorded' | 'not_recorded'
  tasks: unknown[]
  artifacts: unknown[]
  tool_invocations: unknown[]
  model_calls: unknown[]
  budget: Record<string, unknown>
}

const emptyPayload: TasksPayload = {
  recording: 'recorded', tasks: [], artifacts: [], tool_invocations: [], model_calls: [], budget: {},
}

function stubTasks(payload: Partial<TasksPayload>) {
  const fetcher = vi.fn(async () => new Response(
    JSON.stringify({ ...emptyPayload, ...payload }), { status: 200 },
  ))
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}

async function renderTree(runId = 'run-1') {
  const view = render(
    <MemoryRouter><RunTaskTree runId={runId} active={false} /></MemoryRouter>,
  )
  await act(async () => { await Promise.resolve() })
  return view
}

const recordedTasks = [
  {
    task_id: 'root', parent_id: null, role: 'A0', scope: '分析半导体板块', attempt: 1,
    status: 'completed', worker_id: null, lease_expires_at: null,
    public_error_code: null, selection_version: null,
  },
  {
    task_id: 'market', parent_id: 'root', role: 'A1', scope: 'market', attempt: 1,
    status: 'completed', worker_id: 'w-1', lease_expires_at: null,
    public_error_code: null, selection_version: 2,
  },
  {
    task_id: 'research', parent_id: 'root', role: 'A2', scope: 'sector:半导体', attempt: 1,
    status: 'failed', worker_id: 'w-2', lease_expires_at: '2026-09-15T09:30:00+00:00',
    public_error_code: 'AGENT_TOOL_LIMIT', selection_version: null,
  },
]

it('renders each recorded task with its role, status, sector scope and parent link', async () => {
  stubTasks({ tasks: recordedTasks })
  await renderTree()

  const tree = screen.getByRole('list', { name: '任务树' })
  const rows = within(tree).getAllByRole('listitem')
  expect(rows).toHaveLength(3)

  const root = within(tree).getByRole('group', { name: /A0.*调度/ })
  expect(within(root).getByText('分析半导体板块')).toBeVisible()
  expect(within(root).getByText('已完成')).toBeVisible()

  // Children are nested under the parent that delegated them, not flattened.
  const nested = within(tree).getByRole('list', { name: 'A0 子任务' })
  expect(within(nested).getAllByRole('listitem')).toHaveLength(2)
  expect(within(nested).getByText('sector:半导体')).toBeVisible()
  expect(within(nested).getByText('已达到工具调用上限')).toBeVisible()
})

it('attributes tool and model spend to the task that spent it', async () => {
  stubTasks({
    tasks: recordedTasks,
    tool_invocations: [
      { call_id: 'c1', task_id: 'market', tool_name: 'collect_market', status: 'succeeded', reserved_cny: '0.10', actual_cny: '0.04' },
      { call_id: 'c2', task_id: 'market', tool_name: 'rank_sector_candidates', status: 'succeeded', reserved_cny: '0.10', actual_cny: '0.06' },
      { call_id: 'c3', task_id: 'research', tool_name: 'search_news', status: 'failed', reserved_cny: '0.20', actual_cny: null },
    ],
    model_calls: [
      { call_id: 'm1', task_id: 'market', role: 'A1', model: 'test-model', status: 'succeeded', reserved_tokens: 1000, actual_tokens: 800, settled: true, reserved_cny: '0.50', actual_cny: '0.30' },
      { call_id: 'm2', task_id: 'research', role: 'A2', model: 'test-model', status: 'failed', reserved_tokens: 1000, actual_tokens: null, settled: false, reserved_cny: '0.50', actual_cny: null },
    ],
  })
  await renderTree()

  const market = screen.getByRole('group', { name: /A1.*行情与候选/ })
  expect(within(market).getByText(/工具 2 次/)).toBeVisible()
  expect(within(market).getByText(/模型 1 次/)).toBeVisible()
  expect(within(market).getByText(/已结算 ¥0.40/)).toBeVisible()

  // A failed call that never settled must not be reported as a spend of zero.
  const research = screen.getByRole('group', { name: /A2.*查证/ })
  expect(within(research).getByText(/费用未知/)).toBeVisible()
})

it('links each artifact to the view that owns it', async () => {
  stubTasks({
    tasks: recordedTasks,
    artifacts: [
      { artifact_id: 'a1', task_id: 'research', kind: 'sector_analysis', reference: 'sector-analysis:a1' },
      { artifact_id: 'a2', task_id: 'market', kind: 'candidate_selection', reference: 'candidate-selection:a2' },
    ],
  })
  await renderTree('run-9')

  expect(screen.getByRole('link', { name: '板块雷达' })).toHaveAttribute('href', '/runs/run-9?tab=radar')
  expect(screen.getByRole('link', { name: '概览' })).toHaveAttribute('href', '/runs/run-9?tab=overview')
})

it('keeps a satisfied task distinct from one still holding a lease', async () => {
  stubTasks({ tasks: recordedTasks })
  await renderTree()

  const root = screen.getByRole('group', { name: /A0.*调度/ })
  expect(within(root).queryByText(/租约/)).toBeNull()
  const research = screen.getByRole('group', { name: /A2.*查证/ })
  expect(within(research).getByText(/租约至/)).toBeVisible()
})

it('says nothing was recorded instead of inventing a tree', async () => {
  stubTasks({ recording: 'not_recorded' })
  await renderTree()

  expect(screen.getByText(/本次运行没有记录任务树/)).toBeVisible()
  expect(screen.queryByRole('list', { name: '任务树' })).toBeNull()
})

it('reports a failed load without pretending the run has no tasks', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
  await renderTree()

  expect(screen.getByRole('alert')).toHaveTextContent(/任务树暂时无法加载/)
})
