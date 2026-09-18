-- 035 PostgreSQL 补充：把通用迁移里的 JSON 载荷列换成 JSONB。
--
-- 通用文件必须同时满足 SQLite，所以这些列先建成 TEXT；这里是权威库真正的形态。
-- 转换是原地 ALTER，不需要重建表：迁移刚建完这些表，此刻必定为空。
--
-- 仓库其它表保存 JSON 时用的是 TEXT，这里刻意不同：审计与检索痕迹是本库未来唯一
-- 需要按内容追问的载荷（例如“哪些检索采用了这一段候选”），JSONB 让这类排查不必
-- 先全表反序列化。写入侧因此必须显式 CAST(:param AS JSONB)。
--
-- 本迁移在 Task 3 通过后即冻结。

ALTER TABLE research_documents
    ALTER COLUMN access_tags_json DROP DEFAULT,
    ALTER COLUMN access_tags_json TYPE JSONB USING access_tags_json::jsonb,
    ALTER COLUMN access_tags_json SET DEFAULT '[]'::jsonb;

ALTER TABLE research_index_outbox
    ALTER COLUMN payload_json DROP DEFAULT,
    ALTER COLUMN payload_json TYPE JSONB USING payload_json::jsonb,
    ALTER COLUMN payload_json SET DEFAULT '{}'::jsonb;

ALTER TABLE research_retrieval_audits
    ALTER COLUMN filters_json DROP DEFAULT,
    ALTER COLUMN filters_json TYPE JSONB USING filters_json::jsonb,
    ALTER COLUMN filters_json SET DEFAULT '{}'::jsonb,
    ALTER COLUMN provider_versions_json DROP DEFAULT,
    ALTER COLUMN provider_versions_json TYPE JSONB USING provider_versions_json::jsonb,
    ALTER COLUMN provider_versions_json SET DEFAULT '{}'::jsonb,
    ALTER COLUMN dense_candidates_json DROP DEFAULT,
    ALTER COLUMN dense_candidates_json TYPE JSONB USING dense_candidates_json::jsonb,
    ALTER COLUMN dense_candidates_json SET DEFAULT '[]'::jsonb,
    ALTER COLUMN bm25_candidates_json DROP DEFAULT,
    ALTER COLUMN bm25_candidates_json TYPE JSONB USING bm25_candidates_json::jsonb,
    ALTER COLUMN bm25_candidates_json SET DEFAULT '[]'::jsonb,
    ALTER COLUMN fused_candidates_json DROP DEFAULT,
    ALTER COLUMN fused_candidates_json TYPE JSONB USING fused_candidates_json::jsonb,
    ALTER COLUMN fused_candidates_json SET DEFAULT '[]'::jsonb,
    ALTER COLUMN reranked_candidates_json DROP DEFAULT,
    ALTER COLUMN reranked_candidates_json TYPE JSONB USING reranked_candidates_json::jsonb,
    ALTER COLUMN reranked_candidates_json SET DEFAULT '[]'::jsonb,
    ALTER COLUMN parent_expansions_json DROP DEFAULT,
    ALTER COLUMN parent_expansions_json TYPE JSONB USING parent_expansions_json::jsonb,
    ALTER COLUMN parent_expansions_json SET DEFAULT '[]'::jsonb,
    ALTER COLUMN claims_json DROP DEFAULT,
    ALTER COLUMN claims_json TYPE JSONB USING claims_json::jsonb,
    ALTER COLUMN claims_json SET DEFAULT '[]'::jsonb,
    ALTER COLUMN conflicts_json DROP DEFAULT,
    ALTER COLUMN conflicts_json TYPE JSONB USING conflicts_json::jsonb,
    ALTER COLUMN conflicts_json SET DEFAULT '[]'::jsonb,
    ALTER COLUMN returned_evidence_json DROP DEFAULT,
    ALTER COLUMN returned_evidence_json TYPE JSONB USING returned_evidence_json::jsonb,
    ALTER COLUMN returned_evidence_json SET DEFAULT '[]'::jsonb;

ALTER TABLE research_conflict_decisions
    ALTER COLUMN claim_ids_json TYPE JSONB USING claim_ids_json::jsonb;

ALTER TABLE internal_research_evidence
    ALTER COLUMN qualifiers_json DROP DEFAULT,
    ALTER COLUMN qualifiers_json TYPE JSONB USING qualifiers_json::jsonb,
    ALTER COLUMN qualifiers_json SET DEFAULT '[]'::jsonb;

ALTER TABLE internal_research_evidence_sources
    ALTER COLUMN section_path_json DROP DEFAULT,
    ALTER COLUMN section_path_json TYPE JSONB USING section_path_json::jsonb,
    ALTER COLUMN section_path_json SET DEFAULT '[]'::jsonb,
    ALTER COLUMN bounding_boxes_json DROP DEFAULT,
    ALTER COLUMN bounding_boxes_json TYPE JSONB USING bounding_boxes_json::jsonb,
    ALTER COLUMN bounding_boxes_json SET DEFAULT '[]'::jsonb;
