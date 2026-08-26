import { useEffect, useState } from 'react'
import type { DraftVersionView } from '../../api'
import type { ApprovalView, EvidenceDecisionView, GovernanceResponse } from '../../editingApi'
import ConfirmDialog from '../ui/ConfirmDialog'
import StatusBadge from '../ui/StatusBadge'

type Source = { source_id?: string; title?: string; publisher?: string; citation_url?: string | null }

type Props = {
  version: DraftVersionView
  governance: GovernanceResponse | null
  approval: ApprovalView | null
  decisions: EvidenceDecisionView[]
  exportUrl?: string
  onDecision: (sourceId: string, decision: string, reason: string) => Promise<void>
  onApprove: () => Promise<void>
  onRevoke: () => Promise<void>
  onReturn: (reason: string) => Promise<void>
}

const SOURCE_PREVIEW_LIMIT = 6

export default function EvidenceDecisionPane(props: Props) {
  const [sourceId, setSourceId] = useState('')
  const [decision, setDecision] = useState('KEEP')
  const [decisionReason, setDecisionReason] = useState('')
  const [returnReason, setReturnReason] = useState('')
  const [confirm, setConfirm] = useState<'approve' | 'return' | null>(null)
  const [sourcesExpanded, setSourcesExpanded] = useState(false)
  const sources = props.version.sources as Source[]
  const visibleSources = sourcesExpanded ? sources : sources.slice(0, SOURCE_PREVIEW_LIMIT)
  const passed = props.governance?.passed ?? props.governance?.status === 'PASS'

  useEffect(() => {
    setSourcesExpanded(false)
  }, [props.version.version])

  return <aside className="evidence-pane" aria-label="证据与治理">
    <div className="review-pane__header">
      <div>
        <h2>证据与合规</h2>
        <p>核验来源，记录处置，最后完成审批。</p>
      </div>
      <StatusBadge status={passed ? 'SUCCESS' : 'BLOCKED'} label={passed ? '治理通过' : '治理未通过'} />
    </div>

    <section className="evidence-sources">
      <div className="evidence-section__heading">
        <h3>新闻来源</h3>
        {sources.length > 0 && <span>{sources.length} 条</span>}
      </div>
      {sources.length === 0
        ? <p className="status-detail">暂无来源。</p>
        : <>
          <ul className="source-list" aria-label="审核来源">
            {visibleSources.map((source) => <li key={source.source_id ?? source.title}>
              <strong>{source.title ?? '未命名来源'}</strong>
              {source.publisher && <small>{source.publisher}</small>}
              {source.citation_url
                ? <a href={source.citation_url} target="_blank" rel="noreferrer">查看来源</a>
                : <span>无可访问链接</span>}
            </li>)}
          </ul>
          {sources.length > SOURCE_PREVIEW_LIMIT && <button
            className="button button-secondary source-list__toggle"
            type="button"
            aria-expanded={sourcesExpanded}
            onClick={() => setSourcesExpanded((current) => !current)}
          >
            {sourcesExpanded ? '收起来源' : `展开全部 ${sources.length} 条来源`}
          </button>}
        </>}
    </section>

    {sources.length > 0 && <section className="decision-form">
      <h3>记录证据决定</h3>
      <label>来源
        <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
          <option value="">请选择</option>
          {sources.map((source) => <option key={source.source_id} value={source.source_id}>{source.title}</option>)}
        </select>
      </label>
      <label>决定
        <select value={decision} onChange={(event) => setDecision(event.target.value)}>
          <option value="KEEP">保留</option>
          <option value="DOWNGRADE">降级</option>
          <option value="REJECT">拒绝</option>
        </select>
      </label>
      <label>理由
        <textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} rows={3} />
      </label>
      <button className="button button-secondary" type="button" disabled={!sourceId || !decisionReason.trim()} onClick={async () => {
        await props.onDecision(sourceId, decision, decisionReason.trim())
        setDecisionReason('')
      }}>保存证据决定</button>
    </section>}

    <section>
      <h3>当前决定</h3>
      {props.decisions.length === 0
        ? <p className="status-detail">尚未记录证据决定。</p>
        : <ul className="decision-list">{props.decisions.map((item) => <li key={item.decision_id}>
          <strong>{item.source_id} · {item.decision}</strong>
          <span>{item.reason}</span>
        </li>)}</ul>}
    </section>

    <section className="review-actions">
      <div className="review-actions__heading">
        <h3>审核操作</h3>
        <span>草稿 v{props.version.version}</span>
      </div>
      {props.approval?.status === 'APPROVED_FOR_COPY'
        ? <>
          <button className="button button-secondary" onClick={props.onRevoke}>撤销批准</button>
          {props.exportUrl && <a className="button button-primary" href={props.exportUrl}>导出已批准版本</a>}
        </>
        : <button className="button button-primary" disabled={!passed} onClick={() => setConfirm('approve')}>批准复制</button>}
      <label>退回原因
        <textarea value={returnReason} onChange={(event) => setReturnReason(event.target.value)} rows={2} />
      </label>
      <button className="button button-secondary" disabled={!returnReason.trim()} onClick={() => setConfirm('return')}>退回修改</button>
    </section>

    <ConfirmDialog open={confirm === 'approve'} title={`批准草稿 v${props.version.version}`} description="批准后该版本可以导出和复制。" confirmLabel="确认批准" onCancel={() => setConfirm(null)} onConfirm={async () => { setConfirm(null); await props.onApprove() }} />
    <ConfirmDialog open={confirm === 'return'} title={`退回草稿 v${props.version.version}`} description={`退回原因：${returnReason}`} confirmLabel="确认退回" tone="danger" onCancel={() => setConfirm(null)} onConfirm={async () => { setConfirm(null); await props.onReturn(returnReason.trim()); setReturnReason('') }} />
  </aside>
}
