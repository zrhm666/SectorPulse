import { render, screen, within } from '@testing-library/react'
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

const CANDIDATES = Array.from({ length: 4 }, (_, index) => ({
  sector_id: `industry-${index + 1}`,
  sector_kind: 'INDUSTRY',
  name: `候选板块 ${index + 1}`,
  rank: index + 1,
  score: String(10 - index),
  reasons: ['综合评分领先'],
}))

function mockCandidates(items = CANDIDATES, confirmed = true) {
  vi.mocked(api.fetchDataRunCandidatePage).mockResolvedValue({
    items,
    total: items.length,
    offset: 0,
    limit: 20,
    query: null,
    sort: 'rank',
    direction: 'asc',
    data_version: 'a'.repeat(64),
  })
  vi.mocked(api.fetchDataRunSelection).mockResolvedValue({
    run_id: 'run-1',
    confirmed,
    version: confirmed ? 1 : 0,
    selected_sector_ids: items.map((item) => item.sector_id),
    method: confirmed ? 'DEFAULT' : null,
    confirmed_at: confirmed ? '2026-08-25T07:02:00Z' : null,
    data_version: 'a'.repeat(64),
    edit_count: 0,
  })
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
  vi.mocked(api.fetchDataRunSummary).mockResolvedValue({
    run_id: 'run-1',
    status: READY_RUN.status,
    terminal: true,
    workflow_stage: 'ATTRIBUTION_READY',
    workflow_stage_index: 5,
    requested_at: READY_RUN.requested_at,
    cutoff_at: '2026-08-25T07:01:00Z',
    finished_at: '2026-08-25T07:02:00Z',
    candidate_count: 0,
  })
  mockCandidates([], false)
  vi.mocked(api.fetchDataRunMarket).mockResolvedValue({
    snapshots: [], kind: 'INDUSTRY', items: [], total: 0, offset: 0, limit: 20,
  })
  vi.mocked(api.fetchDataRunEvidence).mockResolvedValue({ events: [], total: 0 })
  vi.mocked(api.fetchDataRunAcquisition).mockResolvedValue({
    market_sources: [], news_sources: [],
    counts: { provider_results: 0, normalized_documents: 0, evidence_events: 0 },
    coverage: 'COMPLETE', coverage_notice: null,
  })
  vi.mocked(api.fetchDataRunNewsRecords).mockResolvedValue({
    items: [], total: 0, offset: 0, limit: 20,
    coverage: 'COMPLETE', coverage_notice: null,
  })
  vi.mocked(api.fetchDataRunNewsRecord).mockResolvedValue({
    document_id: 'doc-raw-1', source_id: 'eastmoney-search',
    citation_url: 'https://example.com/raw-news', title: 'Provider 原始新闻标题',
    publisher: '东方财富', summary: '这是规范化保存的新闻摘要。',
    content_kind: 'SUMMARY', content: '这是规范化保存的新闻摘要。',
    content_available: true, published_at: '2026-08-25T06:00:00Z',
    source_observed_at: '2026-08-25T06:01:00Z',
    collected_at: '2026-08-25T07:00:00Z', source_grade: 'REPUTABLE_MEDIA',
  })
  vi.mocked(api.fetchDataRunQuality).mockResolvedValue(READY_RUN.quality_summary!)
  vi.mocked(api.fetchDataRunContentRun).mockResolvedValue(null)
  vi.mocked(api.generateDataRunArticle).mockResolvedValue({ run_id: 'run-1' })
  vi.mocked(api.confirmDataRunSelection).mockImplementation(
    async (_runId, sectorIds, expectedVersion) => ({
      run_id: 'run-1', confirmed: true, version: expectedVersion + 1,
      selected_sector_ids: sectorIds, method: 'MANUAL',
      confirmed_at: '2026-08-25T07:03:00Z', data_version: 'a'.repeat(64), edit_count: 1,
    }),
  )
  vi.mocked(api.retryDataRun).mockResolvedValue({ run_id: 'run-2' })
})

