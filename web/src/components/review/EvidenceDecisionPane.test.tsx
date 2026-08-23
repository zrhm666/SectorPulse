import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import EvidenceDecisionPane from './EvidenceDecisionPane'

const version = { version: 2, status: 'READY_FOR_HUMAN_REVIEW', titles: ['标题'], introduction: '导语', sections: [], conclusion: '结论', risk_notice: '风险', sources: [{ source_id: 'source-1', title: '来源' }], character_count: 10 }

it('keeps evidence and return reasons independent', async () => {
  render(<EvidenceDecisionPane version={version} governance={{ status: 'PASS', issues: [] }} approval={null} decisions={[]} onDecision={vi.fn()} onApprove={vi.fn()} onRevoke={vi.fn()} onReturn={vi.fn()} />)

  await userEvent.type(screen.getByLabelText('理由'), '保留原始来源')

  expect(screen.getByRole('button', { name: '退回修改' })).toBeDisabled()
})

it('shows the approved export action', () => {
  render(<EvidenceDecisionPane version={version} governance={{ status: 'PASS', issues: [] }} approval={{ draft_id: 'draft-1', version: 2, status: 'APPROVED_FOR_COPY', actor: 'reviewer' }} decisions={[]} exportUrl="/export.json" onDecision={vi.fn()} onApprove={vi.fn()} onRevoke={vi.fn()} onReturn={vi.fn()} />)

  expect(screen.getByRole('link', { name: '导出已批准版本' })).toHaveAttribute('href', '/export.json')
})
