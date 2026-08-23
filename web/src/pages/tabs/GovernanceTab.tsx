import { useEffect, useState } from 'react'
import InlineAlert from '../../components/ui/InlineAlert'
import LoadingState from '../../components/ui/LoadingState'
import { fetchGovernance, type GovernanceResponse } from '../../editingApi'
import GovernanceCard from './GovernanceCard'

export default function GovernanceTab({ runId }: { runId: string }) {
  const [report, setReport] = useState<GovernanceResponse | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => { fetchGovernance(runId).then(setReport).catch(() => setFailed(true)) }, [runId])
  if (failed) return <InlineAlert tone="error" title="无法加载治理报告">草稿可能尚未生成，或治理服务暂不可用。</InlineAlert>
  if (!report) return <LoadingState label="正在加载治理报告…" />
  return <GovernanceCard report={report} />
}
