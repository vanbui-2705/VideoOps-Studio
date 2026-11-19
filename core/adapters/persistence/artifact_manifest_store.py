"""PostgreSQL artifact manifest repository with relative-path persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from core.adapters.persistence.models import ArtifactRow
from core.domain.errors import DomainValidationError
from core.domain.media_models import ArtifactManifest, MediaInfo


class PostgresArtifactManifestStore:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def get(self, job_id: str, artifact_id: str) -> ArtifactManifest | None:
        with self._sessions() as session:
            row = session.scalar(
                select(ArtifactRow).where(
                    ArtifactRow.job_id == job_id,
                    ArtifactRow.artifact_id == artifact_id,
                )
            )
            return self._project(row) if row and row.uri and row.checksum else None

    def save(self, manifest: ArtifactManifest) -> ArtifactManifest:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(ArtifactRow)
                .where(
                    ArtifactRow.job_id == manifest.job_id,
                    ArtifactRow.artifact_id == manifest.artifact_id,
                )
                .with_for_update()
            )
            if row is None:
                row = ArtifactRow(
                    job_id=manifest.job_id,
                    artifact_id=manifest.artifact_id,
                    artifact_type=manifest.artifact_type,
                    content_revision=manifest.content_revision,
                    created_at=manifest.created_at,
                    byte_size=manifest.byte_size,
                    artifact_metadata={},
                )
                session.add(row)
            elif row.content_revision != manifest.content_revision:
                raise DomainValidationError("Artifact ID belongs to another revision")
            row.artifact_type = manifest.artifact_type
            row.uri = manifest.relative_path
            row.checksum = manifest.checksum
            row.byte_size = manifest.byte_size
            row.artifact_metadata = _metadata_to_dict(manifest)
            session.flush()
        return manifest

    def list_for_revision(
        self, job_id: str, content_revision: int
    ) -> tuple[ArtifactManifest, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ArtifactRow)
                .where(
                    ArtifactRow.job_id == job_id,
                    ArtifactRow.content_revision == content_revision,
                    ArtifactRow.uri.is_not(None),
                    ArtifactRow.checksum.is_not(None),
                )
                .order_by(ArtifactRow.artifact_id)
            ).all()
            return tuple(self._project(row) for row in rows)

    @staticmethod
    def _project(row: ArtifactRow) -> ArtifactManifest:
        details = row.artifact_metadata or {}
        media_data = details.get("media_info")
        media_info = MediaInfo(**media_data) if media_data else None
        return ArtifactManifest(
            artifact_id=row.artifact_id,
            job_id=row.job_id,
            artifact_type=row.artifact_type,
            relative_path=row.uri or "",
            checksum=row.checksum or "",
            byte_size=row.byte_size,
            content_revision=row.content_revision,
            created_at=row.created_at,
            media_info=media_info,
            metadata=dict(details.get("metadata", {})),
        )


def _metadata_to_dict(manifest: ArtifactManifest) -> dict:
    media = manifest.media_info
    return {
        "media_info": (
            {
                "duration_ms": media.duration_ms,
                "codec": media.codec,
                "width": media.width,
                "height": media.height,
                "format_name": media.format_name,
            }
            if media
            else None
        ),
        "metadata": manifest.metadata,
    }
