"""Audit trail of sensitive recognition operations.

Recorded: profile created / re-enrolled / disabled / enabled / deleted,
enrollment images added or removed, enrollment finalised, vehicles created /
updated / deleted, licence installed or removed, settings changed, exports
created, tokens created or revoked, events deleted. Viewing biometric imagery
is deliberately not logged.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from pathscope.recognition.common.access import Principal
from pathscope.recognition.registry.models import RecognitionAudit

ACTIONS = (
    "profile_created", "profile_updated", "profile_reenrolled", "profile_enabled", "profile_disabled", "profile_deleted",
    "enrollment_image_added", "enrollment_image_deleted", "enrollment_finalized",
    "vehicle_created", "vehicle_updated", "vehicle_enabled", "vehicle_disabled", "vehicle_deleted",
    "license_installed", "license_removed", "setting_changed", "export_created", "token_created", "token_revoked",
    "events_deleted", "retention_sweep",
)


def audit(session: Session, principal: Principal | None, action: str, target_type: str | None = None, target_id: str | None = None, detail: dict | None = None, client: str | None = None) -> RecognitionAudit:
    row = RecognitionAudit(
        actor=principal.name if principal else "system",
        actor_role=principal.role if principal else "system",
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail or {},
        client=client,
    )
    session.add(row)
    session.flush()
    return row
