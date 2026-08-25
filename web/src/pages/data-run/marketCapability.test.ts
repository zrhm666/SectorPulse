import { describe, expect, it } from 'vitest'

import type { MarketSnapshotSummary } from '../../dataRunsApi'
import { marketCapability } from './marketCapability'

const source: MarketSnapshotSummary = {
  kind: 'INDUSTRY',
  provider_id: 'akshare-ths',
  classification_version: 'ths-industry',
  source_version: '1.18.87',
  observed_at: '2026-08-25T09:00:00Z',
  collected_at: '2026-08-25T09:00:01Z',
  sector_count: 90,
}

const fullFields = [
  'provider_sector_id',
  'name',
  'pct_change',
  'turnover_rate',
  'total_market_cap',
  'advancers',
  'decliners',
  'leader_name',
  'leader_pct_change',
]

describe('marketCapability', () => {
  it('identifies full market coverage', () => {
    expect(marketCapability({ ...source, available_fields: fullFields })).toEqual({
      level: 'full',
      label: '完整行情字段',
      notice: null,
      missingFields: [],
    })
  })

  it('identifies partial THS industry coverage', () => {
    expect(marketCapability({
      ...source,
      available_fields: [
        'provider_sector_id',
        'name',
        'pct_change',
        'advancers',
        'decliners',
        'leader_name',
        'leader_pct_change',
      ],
    })).toEqual({
      level: 'partial',
      label: '部分行情字段',
      notice: '未返回：换手率、总市值',
      missingFields: ['turnover_rate', 'total_market_cap'],
    })
  })

  it('identifies a list-only concept snapshot', () => {
    expect(marketCapability({
      ...source,
      kind: 'CONCEPT',
      available_fields: ['provider_sector_id', 'name'],
    })).toEqual({
      level: 'list-only',
      label: '仅板块清单',
      notice: '仅板块清单，不参与行情排序',
      missingFields: [
        'pct_change',
        'turnover_rate',
        'total_market_cap',
        'advancers',
        'decliners',
        'leader_name',
        'leader_pct_change',
      ],
    })
  })
})
