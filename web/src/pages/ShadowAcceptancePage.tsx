import { useEffect, useState } from 'react'
import ShadowAcceptanceCard from '../components/ShadowAcceptanceCard'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import { fetchShadowProgress, fetchShadowRuns, type ShadowProgress, type ShadowRunView } from '../shadowApi'

export default function ShadowAcceptancePage() {
  const [runs, setRuns] = useState<ShadowRunView[]>([])
  const [progress, setProgress] = useState<ShadowProgress>()
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)

  useEffect(() => {
    let active = true

    Promise.all([fetchShadowRuns(), fetchShadowProgress()])
      .then(([runResult, progressResult]) => {
        if (!active) return
        setRuns(runResult)
        setProgress(progressResult)
      })
      .catch(() => {
        if (active) setLoadError(true)
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [])

  return (
    <section className="management-page">
      <PageHeader title="影子验收" description="只读查看已保存的真实验收进度和历史运行。" />
      <InlineAlert tone="warning" title="影子验收已暂停">
        当前不再追踪新的 20 个交易日记录；已有历史进度和运行记录会继续保留并展示。
      </InlineAlert>
      <Panel density="compact" title="历史验收进度">
        {loading && <LoadingState label="正在加载影子验收记录…" />}
        {!loading && loadError && (
          <InlineAlert tone="error" title="无法加载影子验收记录">请稍后刷新页面重试。</InlineAlert>
        )}
        {!loading && !loadError && <ShadowAcceptanceCard runs={runs} progress={progress} />}
      </Panel>
    </section>
  )
}
