import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  confirmDataRunSelection,
  fetchDataRunCandidatePage,
  fetchDataRunNewsRecord,
  fetchDataRunSelection,
  fetchDataRunSummary,
  fetchDataRunAcquisition,
  fetchDataRunContentRun,
  fetchDataRunMarket,
  fetchDataRunNewsRecords,
  generateDataRunArticle,
  retryDataRun,
} from './dataRunsApi'


function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}


describe('data run workbench api', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('encodes market kind and pagination', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({
      snapshots: [], kind: 'CONCEPT', items: [], total: 0, offset: 20, limit: 20,
    }))

    await fetchDataRunMarket('run/id', 'CONCEPT', 20, 20)

    expect(fetch).toHaveBeenCalledWith(
      '/api/data-runs/run%2Fid/market?kind=CONCEPT&offset=20&limit=20',
      undefined,
    )
  })

  it('encodes candidate search, sorting and pagination', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({
      items: [], total: 0, offset: 20, limit: 10, query: '农业',
      sort: 'news_count', direction: 'desc', data_version: 'a'.repeat(64),
    }))
    const controller = new AbortController()

    await fetchDataRunCandidatePage('run/id', {
      query: '农业', sort: 'news_count', direction: 'desc', offset: 20, limit: 10,
    }, controller.signal)

    expect(fetch).toHaveBeenCalledWith(
      '/api/data-runs/run%2Fid/candidates?query=%E5%86%9C%E4%B8%9A&sort=news_count&direction=desc&offset=20&limit=10',
      { signal: controller.signal },
    )
  })

  it('loads and confirms an immutable candidate selection version', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ confirmed: false, version: 0 }))
      .mockResolvedValueOnce(jsonResponse({ confirmed: true, version: 1 }))

    await fetchDataRunSelection('run-1')
    await confirmDataRunSelection('run-1', ['a', 'b', 'c'], 0)

    expect(fetch).toHaveBeenNthCalledWith(1, '/api/data-runs/run-1/selection', undefined)
    expect(fetch).toHaveBeenNthCalledWith(2, '/api/data-runs/run-1/selection', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sector_ids: ['a', 'b', 'c'], expected_version: 0 }),
    })
  })

  it('loads workflow summary and one news detail with cancellation support', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ workflow_stage: 'ATTRIBUTION_READY' }))
      .mockResolvedValueOnce(jsonResponse({ document_id: 'doc/1', content_kind: 'SUMMARY' }))
    const controller = new AbortController()

    await fetchDataRunSummary('run-1', controller.signal)
    await fetchDataRunNewsRecord('run-1', 'doc/1', controller.signal)

    expect(fetch).toHaveBeenNthCalledWith(
      1, '/api/data-runs/run-1/summary', { signal: controller.signal },
    )
    expect(fetch).toHaveBeenNthCalledWith(
      2, '/api/data-runs/run-1/news-records/doc%2F1', { signal: controller.signal },
    )
  })

  it('parses an absent content run as null', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(null))

    await expect(fetchDataRunContentRun('run-1')).resolves.toBeNull()
  })

  it('loads the acquisition summary for a run', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({
      market_sources: [], news_sources: [], counts: {}, coverage: 'COMPLETE',
    }))

    await fetchDataRunAcquisition('run/id')

    expect(fetch).toHaveBeenCalledWith('/api/data-runs/run%2Fid/acquisition', undefined)
  })

  it('encodes news record filters and pagination', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({
      items: [], total: 0, offset: 20, limit: 20, coverage: 'COMPLETE',
    }))

    await fetchDataRunNewsRecords('run/id', {
      sourceId: 'east money', status: 'SUCCESS', offset: 20, limit: 20,
    })

    expect(fetch).toHaveBeenCalledWith(
      '/api/data-runs/run%2Fid/news-records?source_id=east+money&status=SUCCESS&offset=20&limit=20',
      undefined,
    )
  })

  it('posts retry and returns the new run id', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ run_id: 'run-2' }))

    await expect(retryDataRun('run-1')).resolves.toEqual({ run_id: 'run-2' })
    expect(fetch).toHaveBeenCalledWith('/api/data-runs/run-1/retry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
  })

  it('starts generation from the server-confirmed candidate version', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ run_id: 'run-1' }))

    await generateDataRunArticle('run/id')

    expect(fetch).toHaveBeenCalledWith('/api/data-runs/run%2Fid/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
  })

  it('uses the API detail when a request fails', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'run cannot be retried' }, 409))

    await expect(retryDataRun('run-1')).rejects.toThrow('run cannot be retried')
  })
})
