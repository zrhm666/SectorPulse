import Button from '../../components/ui/Button'
import InlineAlert from '../../components/ui/InlineAlert'
import type { Membership, MissingReason } from '../../runComparisonsApi'

export const kindLabel = { INDUSTRY: '行业', CONCEPT: '概念' }
export const membershipLabel: Record<Membership, string> = { BOTH: '两次均留存', ONLY_BASE: '仅基准留存', ONLY_COMPARE: '仅对照留存' }
export const missingLabel: Record<MissingReason, string> = { FIELD_UNDECLARED: '字段口径未知', VALUE_MISSING: '未返回数值', SECTOR_MISSING: '未留存该板块' }
export const terminalDataStatuses = new Set(['READY_FOR_ATTRIBUTION', 'DEGRADED', 'BLOCKED', 'FAILED', 'CANCELLED', 'INTERRUPTED'])
export function QueryError({ title, error, retry, label = '重试' }: { title: string; error: string; retry: () => void; label?: string }) {
  return <InlineAlert tone="error" title={title}><p>{error}</p><Button variant="secondary" onClick={retry}>{label}</Button></InlineAlert>
}
export function ComparisonPagination({ offset, limit, total, busy, onPage }: { offset: number; limit: number; total: number; busy: boolean; onPage: (offset: number) => void }) {
  return <nav className="comparison-pagination" aria-label="结果分页">
    <span aria-live="polite">共 {total} 条 · {total ? `${offset + 1}–${Math.min(offset + limit, total)}` : '0 条'}</span>
    <Button variant="secondary" disabled={busy || offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}>上一页</Button>
    <Button variant="secondary" disabled={busy || offset + limit >= total} onClick={() => onPage(offset + limit)}>下一页</Button>
  </nav>
}
