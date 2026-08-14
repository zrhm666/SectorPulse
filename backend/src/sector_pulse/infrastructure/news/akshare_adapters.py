import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sector_pulse.domain.news import NewsDocument, SourceGrade
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderError,
    ProviderManifest,
    ProviderResult,
)
from sector_pulse.infrastructure.news.akshare_client import PandasAkShareNewsClient

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _parse_shanghai(value: Any) -> datetime | None:
    if value is None or str(value).strip() == "" or str(value).lower() == "nat":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI)
    return parsed.astimezone(UTC)


def _text(row: Mapping[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip()


def _document_id(source_id: str, locator: str, title: str) -> str:
    digest = hashlib.sha256(f"{source_id}|{locator}|{title}".encode()).hexdigest()
    return f"{source_id}-{digest[:24]}"


def _content_hash(title: str, summary: str, locator: str) -> str:
    return hashlib.sha256(f"{title}\n{summary}\n{locator}".encode()).hexdigest()


def _result(
    provider_id: str,
    capability: str,
    documents: list[NewsDocument],
    collected_at: datetime,
    source_version: str,
    raw_hash: str | None,
    mapping_errors: int,
) -> ProviderResult[tuple[NewsDocument, ...]]:
    if not documents and mapping_errors:
        return ProviderResult(
            provider_id=provider_id,
            capability=capability,
            status=DataStatus.FAILED,
            collected_at=collected_at,
            raw_artifact_sha256=raw_hash,
            error=ProviderError(
                code=f"{provider_id.upper().replace('-', '_')}_MAPPING_FAILED",
                message=f"all rows failed mapping: {mapping_errors}",
                retriable=False,
            ),
        )
    if not documents:
        return ProviderResult(
            provider_id=provider_id,
            capability=capability,
            status=DataStatus.EMPTY,
            collected_at=collected_at,
            source_version=source_version,
            raw_artifact_sha256=raw_hash,
        )
    if mapping_errors:
        return ProviderResult(
            provider_id=provider_id,
            capability=capability,
            status=DataStatus.PARTIAL,
            data=tuple(documents),
            collected_at=collected_at,
            source_version=source_version,
            raw_artifact_sha256=raw_hash,
            error=ProviderError(
                code=f"{provider_id.upper().replace('-', '_')}_ROW_MAPPING_PARTIAL",
                message=f"skipped rows: {mapping_errors}",
                retriable=False,
            ),
        )
    return ProviderResult(
        provider_id=provider_id,
        capability=capability,
        status=DataStatus.SUCCESS,
        data=tuple(documents),
        collected_at=collected_at,
        source_version=source_version,
        raw_artifact_sha256=raw_hash,
    )


class _BaseAkShareNewsAdapter:
    client_method = ""

    def __init__(self, client: PandasAkShareNewsClient | None = None) -> None:
        self._client = client or PandasAkShareNewsClient()

    @staticmethod
    def _filter(document: NewsDocument, cutoff: datetime) -> bool:
        return document.use_at(cutoff).value != "EXCLUDED"


class AkShareClsAdapter(_BaseAkShareNewsAdapter):
    @property
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_id="akshare-cls-news",
            version="1.0.0",
            capabilities=frozenset({"news.global.discovery"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=True,
            supports_as_of=False,
            source_attribution="AKShare / 财联社电报",
            retention_note="Discovery metadata only; no per-item citation URL",
        )

    def map_rows(
        self, rows: Sequence[Mapping[str, Any]], cutoff: datetime, collected_at: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        documents: list[NewsDocument] = []
        errors = 0
        for row in rows:
            try:
                title = _text(row, "标题")
                summary = _text(row, "内容")
                published_at = _parse_shanghai(
                    f"{_text(row, '发布日期')} {_text(row, '发布时间')}"
                )
                locator = "urn:sector-pulse:akshare-cls:" + hashlib.sha256(
                    f"{title}|{published_at}|{summary}".encode()
                ).hexdigest()[:32]
                document = NewsDocument(
                    document_id=_document_id("cls", locator, title),
                    source_id="cls",
                    canonical_locator=locator,
                    title=title,
                    summary=summary,
                    published_at=published_at,
                    collected_at=collected_at,
                    content_hash=_content_hash(title, summary, locator),
                    source_grade=SourceGrade.DISCOVERY_ONLY,
                )
                if self._filter(document, cutoff):
                    documents.append(document)
            except Exception:
                errors += 1
        return _result(
            "akshare-cls-news",
            "news.global.discovery",
            documents,
            collected_at,
            "1.0.0",
            None,
            errors,
        )

    async def fetch_global(self, cutoff: datetime) -> ProviderResult[tuple[NewsDocument, ...]]:
        try:
            batch = await self._client.fetch_cls()
            return self.map_rows(batch.rows, cutoff, batch.collected_at)
        except Exception as exc:
            return ProviderResult(
                provider_id=self.manifest.provider_id,
                capability="news.global.discovery",
                status=DataStatus.FAILED,
                collected_at=datetime.now(UTC),
                error=ProviderError(code="CLS_FETCH_FAILED", message=str(exc), retriable=True),
            )


class AkShareEastmoneyNewsAdapter(_BaseAkShareNewsAdapter):
    @property
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_id="akshare-eastmoney-news",
            version="1.0.0",
            capabilities=frozenset({"news.keyword.search"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=True,
            supports_as_of=False,
            source_attribution="AKShare / 东方财富关键词新闻",
            retention_note="Metadata and short summary only",
        )

    def map_rows(
        self, rows: Sequence[Mapping[str, Any]], cutoff: datetime, collected_at: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        documents: list[NewsDocument] = []
        errors = 0
        for row in rows:
            try:
                title = _text(row, "新闻标题")
                summary = _text(row, "新闻内容")
                citation_url = _text(row, "新闻链接") or None
                locator = citation_url or (
                    "urn:sector-pulse:eastmoney:"
                    + hashlib.sha256(title.encode("utf-8")).hexdigest()
                )
                publisher = _text(row, "文章来源") or None
                grade = (
                    SourceGrade.REPUTABLE_MEDIA
                    if publisher in {"证券时报", "中国证券报", "上海证券报"}
                    else SourceGrade.DISCOVERY_ONLY
                )
                document = NewsDocument(
                    document_id=_document_id("eastmoney", locator, title),
                    source_id="eastmoney",
                    canonical_locator=locator,
                    citation_url=citation_url,
                    title=title,
                    publisher=publisher,
                    summary=summary,
                    published_at=_parse_shanghai(row.get("发布时间")),
                    collected_at=collected_at,
                    content_hash=_content_hash(title, summary, locator),
                    source_grade=grade,
                )
                if self._filter(document, cutoff):
                    documents.append(document)
            except Exception:
                errors += 1
        return _result(
            "akshare-eastmoney-news",
            "news.keyword.search",
            documents,
            collected_at,
            "1.0.0",
            None,
            errors,
        )

    async def search(
        self, query: str, start_at: datetime, cutoff: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        del start_at
        try:
            batch = await self._client.search_eastmoney(query)
            return self.map_rows(batch.rows, cutoff, batch.collected_at)
        except Exception as exc:
            return ProviderResult(
                provider_id=self.manifest.provider_id,
                capability="news.keyword.search",
                status=DataStatus.FAILED,
                collected_at=datetime.now(UTC),
                error=ProviderError(
                    code="EASTMONEY_NEWS_FETCH_FAILED", message=str(exc), retriable=True
                ),
            )


class AkShareCninfoAdapter(_BaseAkShareNewsAdapter):
    @property
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_id="akshare-cninfo-disclosure",
            version="1.0.0",
            capabilities=frozenset({"news.disclosure.search"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=True,
            supports_as_of=False,
            source_attribution="AKShare / 巨潮资讯",
            retention_note="Announcement metadata only",
        )

    def map_rows(
        self, rows: Sequence[Mapping[str, Any]], cutoff: datetime, collected_at: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        documents: list[NewsDocument] = []
        errors = 0
        for row in rows:
            try:
                title = _text(row, "公告标题")
                citation_url = _text(row, "公告链接") or None
                locator = citation_url or (
                    "urn:sector-pulse:cninfo:" + hashlib.sha256(title.encode("utf-8")).hexdigest()
                )
                document = NewsDocument(
                    document_id=_document_id("cninfo", locator, title),
                    source_id="cninfo",
                    canonical_locator=locator,
                    citation_url=citation_url,
                    title=title,
                    publisher="巨潮资讯",
                    published_at=_parse_shanghai(row.get("公告时间")),
                    collected_at=collected_at,
                    content_hash=_content_hash(title, "", locator),
                    source_grade=SourceGrade.PRIMARY,
                )
                if self._filter(document, cutoff):
                    documents.append(document)
            except Exception:
                errors += 1
        return _result(
            "akshare-cninfo-disclosure",
            "news.disclosure.search",
            documents,
            collected_at,
            "1.0.0",
            None,
            errors,
        )

    async def search_disclosures(
        self, stock_codes: tuple[str, ...], start_at: datetime, cutoff: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        documents: list[NewsDocument] = []
        errors = 0
        for stock_code in stock_codes:
            try:
                start_date = start_at.astimezone(_SHANGHAI).strftime("%Y%m%d")
                end_date = cutoff.astimezone(_SHANGHAI).strftime("%Y%m%d")
                batch = await self._client.search_cninfo(stock_code, start_date, end_date)
                result = self.map_rows(batch.rows, cutoff, batch.collected_at)
                documents.extend(result.data or ())
                if result.status is DataStatus.FAILED:
                    errors += 1
            except Exception:
                errors += 1
        return _result(
            "akshare-cninfo-disclosure",
            "news.disclosure.search",
            documents,
            datetime.now(UTC),
            "1.0.0",
            None,
            errors,
        )
