import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import EvidenceDecisionPane from './EvidenceDecisionPane'

const version = { version: 2, status: 'READY_FOR_HUMAN_REVIEW', titles: ['标题'], introduction: '导语', sections: [], conclusion: '结论', risk_notice: '风险', sources: [{ source_id: 'source-1', title: '来源' }], character_count: 10 }

it('keeps evidence and return reasons independent', async () => {
  render(<EvidenceDecisionPane version={version} governance={{ status: 'PASS', issues: [] }} approval={null} decisions={[]} onDecision={vi.fn()} onApprove={vi.fn()} onRevoke={vi.fn()} onReturn={vi.fn()} />)

  await userEvent.type(screen.getByLabelText('理由'), '保留原始来源')

  await userEvent.click(screen.getByRole('button', { name: '退回修改' }))
  expect(screen.getByRole('button', { name: '提交退回' })).toBeDisabled()
})

it('reveals return reason on demand, preserves cancelled text and requires confirmation', async () => {
  const onReturn = vi.fn().mockResolvedValue(undefined)
  render(<EvidenceDecisionPane version={version} governance={{ status: 'PASS', issues: [] }} approval={null} decisions={[]} onDecision={vi.fn()} onApprove={vi.fn()} onRevoke={vi.fn()} onReturn={onReturn} />)
  expect(screen.queryByLabelText('退回原因')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '退回修改' }))
  await userEvent.type(screen.getByLabelText('退回原因'), '需要补充来源')
  await userEvent.click(screen.getByRole('button', { name: '取消退回' }))
  expect(screen.queryByLabelText('退回原因')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '退回修改' }))
  expect(screen.getByLabelText('退回原因')).toHaveValue('需要补充来源')
  await userEvent.click(screen.getByRole('button', { name: '提交退回' }))
  expect(onReturn).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: '确认退回' }))
  expect(onReturn).toHaveBeenCalledWith('需要补充来源')
})

it('shows the approved export action', () => {
  render(<EvidenceDecisionPane version={version} governance={{ status: 'PASS', issues: [] }} approval={{ draft_id: 'draft-1', version: 2, status: 'APPROVED_FOR_COPY', actor: 'reviewer' }} decisions={[]} exportUrl="/export.json" onDecision={vi.fn()} onApprove={vi.fn()} onRevoke={vi.fn()} onReturn={vi.fn()} />)

  expect(screen.getByRole('link', { name: '导出已批准版本' })).toHaveAttribute('href', '/export.json')
})

it('keeps long source lists compact until expanded', async () => {
  const longVersion = {
    ...version,
    sources: Array.from({ length: 8 }, (_, index) => ({
      source_id: `source-${index + 1}`,
      title: `来源 ${index + 1}`,
    })),
  }
  render(<EvidenceDecisionPane version={longVersion} governance={{ status: 'PASS', issues: [] }} approval={null} decisions={[]} onDecision={vi.fn()} onApprove={vi.fn()} onRevoke={vi.fn()} onReturn={vi.fn()} />)

  const expand = screen.getByRole('button', { name: '展开全部 8 条来源' })
  expect(expand).toHaveAttribute('aria-expanded', 'false')
  const sourceList = screen.getByRole('list', { name: '审核来源' })
  expect(within(sourceList).getByText('来源 6')).toBeVisible()
  expect(within(sourceList).queryByText('来源 7')).not.toBeInTheDocument()

  await userEvent.click(expand)

  expect(within(sourceList).getByText('来源 8')).toBeVisible()
  expect(screen.getByRole('button', { name: '收起来源' })).toHaveAttribute('aria-expanded', 'true')
})

it('follows the focused section mapping and labels global fallback truthfully', () => {
  const mappedVersion = {
    ...version,
    sources: [
      { source_id: 'source-1', title: '全局来源' },
      { source_id: 'source-2', title: '农业来源' },
    ],
  }
  const props = { version: mappedVersion, governance: { status: 'PASS', issues: [] }, approval: null, decisions: [], onDecision: vi.fn(), onApprove: vi.fn(), onRevoke: vi.fn(), onReturn: vi.fn() }
  const view = render(<EvidenceDecisionPane {...props} activeField={{ key: 'sections/agri/body', label: '农业板块', sourceIds: ['source-2'] }} />)

  expect(screen.getByText('与「农业板块」相关的来源')).toBeVisible()
  expect(within(screen.getByRole('list', { name: '审核来源' })).getByText('农业来源')).toBeVisible()
  expect(within(screen.getByRole('list', { name: '审核来源' })).queryByText('全局来源')).not.toBeInTheDocument()

  view.rerender(<EvidenceDecisionPane {...props} activeField={{ key: 'introduction', label: '导语' }} />)
  expect(screen.getByText('当前字段没有逐段来源映射，显示全部来源。')).toBeVisible()
  expect(within(screen.getByRole('list', { name: '审核来源' })).getByText('全局来源')).toBeVisible()
})

it('explains why approval is blocked and keeps governance and audit reachable', async () => {
  render(<EvidenceDecisionPane
    version={version}
    governance={{ status: 'FAIL', issues: [{ code: 'MISSING_SOURCE', message: '缺少来源', severity: 'ERROR' }] }}
    approval={null}
    decisions={[{ decision_id: 'decision-1', draft_version: 2, source_id: 'source-1', decision: 'KEEP', reason: '可靠', affected_section_ids: [], created_at: '2026-08-28T01:00:00Z' }]}
    approvalDisabledReason="治理检查未通过，不能批准。"
    onDecision={vi.fn()} onApprove={vi.fn()} onRevoke={vi.fn()} onReturn={vi.fn()}
  />)

  expect(screen.getByRole('button', { name: '批准复制' })).toBeDisabled()
  expect(screen.getByText('治理检查未通过，不能批准。')).toBeVisible()
  await userEvent.click(screen.getByRole('tab', { name: '治理' }))
  expect(screen.getByText('缺少来源')).toBeVisible()
  await userEvent.click(screen.getByRole('tab', { name: '审计' }))
  expect(screen.getByText('可靠')).toBeVisible()
})
