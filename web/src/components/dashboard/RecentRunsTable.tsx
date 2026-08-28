import { Link } from 'react-router-dom'
import type { OperationsRecentRun } from '../../operationsApi'
import { formatDate, formatDuration } from '../../runPresentation'
import EmptyState from '../ui/EmptyState'
import Panel from '../ui/Panel'
import StatusBadge from '../ui/StatusBadge'

export default function RecentRunsTable({ runs }: { runs: OperationsRecentRun[] }) {
  return (
    <Panel
      className="operations-recent"
      title="最近运行"
      description="展示真实场景、状态、来源和运行信息。"
      actions={<Link to="/runs">查看全部运行</Link>}
    >
      {runs.length === 0 ? (
        <EmptyState title="还没有运行记录" description="新建一次分析后，最近运行会显示在这里。" action={<Link className="button button--primary" to="/runs/new">新建分析</Link>} />
      ) : (
        <div className="operations-recent__viewport">
          <table className="operations-recent__table">
            <thead><tr><th>运行</th><th>状态</th><th>Provider</th><th>候选板块</th><th>创建时间</th><th>耗时</th><th><span className="visually-hidden">操作</span></th></tr></thead>
            <tbody>
              {runs.map((run) => (
                <tr key={`${run.kind}-${run.run_id}`}>
                  <td><Link className="operations-recent__run" to={run.detail_path}><code>{run.run_id.slice(0, 8)}</code><span>{run.mode}</span></Link></td>
                  <td><StatusBadge status={run.status} /></td>
                  <td>{run.provider}</td>
                  <td>{run.candidate_count == null ? '暂无' : `${run.candidate_count} 个`}</td>
                  <td>{formatDate(run.requested_at)}</td>
                  <td>{run.finished_at ? formatDuration(run.elapsed_ms) : '进行中'}</td>
                  <td><Link to={run.detail_path}>查看</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}