it('renders metadata and workbench tabs as named regions', async () => {
  renderPage()
  const summary = await screen.findByRole('region', { name: '数据运行摘要' })
  expect(summary).toHaveTextContent('Provider')
  expect(summary).toHaveTextContent('完成时间')
  const tabs = screen.getByRole('tablist', { name: '数据运行详情' })
  expect(within(tabs).getAllByRole('tab')).toHaveLength(5)
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
  mockCandidates(CANDIDATES.slice(0, 3))
  renderPage()

  await userEvent.click(await screen.findByRole('button', { name: '生成分析稿' }))

  expect(screen.getByTestId('location')).toHaveTextContent('/data-runs/run-1')
  expect(await screen.findByRole('link', { name: '查看生成进度' })).toHaveAttribute(
    'href',
    '/runs/run-1',
  )
})

it('generates the article with only the candidates selected by the user', async () => {
  mockCandidates(CANDIDATES)
  renderPage()

  await userEvent.click(await screen.findByRole('tab', { name: '候选板块' }))
  expect(await screen.findByText('已选择 4 个')).toBeVisible()
  await userEvent.click(screen.getByRole('checkbox', { name: '选择候选板块 2' }))
  expect(screen.getByText('已选择 3 个')).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: '确认 3 个板块' }))
  await userEvent.click(screen.getByRole('button', { name: '生成分析稿' }))

  expect(api.confirmDataRunSelection).toHaveBeenCalledWith(
    'run-1', ['industry-1', 'industry-3', 'industry-4'], 1,
  )
  expect(api.generateDataRunArticle).toHaveBeenCalledWith('run-1')
})

it('requires at least three selected candidates before generation', async () => {
  mockCandidates(CANDIDATES)
  renderPage()

  await userEvent.click(await screen.findByRole('tab', { name: '候选板块' }))
  await userEvent.click(await screen.findByRole('checkbox', { name: '选择候选板块 1' }))
  await userEvent.click(screen.getByRole('checkbox', { name: '选择候选板块 2' }))

  expect(screen.getByText('已选择 2 个')).toBeVisible()
  expect(screen.getByRole('button', { name: '生成分析稿' })).toBeDisabled()
})

