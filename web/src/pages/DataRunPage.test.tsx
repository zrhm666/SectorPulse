import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'

import * as api from '../dataRunsApi'
import type { DataRunView } from '../dataRunsApi'
import DataRunPage from './DataRunPage'


vi.mock('../dataRunsApi')

const READY_RUN: DataRunView = {
  run_id: 'run-1',
  provider: 'fixture',
  mode: 'intraday',
  status: 'READY_FOR_ATTRIBUTION',
  requested_at: '2026-08-25T07:00:00Z',
  cutoff_at: '2026-08-25T07:01:00Z',
  request: {
    mode: 'intraday',
    requested_at: '2026-08-25T07:00:00Z',
    lookback_hours: 6,
    precandidate_limit: 30,
    final_candidate_limit: 12,
  },
  quality: { industry: 'NORMAL', news: 'NORMAL' },
  quality_summary: {
    market_quality: { industry: 'NORMAL' },
    news_quality: { news: 'NORMAL' },
    cutoff_violation_count: 0,
    duplicate_document_count: 0,
    downgrade_reasons: [],
    error_code: null,
  },
  downgrade_reasons: [],
  error_code: null,
  finished_at: '2026-08-25T07:02:00Z',
}

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/data-runs/run-1']}>
      <LocationProbe />
      <Routes>
        <Route path="/data-runs/:runId" element={<DataRunPage />} />
        <Route path="/runs/:runId" element={<div>内容运行详情</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchDataRun).mockResolvedValue(READY_RUN)
  vi.mocked(api.fetchDataRunCandidates).mockResolvedValue([])
  vi.mocked(api.fetchDataRunMarket).mockResolvedValue({
    snapshots: [], kind: 'INDUSTRY', items: [], total: 0, offset: 0, limit: 20,
  })
  vi.mocked(api.fetchDataRunEvidence).mockResolvedValue({ events: [], total: 0 })
  vi.mocked(api.fetchDataRunQuality).mockResolvedValue(READY_RUN.quality_summary!)
  vi.mocked(api.fetchDataRunContentRun).mockResolvedValue(null)
  vi.mocked(api.generateDataRunArticle).mockResolvedValue({ run_id: 'run-1' })
  vi.mocked(api.retryDataRun).mockResolvedValue({ run_id: 'run-2' })
})

it('shows only the current collection stage as running', async () => {
  vi.mocked(api.fetchDataRun).mockResolvedValue({
    ...READY_RUN,
    status: 'FETCHING_MARKET',
    cutoff_at: null,
    finished_at: null,
  })

  renderPage()

  expect(await screen.findByText('等待数据就绪')).toBeDisabled()
  expect(screen.getAllByTestId('data-run-stage-state').map((node) => node.textContent)).toEqual([
    '进行中', '等待中', '等待中', '等待中', '等待中',
  ])
})

it('stays on the data page after starting article generation', async () => {
  renderPage()

  await userEvent.click(await screen.findByRole('button', { name: '生成分析稿' }))

  expect(screen.getByTestId('location')).toHaveTextContent('/data-runs/run-1')
  expect(await screen.findByRole('link', { name: '查看生成进度' })).toHaveAttribute(
    'href',
    '/runs/run-1',
  )
})

it('restores the content run action after refresh', async () => {
  vi.mocked(api.fetchDataRunContentRun).mockResolvedValue({
    run_id: 'run-1',
    status: 'READY_FOR_HUMAN_REVIEW',
    draft_id: 'draft-1',
    can_view_draft: true,
    requested_at: '2026-08-25T07:02:00Z',
    finished_at: '2026-08-25T07:03:00Z',
  })

  renderPage()

  expect(await screen.findByRole('link', { name: '查看分析稿' })).toHaveAttribute(
    'href',
    '/runs/run-1',
  )
})

