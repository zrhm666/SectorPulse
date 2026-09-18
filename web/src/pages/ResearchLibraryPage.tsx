import { useCallback, useEffect, useMemo, useState } from 'react'
import ConfirmDialog from '../components/ui/ConfirmDialog'
import EmptyState from '../components/ui/EmptyState'
import InlineAlert from '../components/ui/InlineAlert'
import LoadingState from '../components/ui/LoadingState'
import ManagementDrawer from '../components/ui/ManagementDrawer'
import PageHeader from '../components/ui/PageHeader'
import Panel from '../components/ui/Panel'
import SummaryStrip from '../components/ui/SummaryStrip'
import { useFeedback } from '../components/ui/FeedbackProvider'
import DocumentDetailDrawer from './research-library/DocumentDetailDrawer'
import DocumentTable from './research-library/DocumentTable'
import DocumentUploadPanel from './research-library/DocumentUploadPanel'
import {
  ResearchLibraryDisabledError,
  fetchDocuments,
  restoreDocument,
  softDeleteDocument,
  type ResearchDocument,
  type ResearchDocumentListItem,
} from '../researchLibraryApi'

// 三个刻意的取舍：
//
// 1. **列表一律带上已删除的资料**。不带的话，"恢复"这条路径在界面上根本走不到——一份被
//    删除的资料会从唯一能恢复它的地方消失。
// 2. **执行人是页面级的，不是每个动作问一次**。治理动作要么署名，要么根本不成立：没有
//    执行人时，上传、归档、删除、恢复一律不可点，而"查看详情"和"下载原件"是读取，照常可用。
// 3. **页面上没有模型与存储配置，也没有对象键和索引代**。那些是"我们怎么做的"，不是
//    "这份资料是什么"；后端也不发这些字段。

const ACTOR_HINT = '治理动作需要署名：请先填写执行人。'

export default function ResearchLibraryPage() {
  const [items, setItems] = useState<ResearchDocumentListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [state, setState] = useState<'ready' | 'disabled' | 'failed'>('ready')
  const [actor, setActor] = useState('')
  const [uploading, setUploading] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<ResearchDocument | null>(null)
  const [openDocumentId, setOpenDocumentId] = useState<string | null>(null)
  const feedback = useFeedback()

  const load = useCallback(() => {
    let active = true
    setLoading(true)
    setState('ready')
    fetchDocuments({ includeDeleted: true })
      .then((result) => {
        if (active) setItems(result.documents)
      })
      .catch((error: unknown) => {
        // "这个部署没有资料库"是正常形态，不是错误态：它该显示成空态并说明原因，而不是
        // 让运维去查一台本来就没问题的服务。
        if (active) setState(error instanceof ResearchLibraryDisabledError ? 'disabled' : 'failed')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => load(), [load])

  const summary = useMemo(() => {
    const published = items.filter((item) =>
      item.versions.some(
        (version) =>
          version.document_version_id === item.document.current_version_id && version.status === 'ACTIVE',
      ),
    )
    const pending = items.filter((item) => item.latest_job !== null && item.latest_job.status !== 'PUBLISHED')
    const deleted = items.filter((item) => item.document.deleted_at !== null)
    return { published: published.length, pending: pending.length, deleted: deleted.length }
  }, [items])

  const actorReady = actor.trim().length > 0

  const confirmDelete = async () => {
    if (!pendingDelete) return
    const target = pendingDelete
    setPendingDelete(null)
    try {
      await softDeleteDocument(target.document_id, actor.trim())
      feedback.success('资料已删除；保留期内可以恢复。')
      load()
    } catch {
      feedback.error('删除没有成功，请稍后重试。')
    }
  }

  const restore = async (document: ResearchDocument) => {
    try {
      await restoreDocument(document.document_id, { actor: actor.trim() })
      feedback.success('资料已恢复。')
      load()
    } catch {
      feedback.error('恢复没有成功，请稍后重试。')
    }
  }

  return (
    <section className="management-page">
      <PageHeader
        title="内部资料库"
        description="上传、查看和治理内部研究资料。只有已发布的版本会被 A2 检索到。"
        meta={
          <label className="research-actor">
            执行人
            <input
              value={actor}
              maxLength={200}
              placeholder="姓名"
              onChange={(event) => setActor(event.target.value)}
            />
          </label>
        }
        actions={
          <button
            className="button button-primary"
            type="button"
            disabled={!actorReady}
            onClick={() => setUploading(true)}
          >
            上传资料
          </button>
        }
      />

      {!loading && state === 'ready' && (
        <SummaryStrip
          label="资料库概览"
          items={[
            { label: '资料总数', value: items.length },
            { label: '已发布版本', value: summary.published },
            { label: '摄取未完成', value: summary.pending },
            { label: '已删除资料', value: summary.deleted },
          ]}
        />
      )}

      {!actorReady && !loading && state === 'ready' && (
        <InlineAlert tone="info" title="治理动作需要署名">
          <p>{ACTOR_HINT}</p>
        </InlineAlert>
      )}

      <Panel
        density="compact"
        title="资料列表"
        description="已删除的资料会保留到保留期结束，之后可审计地清理。"
      >
        {loading && <LoadingState label="正在加载资料库…" />}

        {!loading && state === 'failed' && (
          <InlineAlert tone="error" title="无法加载资料库">
            <p>请确认服务可用后重试。</p>
            <button className="button button-secondary" type="button" onClick={load}>
              重新加载
            </button>
          </InlineAlert>
        )}

        {!loading && state === 'disabled' && (
          <EmptyState
            title="资料库未启用"
            description="这个部署没有开启内部研究资料库（RAG）。开启后，在这里上传的资料才能被 A2 检索到。"
          />
        )}

        {!loading && state === 'ready' && items.length === 0 && (
          <EmptyState
            title="还没有内部资料"
            description="上传第一份研究报告或公告，处理完成并校验通过后才会进入检索。"
          />
        )}

        {!loading && state === 'ready' && items.length > 0 && (
          <DocumentTable
            items={items}
            actorReady={actorReady}
            onOpen={setOpenDocumentId}
            onDelete={setPendingDelete}
            onRestore={restore}
          />
        )}
      </Panel>

      <ManagementDrawer
        open={uploading}
        title="上传资料"
        description="上传是一次署名动作；新版本会在校验通过后原子替换旧版本。"
        onClose={() => setUploading(false)}
      >
        <DocumentUploadPanel
          items={items}
          actor={actor}
          onCancel={() => setUploading(false)}
          onUploaded={() => {
            setUploading(false)
            feedback.success('上传已登记，处理完成后会自动发布。')
            load()
          }}
        />
      </ManagementDrawer>

      <DocumentDetailDrawer
        open={openDocumentId !== null}
        documentId={openDocumentId}
        actor={actor}
        onClose={() => setOpenDocumentId(null)}
        onChanged={load}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        title="确认删除这份资料"
        description={
          pendingDelete
            ? `「${pendingDelete.title}」会立即退出检索，保留期内可以恢复。`
            : ''
        }
        confirmLabel="删除"
        tone="danger"
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </section>
  )
}
