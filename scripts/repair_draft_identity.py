"""Read-only historical draft preview. Intentionally no apply operation yet."""

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from sector_pulse.application.writing.draft_repair import preview_draft_repair
from sector_pulse.application.writing.sector_identity import restore_context_names
from sector_pulse.domain.market.market import SectorUniverseSnapshot
from sector_pulse.domain.writing.article import ArticleDraft
from sector_pulse.domain.writing.attribution import AttributionContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def main() -> int:
    parser = argparse.ArgumentParser(description="只读预览草稿主体修复，不写入数据库。")
    parser.add_argument("--sqlite", type=Path, help="显式 SQLite 文件；省略则读环境变量数据库 URL")
    parser.add_argument("--run-id", required=True, type=UUID)
    parser.add_argument("--draft-id", required=True, type=UUID)
    parser.add_argument("--expected-version", required=True, type=int)
    parser.add_argument(
        "--confirmed-system-markers",
        action="store_true",
        help="仅在已确认末尾标记为旧系统追加时，用于生成清理预览",
    )
    args = parser.parse_args()
    if args.sqlite:
        uri = args.sqlite.resolve().as_uri() + "?mode=ro"
        engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
    else:
        raw_url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
        if not raw_url:
            parser.error("请指定 --sqlite 或设置 SECTOR_PULSE_DATABASE_URL；不会自动加载 .env")
        url = make_url(raw_url)
        if url.get_backend_name() != "postgresql":
            parser.error("环境变量仅支持 PostgreSQL；SQLite 请使用 --sqlite")
        engine = create_engine(url.set(drivername="postgresql+psycopg"))
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(
                "PRAGMA query_only = ON"
                if args.sqlite
                else "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            params = {"run": str(args.run_id), "draft": str(args.draft_id)}
            rows = connection.execute(
                text(
                    "SELECT version, payload_json FROM article_drafts "
                    "WHERE run_id = :run AND draft_id = :draft ORDER BY version DESC"
                ),
                params,
            ).all()
            if not rows or rows[0][0] != args.expected_version:
                raise ValueError("目标不存在或预期版本已过期；拒绝预览")
            draft = ArticleDraft.model_validate_json(rows[0][1])
            identities = tuple(
                AttributionContext.model_validate_json(row[0])
                for row in connection.execute(
                    text("SELECT payload_json FROM attribution_contexts WHERE run_id = :run"),
                    params,
                )
            )

            class ReadOnlySnapshots:
                def get(self, run_id, kind):
                    row = connection.execute(
                        text(
                            "SELECT payload_json FROM sector_snapshots "
                            "WHERE run_id = :run AND sector_kind = :kind"
                        ),
                        {"run": str(run_id), "kind": kind.value},
                    ).first()
                    return SectorUniverseSnapshot.model_validate_json(row[0]) if row else None

            identities = restore_context_names(identities, args.run_id, ReadOnlySnapshots())
            preview = preview_draft_repair(
                draft,
                identities,
                expected_version=args.expected_version,
                confirmed_system_markers=args.confirmed_system_markers,
            )
            output = {
                "mode": "dry-run",
                "run_id": str(args.run_id),
                "draft_id": str(args.draft_id),
                "base_version": draft.version,
                "proposed_version": preview.after.version if preview.after else None,
                "changes": [asdict(change) for change in preview.changes],
                "unresolved_section_ids": preview.unresolved_section_ids,
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Connection exceptions may contain credentials; never print raw exception text.
        print(
            f"预览失败（{type(exc).__name__}）；请检查数据库连接、目标 ID 和版本。", file=sys.stderr
        )
        raise SystemExit(1) from None
