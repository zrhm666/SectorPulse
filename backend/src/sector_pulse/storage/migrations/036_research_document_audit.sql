-- 036 资料库治理动作的审计表（规格 16.3）。
--
-- 这张表**刻意没有外键**指向 research_documents，与 research_retrieval_audits 的
-- 做法一致。物理清理删掉的是块与对象，文档行留着（版本被置为 PURGED），但"谁在什么时候
-- 删了这份资料"必须比它记录的东西活得更久；加上 ON DELETE CASCADE 就会让清理顺手抹掉
-- 自己的证据，而那是规格 16.3 第 6 步明确要求留下的东西。
--
-- 没有外键也意味着这里不会出现"因为父行被删而写不进去"的失败：审计写入是清理事务的
-- 最后一步，它不该有任何可能因别处的删除而失败的前提。
--
-- detail 的长度上限在这里，而它的"单行"规则只在领域模型里。原因很具体：这是通用迁移，
-- 同一份 SQL 要同时跑在 SQLite 与 PostgreSQL 上，而两个方言的换行探针拼法不同
-- （instr(x, char(10)) 与 strpos(x, chr(10))），写一个只在一边成立的 CHECK 会变成一条
-- 只在一边存在的规则。长度上限是"审计不是正文的安放处"在下界上已经够用的那一半：
-- 一篇正文放不进 500 个字符。
--
-- 本迁移在 Task 18 通过后即冻结。

CREATE TABLE IF NOT EXISTS research_document_audit (
    audit_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL CHECK (length(trim(document_id)) > 0),
    document_version_id TEXT,
    action TEXT NOT NULL CHECK (action IN (
        'register_document', 'register_version', 'set_source_weight', 'archive_version',
        'soft_delete', 'restore', 'rebuild_index', 'retry_ingestion', 'purge',
        'refuse_upload'
    )),
    actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
    detail TEXT NOT NULL CHECK (length(trim(detail)) > 0 AND length(detail) <= 500),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_document_audit_document
    ON research_document_audit (document_id, created_at);
