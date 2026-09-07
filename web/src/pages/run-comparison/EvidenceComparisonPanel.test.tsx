import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { fetchComparisonEvidence } from '../../runComparisonsApi'
import { evidenceComparison, pair } from '../../testComparisonFixtures'
import EvidenceComparisonPanel from './EvidenceComparisonPanel'

vi.mock('../../runComparisonsApi', () => ({ fetchComparisonEvidence: vi.fn() }))
it('preserves separate kind links and original mapping reasons on both sides', async () => {
  vi.mocked(fetchComparisonEvidence).mockResolvedValue(evidenceComparison)
  render(<EvidenceComparisonPanel pair={pair} />)
  expect(await screen.findByText(/示例事件/)).toBeVisible()
  expect(screen.getByText('行业 · 001')).toBeVisible()
  expect(screen.getByText('概念 · 001')).toBeVisible()
  expect(screen.getByText(/事件元数据不可用/)).toBeVisible()
  expect(document.body.textContent).toContain('low')
  expect(screen.getByText('无留存关联')).toBeVisible()
  expect(document.body.textContent?.match(/已保存的关键词关联，不代表因果验证。/g)).toHaveLength(3)
})
