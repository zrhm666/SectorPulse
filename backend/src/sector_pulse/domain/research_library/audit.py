"""资料库治理动作的审计记录（规格 16.3）。

这张表要活过它记录的那份文档。软删除之后原件仍在保留期里，物理清理之后连块都被删掉了，
而"谁在什么时候把这份资料删了"必须仍然答得上来——因此审计行**不引用** `research_documents`，
也不随它级联消失。

`detail` 是这套结构里唯一有自由度的地方，因此它有一条硬约束：**不能是正文的安放处**。
正文是多行的、无界的；审计里的一行是单行的、有长度上限的描述。这条约束写成校验器而不是
写在文档里，是因为把正文塞进 detail 的人不会去读文档，但会撞上校验器。
"""

from enum import StrEnum
from uuid import uuid4

from pydantic import AwareDatetime, Field, model_validator

from sector_pulse.domain.research_library.models import Record

#: 一条审计描述的长度上限。够写清"传了什么、改成了什么"，装不下一篇摘要。
DETAIL_MAX_CHARS = 500


class DocumentAuditAction(StrEnum):
    """用户动作的取值，与 `research_document_audit.action` 的 CHECK 一致。

    只登记**人做的决定**，不登记 worker 的每一次尝试：摄取任务的状态变化有
    `research_ingestion_jobs` 自己的时间线，混进这里只会把"谁改了资料库"淹没在重试里。
    `retry_ingestion` 是用户的决定，而它触发的那次 `run` 不是。
    """

    REGISTER_DOCUMENT = "register_document"
    REGISTER_VERSION = "register_version"
    SET_SOURCE_WEIGHT = "set_source_weight"
    ARCHIVE_VERSION = "archive_version"
    SOFT_DELETE = "soft_delete"
    RESTORE = "restore"
    REBUILD_INDEX = "rebuild_index"
    RETRY_INGESTION = "retry_ingestion"
    PURGE = "purge"
    #: 一次被拒绝的上传。拒绝也是发生过的事：被拒的文件留在对象存储里作为隔离证据，
    #: 而没有这一行，那次拒绝就只剩响应体里的一句话，事后无从回答"谁在什么时候试过
    #: 传什么"。
    REFUSE_UPLOAD = "refuse_upload"


class DocumentAuditEntry(Record):
    """一次治理动作的不可变记录。

    `document_version_id` 可空：注册文档、软删除、恢复都是针对整份文档的动作。
    """

    audit_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version_id: str | None = None
    action: DocumentAuditAction
    actor: str = Field(min_length=1)
    detail: str = Field(min_length=1, max_length=DETAIL_MAX_CHARS)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _detail_is_a_description_not_a_body(self) -> "DocumentAuditEntry":
        if self.detail != self.detail.strip():
            raise ValueError("an audit detail must not carry surrounding whitespace")
        if "\n" in self.detail or "\r" in self.detail:
            raise ValueError(
                "an audit detail must be a single line; a record that can hold a document "
                "body will eventually hold one"
            )
        return self

    @model_validator(mode="after")
    def _identifiers_are_not_whitespace(self) -> "DocumentAuditEntry":
        for name in ("audit_id", "document_id", "document_version_id", "actor"):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f"{name} must not be blank")
        return self


def document_audit_entry(
    *,
    document_id: str,
    action: DocumentAuditAction,
    actor: str,
    detail: str,
    created_at: AwareDatetime,
    document_version_id: str | None = None,
) -> DocumentAuditEntry:
    """造一条审计记录，ID 由这里生成。

    审计的 ID 没有语义可言（它不是内容的函数），因此用随机 ID 而不是摘要：两条一模一样的
    动作仍然是两次动作，用内容算 ID 会把第二次写成第一次的重放。
    """
    return DocumentAuditEntry(
        audit_id=f"audit_{uuid4().hex}",
        document_id=document_id,
        document_version_id=document_version_id,
        action=action,
        actor=actor,
        detail=detail,
        created_at=created_at,
    )
