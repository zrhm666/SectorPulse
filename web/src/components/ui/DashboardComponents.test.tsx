import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import MetricCard from './MetricCard'
import SummaryStrip from './SummaryStrip'

it('renders one metric with label value and supporting text', () => {
  render(<MetricCard icon="activity" label="今日运行" value="12" description="2 项待处理" />)
  expect(screen.getByRole('article', { name: '今日运行' })).toHaveTextContent('12')
  expect(screen.getByText('2 项待处理')).toBeInTheDocument()
})

it('clamps progress values to the native progress range', () => {
  render(<MetricCard icon="activity" label="完成率" value="120%" description="已完成" progress={120} />)
  expect(screen.getByRole('progressbar', { name: '完成率进度' })).toHaveAttribute('value', '100')
})

it('renders summary items as one named region', () => {
  render(<SummaryStrip label="运行摘要" items={[{ label: '状态', value: '已完成' }]} />)
  expect(screen.getByRole('region', { name: '运行摘要' })).toHaveTextContent('已完成')
})
