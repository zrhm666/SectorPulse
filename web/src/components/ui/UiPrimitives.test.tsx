import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import EmptyState from './EmptyState'
import InlineAlert from './InlineAlert'
import PageHeader from './PageHeader'
import Panel from './Panel'
import StatusBadge from './StatusBadge'

it('renders one page heading and its primary action', () => {
  render(<PageHeader title="分析运行" description="查看全部运行" actions={<button>新建分析</button>} />)

  expect(screen.getByRole('heading', { level: 1, name: '分析运行' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '新建分析' })).toBeInTheDocument()
})

it('renders optional page metadata before actions', () => {
  render(<PageHeader title="运营总览" meta={<span>最后更新 21:11</span>} actions={<button>刷新</button>} />)
  expect(screen.getByText('最后更新 21:11')).toBeInTheDocument()
  expect(screen.getByText('最后更新 21:11').closest('.page-header__meta')).not.toBeNull()
})

it('exposes status and alert semantics as text', () => {
  render(
    <>
      <StatusBadge status="FAILED" />
      <InlineAlert tone="error" title="运行失败">Provider 超时</InlineAlert>
    </>,
  )

  expect(screen.getByText('失败')).toBeInTheDocument()
  expect(screen.getByText('失败').closest('.status-badge')).toHaveAttribute('data-tone', 'danger')
  expect(screen.getByRole('alert')).toHaveTextContent('Provider 超时')
})

it('applies compact density without changing panel semantics', () => {
  render(<Panel title="新闻记录" density="compact">内容</Panel>)
  expect(screen.getByRole('region', { name: '新闻记录' })).toHaveClass('panel--compact')
})

it('renders a guided empty state action', () => {
  render(<EmptyState title="还没有运行记录" description="创建第一次分析。" action={<button>新建分析</button>} />)

  expect(screen.getByRole('button', { name: '新建分析' })).toBeInTheDocument()
})
