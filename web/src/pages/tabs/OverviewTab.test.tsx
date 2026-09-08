import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import ContentRunStageRail from '../../components/runs/ContentRunStageRail'

const failedDraftRun = {
  run_id: 'run-1',
  requested_at: '2026-08-23T00:00:00Z',
  provider: 'live',
  status: 'DRAFT_GENERATION_FAILED',
  elapsed_ms: 1000,
  total_cost_cny: '0',
  draft_id: null,
}

it('reconstructs truthful stages for a historical draft generation failure', () => {
  render(<ContentRunStageRail events={[]} done run={failedDraftRun} />)

  expect(screen.getAllByTestId('timeline-state').map((node) => node.textContent)).toEqual([
    '已完成',
    '已完成',
    '已完成',
    '已完成',
    '失败',
    '未执行',
  ])
})

it('shows an editorial fallback as degraded completion', () => {
  render(
    <ContentRunStageRail
      events={[{ type: 'progress', stage: 'editorial.fallback', detail: {} }]}
      done={false}
      run={{ ...failedDraftRun, status: 'RUNNING' }}
    />,
  )

  expect(screen.getByText('已降级完成')).toBeInTheDocument()
})

it('does not invent completed stages for a generic failed historical run', () => {
  render(<ContentRunStageRail events={[]} done run={{ ...failedDraftRun, status: 'FAILED' }} />)

  expect(screen.queryByText('已完成')).not.toBeInTheDocument()
})

it('uses saved draft and attribution without inventing editorial or automatic review history', () => {
  render(<ContentRunStageRail events={[]} done run={{ ...failedDraftRun, status: 'UNREVIEWED', draft_id: 'draft-1' }} hasAttribution />)
  expect(screen.getAllByTestId('timeline-state').map(node => node.textContent)).toEqual([
    '已完成', '已完成', '已完成', '未记录', '已完成', '未记录',
  ])
  expect(screen.getByText('自动审核完成')).toBeInTheDocument()
})

it('does not label missing historical events as skipped work', () => {
  render(<ContentRunStageRail events={[]} done run={{ ...failedDraftRun, status: 'INTERRUPTED' }} />)
  expect(screen.queryAllByText('未执行')).toHaveLength(0)
  expect(screen.getAllByTestId('timeline-state').every(node => node.textContent === '未记录')).toBe(true)
})

it('distinguishes automatic review completion from a passing review decision', () => {
  render(<ContentRunStageRail events={[]} done run={{ ...failedDraftRun, status: 'REVISE_REQUIRED', draft_id: 'draft-1', review_decision: 'REVISE' }} />)
  expect(screen.getAllByTestId('timeline-state')[5]).toHaveTextContent('已完成')
})
