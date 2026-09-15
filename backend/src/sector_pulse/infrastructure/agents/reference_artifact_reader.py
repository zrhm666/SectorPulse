"""Safe metadata-only reader for persisted orchestration artifact references."""

from sector_pulse.application.orchestration.controls import ArtifactContent
from sector_pulse.domain.orchestration.models import ArtifactRef


class ReferenceArtifactReader:
    def read(self, artifact: ArtifactRef, *, max_chars: int) -> ArtifactContent:
        del max_chars
        return ArtifactContent(
            summary=f"{artifact.kind}: {artifact.reference}",
            data={
                "artifact_id": str(artifact.artifact_id),
                "kind": artifact.kind,
                "reference": artifact.reference,
            },
        )
