import { useEffect, useMemo, useState } from 'react'
import { fetchDraft, fetchEvidence, fetchRuns, type DraftVersionView, type RunSummary } from '../api'
import DraftWorkspace from '../components/review/DraftWorkspace'
import EvidenceDecisionPane from '../components/review/EvidenceDecisionPane'
import ReviewQueue from '../components/review/ReviewQueue'
import EmptyState from '../components/ui/EmptyState'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import { useFeedback } from '../components/ui/FeedbackProvider'
import { applyDraftPatch, approveDraft, approvedExportUrl, fetchApproval, fetchEvidenceDecisions, fetchGovernance, recordEvidenceDecision, returnDraft, revokeDraft, type ApprovalView, type EvidenceDecisionView, type GovernanceResponse } from '../editingApi'

export default function ReviewWorkspacePage() {
  const feedback = useFeedback()
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [versions, setVersions] = useState<DraftVersionView[]>([])
  const [governance, setGovernance] = useState<GovernanceResponse | null>(null)
  const [approval, setApproval] = useState<ApprovalView | null>(null)
  const [decisions, setDecisions] = useState<EvidenceDecisionView[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const selectedRun = useMemo(() => runs.find((run) => run.run_id === selectedId) ?? null, [runs, selectedId])

  useEffect(() => {
    fetchRuns().then((items) => {
      const reviewable = items.filter((item) => item.draft_id && item.status !== 'RUNNING')
      setRuns(reviewable)
      setSelectedId(reviewable.find((item) => item.status === 'READY_FOR_HUMAN_REVIEW')?.run_id ?? reviewable[0]?.run_id ?? null)
    }).catch(() => setLoadError(true)).finally(() => setLoading(false))
  }, [])

  const loadWorkspace = async (run: RunSummary) => {
    if (!run.draft_id) return
    try {
      const [draft, evidence, report, currentApproval, decisionItems] = await Promise.all([fetchDraft(run.run_id), fetchEvidence(run.run_id), fetchGovernance(run.run_id), fetchApproval(run.run_id, run.draft_id), fetchEvidenceDecisions(run.run_id, run.draft_id)])
      void evidence
      setVersions(draft.versions); setGovernance(report); setApproval(currentApproval); setDecisions(decisionItems)
    } catch { feedback.error('无法加载审核材料，请稍后重试。') }
  }

  useEffect(() => { setVersions([]); if (selectedRun) void loadWorkspace(selectedRun) }, [selectedRun?.run_id])
  const latest = versions[versions.length - 1]

  return <section><PageHeader title="审核工作台" description="集中阅读、修改和核准已生成的分析草稿。" />{loading && <LoadingState label="正在加载审核队列…" />}{loadError && <InlineAlert tone="error" title="无法加载审核队列">请确认服务可用后刷新页面。</InlineAlert>}{!loading && !loadError && runs.length === 0 && <EmptyState title="暂无可审核草稿" description="先创建一次 Fixture 或 Live 分析，草稿完成后会进入这里。" />}{runs.length > 0 && <div className="review-layout"><ReviewQueue runs={runs} selectedId={selectedId} onSelect={setSelectedId} />{selectedRun && !latest && <main className="draft-workspace"><LoadingState label="正在加载草稿与证据…" /></main>}{selectedRun && latest && <><DraftWorkspace versions={versions} onSave={async (input) => { try { await applyDraftPatch(selectedRun.run_id, selectedRun.draft_id!, input); await loadWorkspace(selectedRun); feedback.success('修改已保存为新版本。') } catch (error) { feedback.error('修改保存失败，请刷新草稿后重试。'); throw error } }} /><EvidenceDecisionPane version={latest} governance={governance} approval={approval} decisions={decisions} exportUrl={approval?.status === 'APPROVED_FOR_COPY' ? approvedExportUrl(selectedRun.run_id, selectedRun.draft_id!) : undefined} onDecision={async (sourceId, decision, reason) => { await recordEvidenceDecision(selectedRun.run_id, selectedRun.draft_id!, { source_id: sourceId, decision, reason }); await loadWorkspace(selectedRun); feedback.success('证据决定已记录。') }} onApprove={async () => { setApproval(await approveDraft(selectedRun.run_id, selectedRun.draft_id!)); feedback.success(`草稿 v${latest.version} 已批准。`) }} onRevoke={async () => { setApproval(await revokeDraft(selectedRun.run_id, selectedRun.draft_id!)); feedback.success('批准已撤销。') }} onReturn={async (reason) => { await returnDraft(selectedRun.run_id, selectedRun.draft_id!, reason); feedback.success(`草稿 v${latest.version} 已退回修改。`) }} /></>}</div>}</section>
}
