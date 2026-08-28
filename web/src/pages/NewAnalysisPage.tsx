import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { createRun, fetchFixtureInput } from '../api'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import AppIcon from '../components/ui/AppIcon'
import { createDataRun } from '../dataRunsApi'
import { fetchOperationsSummary, type OperationsSummary } from '../operationsApi'

type Mode = 'intraday' | 'post_close'
type Provider = 'fixture' | 'live'

const stages = ['场景', '执行方式', '参数确认', '启动']
const stageDescriptions = [
  '选择最符合当前工作时点的分析场景。',
  '选择安全演练或实时链路，并检查启动条件。',
  '核对本次请求真正会提交的参数。',
  '最后确认后启动；在此之前不会调用数据源或 LLM。',
]

export default function NewAnalysisPage() {
  const navigate = useNavigate()
  const [stage, setStage] = useState(0)
  const [mode, setMode] = useState<Mode>('intraday')
  const [provider, setProvider] = useState<Provider>('fixture')
  const [summary, setSummary] = useState<OperationsSummary | null>(null)
  const [preflightError, setPreflightError] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(false)
  const submitLock = useRef(false)

  const loadPreflight = useCallback(() => {
    setPreflightError(false)
    fetchOperationsSummary().then(setSummary).catch(() => setPreflightError(true))
  }, [])

  useEffect(() => { loadPreflight() }, [loadPreflight])

  const liveBlockers = useMemo(() => {
    if (!summary) return ['系统状态尚未加载完成']
    const items: string[] = []
    if (!summary.consent.live_data) items.push('在项目根目录创建 .live-data-consent，确认允许实时数据访问。')
    if (!summary.providers.live_data_available) items.push('实时数据源尚不可用，请按系统状态页中的缺失要求完成配置。')
    if (!summary.llm.configured) items.push('检查 .env 中的 LLM Provider、Base URL、API Key 和 Model。')
    if (!summary.consent.live_llm) items.push('在项目根目录创建 .live-llm-consent，确认允许真实 LLM 调用。')
    return items
  }, [summary])

  const blocked = provider === 'live' && liveBlockers.length > 0

  async function submit() {
    if (submitLock.current || blocked) return
    submitLock.current = true
    setSubmitting(true)
    setSubmitError(false)
    try {
      if (provider === 'fixture') {
        const input = await fetchFixtureInput()
        const result = await createRun(input, 'fixture')
        navigate(`/runs/${result.run_id}`)
      } else {
        const result = await createDataRun({ mode, provider: 'live', precandidate_limit: 30, final_candidate_limit: 12 })
        navigate(`/data-runs/${result.run_id}`)
      }
    } catch {
      setSubmitError(true)
      setSubmitting(false)
      submitLock.current = false
    }
  }

  return (
    <section className="analysis-launcher-page density-comfortable">
      <PageHeader
        title="新建分析"
        description="通过四个清晰步骤配置并启动一次真实分析。"
        actions={<Link className="button button-secondary" to="/runs">返回运行历史</Link>}
      />

      <ol className="stepper" aria-label="新建分析进度">
        {stages.map((label, index) => (
          <li key={label} data-state={index === stage ? 'current' : index < stage ? 'done' : 'upcoming'} aria-current={index === stage ? 'step' : undefined}>
            <span>{index + 1}</span><strong>{label}</strong>
          </li>
        ))}
      </ol>

      <div className="analysis-flow">
        <Panel title={stages[stage]} description={stageDescriptions[stage]}>
          {stage === 0 && (
            <div className="choice-grid">
              <button className="choice-card" data-selected={mode === 'intraday'} aria-pressed={mode === 'intraday'} onClick={() => setMode('intraday')} type="button">
                <AppIcon name="activity" /><strong>盘中分析</strong><span>聚焦交易时段内的板块变化，适合快速发现候选主题。</span>
              </button>
              <button className="choice-card" data-selected={mode === 'post_close'} aria-pressed={mode === 'post_close'} onClick={() => setMode('post_close')} type="button">
                <AppIcon name="clock" /><strong>盘后复盘</strong><span>使用收盘后的完整信息，适合形成当日复盘和次日观察清单。</span>
              </button>
            </div>
          )}

          {stage === 1 && (
            <>
              <div className="choice-grid">
                <button className="choice-card" data-selected={provider === 'fixture'} aria-pressed={provider === 'fixture'} onClick={() => setProvider('fixture')} type="button">
                  <AppIcon name="folder" /><strong>Fixture 演练</strong><span>使用内置样例，不拉取实时行情，也不消耗真实 LLM 额度。</span>
                </button>
                <button className="choice-card" data-selected={provider === 'live'} aria-pressed={provider === 'live'} onClick={() => setProvider('live')} type="button">
                  <AppIcon name="activity" /><strong>Live 实时运行</strong><span>拉取实时数据并在数据就绪后调用已配置的 LLM。</span>
                </button>
              </div>
              {preflightError && <InlineAlert tone="error" title="无法读取系统状态"><p>实时运行条件暂时无法确认。</p><button className="button button-secondary" type="button" onClick={loadPreflight}>重新检查</button></InlineAlert>}
              {!summary && !preflightError && <LoadingState label="正在检查运行条件…" />}
              {provider === 'live' && summary && liveBlockers.length > 0 && (
                <InlineAlert tone="warning" title="实时运行暂不可用"><ul>{liveBlockers.map((item) => <li key={item}>{item}</li>)}</ul></InlineAlert>
              )}
              {provider === 'live' && summary && liveBlockers.length === 0 && (
                <InlineAlert tone="success" title="实时运行条件已满足">数据授权、数据源、LLM 配置和调用授权均已就绪。</InlineAlert>
              )}
            </>
          )}

          {stage === 2 && (
            <dl className="summary-list">
              <div><dt>分析场景</dt><dd>{mode === 'intraday' ? '盘中分析' : '盘后复盘'}</dd></div>
              <div><dt>执行方式</dt><dd>{provider === 'fixture' ? 'Fixture 演练' : 'Live 实时运行'}</dd></div>
              <div><dt>候选范围</dt><dd>{provider === 'fixture' ? '内置可复现样例' : '预选 30 个，保留 12 个'}</dd></div>
              <div><dt>额度影响</dt><dd>{provider === 'fixture' ? '不消耗真实 LLM 额度' : `单次预算上限 ¥${summary?.llm.budget_cny_per_run ?? '待确认'}`}</dd></div>
            </dl>
          )}

          {stage === 3 && (
            <div className="launch-confirmation">
              <div className="launch-confirmation__mark"><AppIcon name="activity" /></div>
              <div>
                <strong>{provider === 'fixture' ? 'Fixture 分析已准备好' : '实时分析已准备好'}</strong>
                <p>{mode === 'intraday' ? '盘中分析' : '盘后复盘'} · {provider === 'fixture' ? '使用内置样例，不调用实时数据和真实 LLM' : '预选 30 个候选，最终保留 12 个'}</p>
              </div>
            </div>
          )}

          {submitError && <InlineAlert tone="error" title="分析未能启动">请求未成功，请检查系统状态后重试。</InlineAlert>}

          <div className="flow-actions">
            {stage > 0 && <button className="button button-secondary" type="button" disabled={submitting} onClick={() => setStage(stage - 1)}>上一步</button>}
            {stage < 3 && <button className="button button-primary" type="button" disabled={stage === 1 && blocked} onClick={() => setStage(stage + 1)}>{stage === 0 ? '下一步：选择执行方式' : stage === 1 ? '下一步：确认参数' : '下一步：启动'}</button>}
            {stage === 3 && <button className="button button-primary" type="button" disabled={submitting || blocked} onClick={submit}>{submitting ? '正在启动…' : provider === 'fixture' ? '启动 Fixture 分析' : '启动实时分析'}</button>}
          </div>
        </Panel>

        <aside className="flow-note launcher-summary" aria-label="本次分析摘要">
          <span className="launcher-summary__eyebrow">本次分析</span>
          <strong>{mode === 'intraday' ? '盘中分析' : '盘后复盘'}</strong>
          <dl>
            <div><dt>执行方式</dt><dd>{provider === 'fixture' ? 'Fixture 演练' : 'Live 实时运行'}</dd></div>
            <div><dt>候选范围</dt><dd>{provider === 'fixture' ? '内置样例' : '30 → 12'}</dd></div>
            <div><dt>当前步骤</dt><dd>{stage + 1} / 4</dd></div>
          </dl>
          <p>启动前不会调用数据源或 LLM；返回上一步不会丢失当前选择。</p>
        </aside>
      </div>
    </section>
  )
}
