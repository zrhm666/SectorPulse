import pytest

from backend.tests.unit.application.writing.test_revision_agent import inputs


def test_preview_replaces_generic_subject_without_changing_original():
    from sector_pulse.application.writing.draft_repair import preview_draft_repair

    draft, _, cards, _ = inputs()
    draft = draft.model_copy(
        update={
            "sections": (
                draft.sections[0].model_copy(
                    update={
                        "heading": "板块一：市场观察",
                        "body": "该行业板块上涨。引用称（已复核）。\n（已复核）（已复核）",
                    }
                ),
            )
        }
    )
    before = draft.model_dump_json()
    result = preview_draft_repair(
        draft, tuple(cards.values()), expected_version=1, confirmed_system_markers=True
    )
    assert result.after.version == 2
    assert result.after.status.value == "UNREVIEWED"
    assert result.after.sections[0].heading == "文化传媒：市场观察"
    assert result.after.sections[0].body == "文化传媒上涨。引用称（已复核）。"
    assert draft.model_dump_json() == before
    assert {d.path for d in result.changes} == {"sections/s1/heading", "sections/s1/body"}


def test_preview_does_not_guess_unmapped_name_or_unconfirmed_marker():
    from sector_pulse.application.writing.draft_repair import preview_draft_repair

    draft, _, _, _ = inputs()
    draft = draft.model_copy(
        update={
            "sections": (
                draft.sections[0].model_copy(
                    update={
                        "heading": "板块一：观察",
                        "body": "该板块上涨。（已复核）",
                    }
                ),
            )
        }
    )
    result = preview_draft_repair(draft, (), expected_version=1)
    assert result.after is None
    assert result.unresolved_section_ids == ("s1",)
    assert result.changes == ()


def test_preview_is_idempotent_and_rejects_wrong_version():
    from sector_pulse.application.writing.draft_repair import preview_draft_repair

    draft, _, cards, _ = inputs()
    assert preview_draft_repair(draft, tuple(cards.values()), expected_version=1).after is None
    with pytest.raises(ValueError, match="version"):
        preview_draft_repair(draft, tuple(cards.values()), expected_version=2)


def test_apply_requires_confirmed_preview_and_preserves_history(tmp_path):
    from sector_pulse.application.writing.draft_repair import (
        apply_draft_repair,
        preview_draft_repair,
        repair_preview_hash,
    )
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.review.draft_edit_repository import SQLiteDraftEditRepository

    repository = SQLiteDraftEditRepository(SQLiteDatabase(tmp_path / "repair.db"))
    draft, _, cards, _ = inputs()
    draft = draft.model_copy(
        update={
            "sections": (
                draft.sections[0].model_copy(
                    update={
                        "heading": "板块一：观察",
                        "body": "该板块表现分化。",
                    }
                ),
            )
        }
    )
    repository.save_draft(draft)
    preview = preview_draft_repair(draft, tuple(cards.values()), expected_version=1)
    with pytest.raises(ValueError, match="preview"):
        apply_draft_repair(preview, repository, expected_preview_hash="wrong", actor="tester")
    assert repository.latest_version(draft.draft_id).version == 1
    result = apply_draft_repair(
        preview, repository, expected_preview_hash=repair_preview_hash(preview), actor="tester"
    )
    assert result.version == 2
    assert result.status.value == "UNREVIEWED"
    assert result.sections[0].heading == "文化传媒：观察"
    assert repository.get_version(draft.draft_id, 1) == draft
    with pytest.raises(ValueError):
        apply_draft_repair(
            preview, repository, expected_preview_hash=repair_preview_hash(preview), actor="tester"
        )
    assert repository.latest_version(draft.draft_id).version == 2
