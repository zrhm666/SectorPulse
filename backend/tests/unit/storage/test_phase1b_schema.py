from sector_pulse.storage.sqlite import SQLiteDatabase


def table_names(database: SQLiteDatabase) -> set[str]:
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {str(row[0]) for row in rows}


def test_phase1b_schema_has_all_tables(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "phase1b.db")
    database.initialize()
    assert {
        "attribution_contexts",
        "attribution_gate_results",
        "sector_analysis_cards",
        "claims",
        "article_outlines",
        "article_drafts",
        "article_sections",
        "article_sources",
        "review_reports",
        "review_issues",
        "agent_invocations",
    } <= table_names(database)