it('retries a failed run with its original parameters', async () => {
  vi.mocked(api.fetchDataRun).mockResolvedValue({
    ...READY_RUN,
    status: 'FAILED',
    error_code: 'PROVIDER_FAILED',
  })

  renderPage()
  await userEvent.click(await screen.findByRole('button', { name: '按原参数重新采集' }))

  expect(api.retryDataRun).toHaveBeenCalledWith('run-1')
  expect(screen.getByTestId('location')).toHaveTextContent('/data-runs/run-2')
})

it('shows market, candidate, linked news, and quality data', async () => {
  vi.mocked(api.fetchDataRunMarket).mockResolvedValue({
    snapshots: [{
      kind: 'INDUSTRY', provider_id: 'akshare-ths', classification_version: 'v1',
      source_version: 'v2', observed_at: '2026-08-25T07:00:00Z',
      collected_at: '2026-08-25T07:01:00Z', sector_count: 90,
    }],
    kind: 'INDUSTRY',
    items: [{
      sector_id: 'industry-1', name: '机器人', kind: 'INDUSTRY', pct_change: '3.2',
      turnover_rate: '2.1', total_market_cap: null, advancers: 21, decliners: 5,
      leader_name: '示例股份', leader_pct_change: '8.6', breadth_ratio: '0.8',
    }],
    total: 1, offset: 0, limit: 20,
  })
  vi.mocked(api.fetchDataRunCandidates).mockResolvedValue([{
    sector_id: 'industry-1', sector_kind: 'INDUSTRY', name: '机器人', rank: 1,
    score: '9.8', reasons: ['涨幅领先'],
  }])
  vi.mocked(api.fetchDataRunEvidence).mockResolvedValue({
    total: 1,
    events: [{
      event_id: 'event-1', canonical_title: '机器人产业新闻',
      first_published_at: '2026-08-25T06:00:00Z', deduplication_reason: 'canonical_url',
      sector_ids: ['industry-1'], links: [],
      documents: [{
        document_id: 'doc-1', source_id: 'source-1',
        citation_url: 'https://example.com/news', title: '机器人产业新闻',
        publisher: '示例媒体', summary: '产业链出现新动态。',
        published_at: '2026-08-25T06:00:00Z', source_observed_at: null,
        collected_at: '2026-08-25T07:00:00Z', source_grade: 'REPUTABLE_MEDIA',
      }],
    }],
  })
  vi.mocked(api.fetchDataRunQuality).mockResolvedValue({
    market_quality: { industry: 'NORMAL' }, news_quality: { news: 'DEGRADED' },
    cutoff_violation_count: 1, duplicate_document_count: 2,
    downgrade_reasons: ['NEWS_SOURCE_PARTIAL'], error_code: null,
  })

  renderPage()

  expect(await screen.findByText('示例股份')).toBeVisible()
  await userEvent.click(screen.getByRole('tab', { name: '候选板块' }))
  expect(await screen.findByText('涨幅领先')).toBeVisible()
  await userEvent.click(screen.getByRole('tab', { name: '新闻证据' }))
  expect(await screen.findByText('产业链出现新动态。')).toBeVisible()
  expect(screen.getByRole('link', { name: '查看原文' })).toHaveAttribute(
    'href',
    'https://example.com/news',
  )
  await userEvent.click(screen.getByRole('tab', { name: '质量报告' }))
  expect(await screen.findByText('NEWS_SOURCE_PARTIAL')).toBeVisible()
  expect(screen.getByText('Cutoff 越界 1')).toBeVisible()
})

it('keeps other panels usable when market loading fails', async () => {
  vi.mocked(api.fetchDataRunMarket).mockRejectedValue(new Error('market unavailable'))
  vi.mocked(api.fetchDataRunCandidates).mockResolvedValue([{
    sector_id: 'industry-1', sector_kind: 'INDUSTRY', name: '机器人', rank: 1,
    score: '9.8', reasons: ['涨幅领先'],
  }])

  renderPage()

  expect(await screen.findByText('market unavailable')).toBeVisible()
  await userEvent.click(screen.getByRole('tab', { name: '候选板块' }))
  expect(await screen.findByText('机器人')).toBeVisible()
})
