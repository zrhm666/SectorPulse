import { useState } from 'react'
import DraftWorkspace from '../components/review/DraftWorkspace'
import EvidenceDecisionPane from '../components/review/EvidenceDecisionPane'
import ReviewPaneTabs, { type ReviewPane } from '../components/review/ReviewPaneTabs'
import ReviewQueue from '../components/review/ReviewQueue'
import EmptyState from '../components/ui/EmptyState'
import { useFeedback } from '../components/ui/FeedbackProvider'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import useReviewWorkspace from '../hooks/useReviewWorkspace'
import {
  applyDraftPatch, approveDraft, approvedExportUrl,
  recordEvidenceDecision, returnDraft, ReviewApiError, revokeDraft,
} from '../editingApi'

export default function ReviewWorkspacePage() {
  const feedback = useFeedback()
  const [activePane, setActivePane] = useState<ReviewPane>('draft')
  const [hasPendingEdits, setHasPendingEdits] = useState(false)
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
      <ReviewPaneTabs active={activePane} onChange={setActivePane} />
      <div className="review-workspace__grid" role="region" aria-label="审核主工作区">
        <div id="review-pane-queue" className="review-workspace__pane" role="tabpanel" aria-labelledby="review-tab-queue" data-pane="queue" data-active={activePane === 'queue'}>
          <ReviewQueue runs={runs} selectedId={selectedId} onSelect={(runId) => {
            if (hasPendingEdits) {
              feedback.error('当前草稿仍有未保存或冲突的修改，请处理后再切换运行。')
              return
            }
            workspace.selectRun(runId)
            setActivePane('draft')
          }} />
        </div>
        <div id="review-pane-draft" className="review-workspace__pane" role="tabpanel" aria-labelledby="review-tab-draft" data-pane="draft" data-active={activePane === 'draft'}>
          {selectedRun && workspaceLoading && !latest && <main className="draft-workspace" aria-label="草稿编辑区"><LoadingState label="正在加载草稿与证据…" /></main>}
          {selectedRun && workspaceError && !latest && <main className="draft-workspace" aria-label="草稿编辑区"><InlineAlert tone="error" title="无法加载审核材料">{workspaceError}<div><button className="button button-secondary" type="button" onClick={() => void workspace.refreshWorkspace()}>重新加载</button></div></InlineAlert></main>}
          {selectedRun && latest && <DraftWorkspace versions={versions} onPendingChange={setHasPendingEdits} onSave={async (input) => {
          try {
            const result = await applyDraftPatch(selectedRun.run_id, selectedRun.draft_id!, input)
            await workspace.refreshWorkspace()
            return result
          } catch (error) {
            if (error instanceof ReviewApiError && error.code === 'CONFLICT') {
              await workspace.refreshWorkspace()
              feedback.error('草稿已被其他修改更新；本地文本已保留，请重试保存。')
            } else {
              feedback.error('修改保存失败，本地文本已保留，请检查连接后重试。')
            }
            throw error
          }
          }} />}
        </div>
        <div id="review-pane-evidence" className="review-workspace__pane" role="tabpanel" aria-labelledby="review-tab-evidence" data-pane="evidence" data-active={activePane === 'evidence'}>
          {selectedRun && latest && <EvidenceDecisionPane
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
          />}
        </div>
      </div>
    </div>}
  </section>
}
