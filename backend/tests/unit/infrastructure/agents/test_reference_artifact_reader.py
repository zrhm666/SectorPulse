from uuid import uuid4


def test_reference_reader_exposes_only_safe_persisted_metadata() -> None:
    from sector_pulse.domain.orchestration.models import ArtifactRef
    from sector_pulse.infrastructure.agents.reference_artifact_reader import (
        ReferenceArtifactReader,
    )

    artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=uuid4(),
        attempt=2,
        kind="candidate_proposal",
        reference="candidate-proposal:example",
    )

    content = ReferenceArtifactReader().read(artifact, max_chars=2000)

    assert content.summary == "candidate_proposal: candidate-proposal:example"
    assert content.data == {
        "artifact_id": str(artifact.artifact_id),
        "kind": "candidate_proposal",
        "reference": "candidate-proposal:example",
    }
