import DraftWorkspace from '../components/review/DraftWorkspace'
import EvidenceDecisionPane from '../components/review/EvidenceDecisionPane'
import ReviewQueue from '../components/review/ReviewQueue'
import EmptyState from '../components/ui/EmptyState'
import { useFeedback } from '../components/ui/FeedbackProvider'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import useReviewWorkspace from '../hooks/useReviewWorkspace'
import {
  applyDraftPatch, approveDraft, approvedExportUrl,
  recordEvidenceDecision, returnDraft, revokeDraft,
} from '../editingApi'

export default function ReviewWorkspacePage() {
  const feedback = useFeedback()
  const workspace = useReviewWorkspace()
  const {
    runs, selectedId, selectedRun, versions, governance, approval, decisions,
    initialLoading, workspaceLoading, queueError, workspaceError,
  } = workspace

  const runAction = async (
    action: () => Promise<void>, successMessage: string, errorMessage: string,
  ) => {
    try {
      await action()
      await workspace.refreshWorkspace()
      feedback.success(successMessage)
    } catch {
      feedback.error(errorMessage)
    }
  }

  const latest = versions[versions.length - 1]

  return <section className="review-page">
    <PageHeader title="审核工作台" description="集中阅读、修改和核准已生成的分析草稿。" />
    {initialLoading && <LoadingState label="正在加载审核队列…" />}
    {queueError && <InlineAlert tone="error" title="无法加载审核队列">{queueError}</InlineAlert>}
    {workspaceError && versions.length > 0 && <InlineAlert tone="warning" title="显示最近一次成功数据">{workspaceError}</InlineAlert>}
    {!initialLoading && !queueError && runs.length === 0 && <EmptyState title="暂无可审核草稿" description="先创建一次 Fixture 或 Live 分析，草稿完成后会进入这里。" />}
    {runs.length > 0 && <div className="review-workspace">
      <ReviewQueue runs={runs} selectedId={selectedId} onSelect={workspace.selectRun} />
      <div className="review-layout" role="region" aria-label="审核主工作区">
      {selectedRun && workspaceLoading && !latest && <main className="draft-workspace" aria-label="草稿编辑区"><LoadingState label="正在加载草稿与证据…" /></main>}
      {selectedRun && workspaceError && !latest && <main className="draft-workspace" aria-label="草稿编辑区"><InlineAlert tone="error" title="无法加载审核材料">{workspaceError}<div><button className="button button-secondary" type="button" onClick={() => void workspace.refreshWorkspace()}>重新加载</button></div></InlineAlert></main>}
      {selectedRun && latest && <>
        <DraftWorkspace versions={versions} onSave={async (input) => {
          try {
            await applyDraftPatch(selectedRun.run_id, selectedRun.draft_id!, input)
            await workspace.refreshWorkspace()
            feedback.success('修改已保存为新版本。')
          } catch (error) {
            feedback.error('修改保存失败，请刷新草稿后重试。')
            throw error
          }
        }} />
        <EvidenceDecisionPane
          version={latest}
          governance={governance}
          approval={approval}
          decisions={decisions}
          exportUrl={approval?.status === 'APPROVED_FOR_COPY'
            ? approvedExportUrl(selectedRun.run_id, selectedRun.draft_id!) : undefined}
          onDecision={(sourceId, decision, reason) => runAction(async () => {
            await recordEvidenceDecision(selectedRun.run_id, selectedRun.draft_id!, {
              source_id: sourceId, decision, reason,
            })
          }, '证据决定已记录。', '证据决定保存失败，请稍后重试。')}
          onApprove={() => runAction(async () => {
            await approveDraft(selectedRun.run_id, selectedRun.draft_id!)
          }, `草稿 v${latest.version} 已批准。`, '批准失败，请刷新草稿状态后重试。')}
          onRevoke={() => runAction(async () => {
            await revokeDraft(selectedRun.run_id, selectedRun.draft_id!)
          }, '批准已撤销。', '撤销批准失败，请稍后重试。')}
          onReturn={(reason) => runAction(async () => {
            await returnDraft(selectedRun.run_id, selectedRun.draft_id!, reason)
          }, `草稿 v${latest.version} 已退回修改。`, '退回操作失败，请稍后重试。')}
        />
      </>}
      </div>
    </div>}
  </section>
}
