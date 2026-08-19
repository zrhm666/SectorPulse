import { useState } from 'react'
import { approvedExportUrl, approveDraft, revokeDraft, type ApprovalView, type GovernanceResponse } from '../../editingApi'

export default function ApprovalCard(props: { runId: string; draftId: string; governance: GovernanceResponse }) {
  const [approval, setApproval] = useState<ApprovalView | null>(null)
  const [error, setError] = useState('')
  async function approve() {
    try { setApproval(await approveDraft(props.runId, props.draftId)); setError('') }
    catch (err) { setError(err instanceof Error ? err.message : '核准失败') }
  }
  async function revoke() {
    try { setApproval(await revokeDraft(props.runId, props.draftId)); setError('') }
    catch (err) { setError(err instanceof Error ? err.message : '撤销失败') }
  }
  return (
    <div className="card">
      <h4>发布前核准</h4>
      {approval && <p>当前状态：{approval.status}（v{approval.version}）</p>}
      <button type="button" disabled={!((props.governance.passed ?? props.governance.status === 'PASS'))} onClick={approve}>核准并允许复制</button>
      <button type="button" disabled={!approval || approval.status !== 'APPROVED_FOR_COPY'} onClick={revoke}>撤销核准</button>
      {approval?.status === 'APPROVED_FOR_COPY' && <a href={approvedExportUrl(props.runId, props.draftId)}>导出 JSON</a>}
      {error && <p role="alert">{error}</p>}
    </div>
  )
}
