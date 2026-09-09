import pytest
from sector_pulse.domain.review.editing import DraftPatch


def test_patch_rejects_source_and_cutoff_paths():
    with pytest.raises(ValueError, match="path is not editable"):
        DraftPatch(path="sections/s1/source_ids", old_value_hash="x", value=["new"])


def test_patch_accepts_editable_section_body():
    patch = DraftPatch(path="sections/s1/body", old_value_hash="hash", value="new body")
    assert patch.path == "sections/s1/body"
