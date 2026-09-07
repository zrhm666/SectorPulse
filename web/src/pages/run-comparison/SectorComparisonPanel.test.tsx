import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'
import { sectorComparison } from '../../testComparisonFixtures'
import SectorComparisonPanel from './SectorComparisonPanel'

it('keeps kind identity, known zero and null distinct and explains aligned changes', () => {
  render(<SectorComparisonPanel data={sectorComparison} />)
  expect(screen.getByText('半导体')).toBeVisible()
  expect(screen.getByText('人工智能')).toBeVisible()
  expect(screen.getByText('上升 3 位')).toBeVisible()
  expect(screen.getAllByText('0%')).toHaveLength(2)
  expect(screen.getByText('仅对照入选')).toBeVisible()
  const row = screen.getByRole('row', { name: /半导体/ })
  fireEvent.click(within(row).getByRole('button', { name: '查看详情' }))
  expect(screen.getByText('字段口径未知')).toBeVisible()
  expect(screen.getByText(/各次运行内部相对分/)).toBeVisible()
  expect(document.body.textContent).toContain('0.87')
  fireEvent.change(screen.getByLabelText('板块类型'), { target: { value: 'CONCEPT' } })
  expect(screen.queryByText('半导体')).not.toBeInTheDocument()
  expect(screen.getByText('人工智能')).toBeVisible()
})
it('explains incompatible and missing categories instead of rendering matched codes', () => {
  render(<SectorComparisonPanel data={{ ...sectorComparison, kinds: sectorComparison.kinds.map((kind) => ({ ...kind, status: 'INCOMPATIBLE', rows: [] })) }} />)
  expect(screen.getAllByText('来源或分类版本不一致')).toHaveLength(2)
  expect(screen.queryByText('半导体')).not.toBeInTheDocument()
  expect(screen.getAllByText(/当前筛选没有可比候选/)).toHaveLength(2)
})