it('keeps local candidate choices when confirmation finds a version conflict', async () => {
  mockCandidates(CANDIDATES)
  vi.mocked(api.confirmDataRunSelection).mockRejectedValueOnce(
    new Error('CANDIDATE_SELECTION_VERSION_CONFLICT'),
  )
  renderPage()

  await userEvent.click(await screen.findByRole('tab', { name: '候选板块' }))
  await userEvent.click(await screen.findByRole('checkbox', { name: '选择候选板块 2' }))
  await userEvent.click(screen.getByRole('button', { name: '确认 3 个板块' }))

  expect(await screen.findByText('CANDIDATE_SELECTION_VERSION_CONFLICT')).toBeVisible()
  expect(screen.getByText('已选择 3 个')).toBeVisible()
  expect(screen.getByRole('checkbox', { name: '选择候选板块 2' })).not.toBeChecked()
  await userEvent.click(screen.getByRole('button', { name: '加载最新版本并保留选择' }))
  expect(screen.getByRole('checkbox', { name: '选择候选板块 2' })).not.toBeChecked()
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
  mockCandidates([{
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
  mockCandidates([{
    sector_id: 'industry-1', sector_kind: 'INDUSTRY', name: '机器人', rank: 1,
    score: '9.8', reasons: ['涨幅领先'],
  }])

  renderPage()

  expect(await screen.findByText('market unavailable')).toBeVisible()
  await userEvent.click(screen.getByRole('tab', { name: '候选板块' }))
  expect(await screen.findByText('机器人')).toBeVisible()
})

it('shows what providers actually returned and the three processing counts', async () => {
  vi.mocked(api.fetchDataRunAcquisition).mockResolvedValue({
    market_sources: [{
      kind: 'INDUSTRY', provider_id: 'akshare-ths', classification_version: 'v1',
      source_version: '2.3.0', observed_at: '2026-08-25T07:00:00Z',
      collected_at: '2026-08-25T07:01:00Z', sector_count: 90,
      available_fields: ['sector_id', 'name'], raw_artifact_sha256: 'abc123',
    }],
    news_sources: [{
      source_id: 'eastmoney-search', status: 'SUCCESS', query_count: 24,
      status_counts: { SUCCESS: 24, EMPTY: 0, PARTIAL: 0, STALE: 0, UNAVAILABLE: 0, FAILED: 0 },
      result_count: 240, call_count: 24, retry_count: 1, duration_ms: 1234,
      error_codes: [],
    }],
    counts: { provider_results: 240, normalized_documents: 182, evidence_events: 35 },
    coverage: 'COMPLETE', coverage_notice: null,
  })

  renderPage()

  expect(await screen.findByText('本次实际获取')).toBeVisible()
  expect(screen.getByText('akshare-ths')).toBeVisible()
  expect(screen.getByText('实际字段：板块代码、板块名称')).toBeVisible()
  expect(screen.getByText('eastmoney-search')).toBeVisible()
  expect(screen.getByText('Provider 返回')).toBeVisible()
  expect(screen.getByText('240')).toBeVisible()
  expect(screen.getByText('规范化保存')).toBeVisible()
  expect(screen.getByText('182')).toBeVisible()
  expect(screen.getByText('进入证据链')).toBeVisible()
  expect(screen.getByText('35')).toBeVisible()
})

it('distinguishes unavailable market fields from an explicit zero', async () => {
  vi.mocked(api.fetchDataRunMarket).mockResolvedValue({
    snapshots: [], kind: 'INDUSTRY', total: 2, offset: 0, limit: 20,
    items: [{
      sector_id: 'missing', name: '缺字段板块', kind: 'INDUSTRY', pct_change: '0',
      turnover_rate: null, total_market_cap: null, advancers: 0, decliners: 0,
      leader_name: null, leader_pct_change: null, breadth_ratio: '0',
      field_availability: { pct_change: false, turnover_rate: false },
    }, {
      sector_id: 'zero', name: '真实零值板块', kind: 'INDUSTRY', pct_change: '0',
      turnover_rate: '0', total_market_cap: null, advancers: 0, decliners: 0,
      leader_name: null, leader_pct_change: null, breadth_ratio: '0',
      field_availability: { pct_change: true, turnover_rate: true },
    }],
  })

  renderPage()

  const missingRow = (await screen.findByText('缺字段板块')).closest('tr')!
  expect(missingRow).toHaveTextContent('未返回')
  expect(missingRow).not.toHaveTextContent('0%')
  const zeroRow = screen.getByText('真实零值板块').closest('tr')!
  expect(zeroRow).toHaveTextContent('0%')
})

it('explains partial industry coverage and list-only concepts', async () => {
  const snapshots = [{
    kind: 'INDUSTRY' as const,
    provider_id: 'akshare-ths',
    classification_version: 'ths-industry',
    source_version: '1.18.87',
    observed_at: '2026-08-25T07:00:00Z',
    collected_at: '2026-08-25T07:01:00Z',
    sector_count: 90,
    available_fields: [
      'provider_sector_id', 'name', 'pct_change', 'advancers', 'decliners',
      'leader_name', 'leader_pct_change',
    ],
  }, {
    kind: 'CONCEPT' as const,
    provider_id: 'akshare-ths',
    classification_version: 'ths-concept',
    source_version: '1.18.87',
    observed_at: '2026-08-25T07:00:00Z',
    collected_at: '2026-08-25T07:01:00Z',
    sector_count: 375,
    available_fields: ['provider_sector_id', 'name'],
  }]
  vi.mocked(api.fetchDataRunMarket).mockImplementation(async (_runId, kind) => ({
    snapshots,
    kind,
    items: kind === 'INDUSTRY' ? [{
      sector_id: '881121', name: '半导体', kind: 'INDUSTRY', pct_change: '2.3',
      turnover_rate: null, total_market_cap: null, advancers: 20, decliners: 4,
      leader_name: '测试股份', leader_pct_change: '9.8', breadth_ratio: '0.83',
      field_availability: {
        pct_change: true, turnover_rate: false, total_market_cap: false,
        advancers: true, decliners: true, leader_name: true, leader_pct_change: true,
      },
    }] : [{
      sector_id: '308614', name: '阿尔茨海默概念', kind: 'CONCEPT', pct_change: '0',
      turnover_rate: null, total_market_cap: null, advancers: 0, decliners: 0,
      leader_name: null, leader_pct_change: null, breadth_ratio: '0.5',
      field_availability: {
        pct_change: false, turnover_rate: false, total_market_cap: false,
        advancers: false, decliners: false, leader_name: false, leader_pct_change: false,
      },
    }],
    total: 1,
    offset: 0,
    limit: 20,
  }))

  renderPage()

  expect(await screen.findByText('部分行情字段')).toBeVisible()
  expect(screen.getByText('未返回：换手率、总市值')).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: '概念' }))
  expect(await screen.findByText('仅板块清单，不参与行情排序')).toBeVisible()
})

