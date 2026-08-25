import type { MarketSnapshotSummary } from '../../dataRunsApi'

const MARKET_FIELDS = [
  'pct_change',
  'turnover_rate',
  'total_market_cap',
  'advancers',
  'decliners',
  'leader_name',
  'leader_pct_change',
] as const

const FIELD_LABELS: Record<(typeof MARKET_FIELDS)[number], string> = {
  pct_change: '涨跌幅',
  turnover_rate: '换手率',
  total_market_cap: '总市值',
  advancers: '上涨家数',
  decliners: '下跌家数',
  leader_name: '领涨股',
  leader_pct_change: '领涨幅',
}

export type MarketCapability = {
  level: 'full' | 'partial' | 'list-only' | 'unknown'
  label: string
  notice: string | null
  missingFields: string[]
}

export function marketCapability(source: MarketSnapshotSummary): MarketCapability {
  if (source.available_fields == null) {
    return {
      level: 'unknown',
      label: '字段覆盖未记录',
      notice: '历史快照未记录 Provider 字段覆盖信息',
      missingFields: [],
    }
  }
  const available = new Set(source.available_fields)
  const missingFields = MARKET_FIELDS.filter((field) => !available.has(field))
  if (missingFields.length === 0) {
    return { level: 'full', label: '完整行情字段', notice: null, missingFields: [] }
  }
  if (!available.has('pct_change')) {
    return {
      level: 'list-only',
      label: '仅板块清单',
      notice: '仅板块清单，不参与行情排序',
      missingFields: [...missingFields],
    }
  }
  return {
    level: 'partial',
    label: '部分行情字段',
    notice: `未返回：${missingFields.map((field) => FIELD_LABELS[field]).join('、')}`,
    missingFields: [...missingFields],
  }
}
