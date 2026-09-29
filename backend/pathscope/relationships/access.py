"""Access control, identity visibility, audit and settings of the relationship graph.

Relationship data can reveal more than single detections (who is regularly
with whom, which vehicle a person leaves with), so the graph has its own
policy on top of CV-Scope's local-only default:

* **Viewers** are identified by a recognition access token (the licensed
  modules' role-based tokens: viewer < operator < admin). Without a token a
  browser is anonymous.
* **Identities**: recognized people, plates and registered vehicles are shown
  by name only to viewers with ``identity_role``; everybody else sees
  "Recognized person" with no key to follow, and cannot open identity history.
* **Actions** each need a role, configurable: reading the graph (default:
  anyone on this computer, like the rest of CV-Scope), exporting, exporting
  with identities, editing rules, deleting data, changing these settings.
* **Modules**: face-derived and plate-derived relationships can be switched
  off for the graph, as can external sensor observations.
* **Retention**: relationship data, identity links and the audit trail are
  deleted after configurable periods (hourly sweep).
* **Audit**: rule changes, analyses, exports, deletions, settings changes,
  registry imports and every identity-level view are recorded.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session
from pathscope.config import get_settings
from pathscope.db.models import Setting
from pathscope.relationships.models import RelationAudit

Role = Literal["none", "viewer", "operator", "admin"]
ROLE_RANK = {"none": 0, "viewer": 1, "operator": 2, "admin": 3}
SETTINGS_KEY = "relationships.settings"


class AccessSettings(BaseModel):
    graph_role: Role = Field(default="none", description="Read relationships and timelines (none = anyone who can open CV-Scope)")
    identity_role: Role = Field(default="viewer", description="See names, plates and identity-level history")
    export_role: Role = Field(default="none", description="Export anonymous relationship data")
    export_identity_role: Role = Field(default="admin", description="Export with names and plates")
    rules_role: Role = Field(default="none", description="Create and change relationship rules, run analyses")
    delete_role: Role = Field(default="none", description="Delete relationship data")
    settings_role: Role = Field(default="admin", description="Change these settings (loopback only while no recognition token exists)")


class ModuleSettings(BaseModel):
    face: bool = Field(default=True, description="Use face recognition results (IDENTIFIED_AS)")
    plate: bool = Field(default=True, description="Use plate recognition results (IDENTIFIED_BY_PLATE, REGISTERED_AS)")
    sensors: bool = Field(default=True, description="Accept observations from external sensors")


class RetentionSettings(BaseModel):
    days: int = Field(default=0, ge=0, le=36500, description="Delete relationship data older than this (0 = keep)")
    identity_days: int = Field(default=30, ge=0, le=36500, description="Delete identity links (recognized people, plates) older than this (0 = keep)")
    audit_days: int = Field(default=365, ge=0, le=36500)


class CustomType(BaseModel):
    id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,59}$")
    label: str = ""
    inverse: str = ""
    symmetric: bool = False
    description: str = ""
    # imported from an authorized external registry only; never produced by rules
    external_only: bool = False


class RelationshipSettings(BaseModel):
    access: AccessSettings = Field(default_factory=AccessSettings)
    modules: ModuleSettings = Field(default_factory=ModuleSettings)
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    custom_types: list[CustomType] = Field(default_factory=list)
    llm_summaries: bool = Field(default=False, description="Allow a language model to reword deterministic summaries (Anomaly Assistant model settings)")


def load_settings(session: Session) -> RelationshipSettings:
    row = session.get(Setting, SETTINGS_KEY)
    if row is None or not isinstance(row.value, dict):
        return RelationshipSettings()
    try:
        return RelationshipSettings.model_validate(row.value)
    except ValueError:
        return RelationshipSettings()


def save_settings(session: Session, s: RelationshipSettings) -> None:
    from pathscope.relationships.relations import load_custom_types

    row = session.get(Setting, SETTINGS_KEY)
    if row is None:
        session.add(Setting(key=SETTINGS_KEY, value=s.model_dump()))
    else:
        row.value = s.model_dump()
    session.commit()
    load_custom_types([t.model_dump() for t in s.custom_types])


def plate_salt() -> bytes:
    """Key of the plate hashes in entity keys (created once, kept outside the database)."""
    path = Path(get_settings().resolved_data_dir) / "relationships" / "plate.key"
    if path.is_file():
        data = path.read_bytes()
        if len(data) >= 16:
            return data
    path.parent.mkdir(parents=True, exist_ok=True)
    data = secrets.token_bytes(32)
    path.write_bytes(data)
    return data


# ---------------------------------------------------------------------------- viewers
@dataclass
class Viewer:
    name: str
    role: str  # none | viewer | operator | admin
    settings: RelationshipSettings
    client: str | None = None
    loopback: bool = False
    # No recognition token exists yet and the request comes from this computer:
    # the local user administers the settings (as for the rest of CV-Scope)
    local_admin: bool = False

    def has(self, role: str) -> bool:
        return ROLE_RANK.get(self.role, 0) >= ROLE_RANK.get(role, 0)

    @property
    def sees_identities(self) -> bool:
        return self.has(self.settings.access.identity_role)

    def require(self, action: str) -> None:
        need = getattr(self.settings.access, f"{action}_role")
        if not self.has(need):
            what = {"graph": "read relationship data", "export": "export relationship data", "export_identity": "export names and plates",
                    "rules": "change relationship rules", "delete": "delete relationship data", "settings": "change relationship settings",
                    "identity": "see identities"}.get(action, action)
            raise HTTPException(401 if self.role == "none" else 403, f"To {what} you need a recognition access token with the '{need}' role.")

    def to_dict(self) -> dict:
        a = self.settings.access
        can = {k: self.has(getattr(a, f"{k}_role")) for k in ("graph", "export", "export_identity", "rules", "delete", "settings")}
        can["settings"] = can["settings"] or self.local_admin
        return {"name": self.name, "role": self.role, "sees_identities": self.sees_identities, "can": can}


def viewer_dep(request: Request, session: Session = Depends(db_session)) -> Viewer:
    """Who is asking (a recognition token, or an anonymous local user) and the current policy."""
    from pathscope.recognition.common.access import (
        authenticate,
        extract_secret,
        has_any_token,
        is_loopback,
    )

    settings = load_settings(session)
    principal = authenticate(session, extract_secret(request))
    client = request.client.host if request.client else None
    loop = is_loopback(request)
    if principal is None:
        return Viewer("anonymous", "none", settings, client, loop, local_admin=loop and not has_any_token(session))
    return Viewer(principal.name, principal.role, settings, client, loop)


def graph_viewer(viewer: Viewer = Depends(viewer_dep)) -> Viewer:
    viewer.require("graph")
    return viewer


def can_change_settings(session: Session, viewer: Viewer) -> None:
    """Settings and the audit trail: the settings role, or the local user while no token exists."""
    from pathscope.recognition.common.access import has_any_token

    if not has_any_token(session):
        if not viewer.loopback:
            raise HTTPException(403, "Change relationship settings from the CV-Scope computer itself (or create a recognition access token).")
        return
    viewer.require("settings")


# ---------------------------------------------------------------------------- audit
AUDIT_ACTIONS = (
    "rule_created", "rule_versioned", "rule_archived", "rule_restored", "analysis_started", "analysis_current", "analysis_deleted",
    "export", "identity_viewed", "data_deleted", "settings_changed", "registry_import", "sensor_observation", "retention_sweep", "summary_model",
)


def audit(session: Session, viewer: Viewer | None, action: str, target_type: str | None = None, target_id: str | int | None = None, detail: dict | None = None) -> None:
    session.add(RelationAudit(
        actor=viewer.name if viewer else "system", actor_role=viewer.role if viewer else "system", action=action, target_type=target_type,
        target_id=str(target_id) if target_id is not None else None, detail=detail or {}, client=viewer.client if viewer else None,
    ))
    session.flush()


def audit_rows(session: Session, limit: int = 200, offset: int = 0) -> list[dict]:
    q = select(RelationAudit).order_by(RelationAudit.at.desc()).limit(limit).offset(offset)
    return [
        {"id": r.id, "at": r.at, "actor": r.actor, "actor_role": r.actor_role, "action": r.action, "target_type": r.target_type, "target_id": r.target_id, "detail": r.detail or {}, "client": r.client}
        for r in session.scalars(q)
    ]