it('shows independently filterable provider news records and historical coverage', async () => {
  vi.mocked(api.fetchDataRunNewsRecords).mockResolvedValue({
    items: [{
      document_id: 'doc-raw-1', source_id: 'eastmoney-search',
      citation_url: 'https://example.com/raw-news', title: 'Provider 原始新闻标题',
      publisher: '东方财富', summary: '这是规范化保存的新闻摘要。',
      published_at: '2026-08-25T06:00:00Z', source_observed_at: '2026-08-25T06:01:00Z',
      collected_at: '2026-08-25T07:00:00Z', source_grade: 'REPUTABLE_MEDIA',
      query_ids: ['query-1'], query_type: 'sector', query_status: 'SUCCESS',
      query_source_id: 'eastmoney-search',
    }],
    total: 1, offset: 0, limit: 20, coverage: 'LINKED_ONLY',
    coverage_notice: '历史运行仅保留进入证据链的新闻记录。',
  })

  renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: '新闻记录' }))

  expect(await screen.findByText('Provider 原始新闻标题')).toBeVisible()
  expect(screen.getByText('这是规范化保存的新闻摘要。')).toBeVisible()
  expect(screen.getByText('历史运行仅保留进入证据链的新闻记录。')).toBeVisible()
  expect(screen.getByRole('link', { name: '查看原文' })).toHaveAttribute('href', 'https://example.com/raw-news')
  await userEvent.click(screen.getByRole('button', { name: '查看已保存详情' }))
  expect(await screen.findByRole('dialog', { name: 'Provider 原始新闻标题' })).toBeVisible()
  expect(screen.getByText('系统未保存新闻全文')).toBeVisible()
})

it('explains how evidence was mapped to a sector', async () => {
  vi.mocked(api.fetchDataRunEvidence).mockResolvedValue({
    total: 1,
    events: [{
      event_id: 'event-1', canonical_title: '机器人产业新闻',
      first_published_at: '2026-08-25T06:00:00Z', deduplication_reason: 'canonical_url',
      sector_ids: ['industry-1'], documents: [],
      links: [{
        sector_id: 'industry-1', sector_kind: 'INDUSTRY', sector_name: '机器人',
        relation_type: 'DIRECT', matched_entities: ['机器人'],
        mapping_confidence: 'HIGH', mapping_reason: '板块名称精确命中',
      }],
    }],
  })

  renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: '新闻证据' }))

  expect(await screen.findByText('机器人（行业）')).toBeVisible()
  expect(screen.getByText('置信度 HIGH')).toBeVisible()
  expect(screen.getByText('命中实体：机器人')).toBeVisible()
  expect(screen.getByText('板块名称精确命中')).toBeVisible()
})
