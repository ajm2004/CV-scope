"""Relationship-type registry.

A relationship type names an *observable* relation between two entities:
where they were, how they moved relative to each other, in which order
things happened, and what an observation resolved to. The built-in list
covers people, vehicles, places and time; more types can be registered
(``register_relation_type``, or the API for user-defined types).

What the engine must never infer from movement is who people *are* to each
other or who owns what. Types such as FRIEND, FAMILY, PARTNER, COWORKER or
OWNS are refused as rule outputs. They can only exist as ``external_only``
types, imported from an authorized registry by an administrator, never
produced by the engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RelationCategory = Literal["identity", "spatial", "movement", "place", "vehicle", "temporal", "association", "external"]


@dataclass(frozen=True)
class RelationType:
    id: str
    label: str  # verb phrase: "approached"
    inverse: str  # "was approached by"
    category: RelationCategory
    symmetric: bool = False
    description: str = ""
    # False: only built-in logic may create it (IDENTIFIED_AS from recognition results)
    inferable: bool = True
    # True: never produced by the engine; only imported from an authorized external registry
    external_only: bool = False
    builtin: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "inverse": self.inverse, "category": self.category, "symmetric": self.symmetric,
            "description": self.description, "inferable": self.inferable, "external_only": self.external_only, "builtin": self.builtin,
        }


_BUILTIN: list[RelationType] = [
    # identity resolution (from recognition results and the registry)
    RelationType("IDENTIFIED_AS", "identified as", "identity of", "identity", description="A track resolved to an enrolled identity by the face module.", inferable=False),
    RelationType("IDENTIFIED_BY_PLATE", "identified by plate", "plate of", "identity", description="A vehicle track whose plate was read.", inferable=False),
    RelationType("REGISTERED_AS", "registered as", "registration of", "identity", description="A plate that belongs to a registered vehicle.", inferable=False),
    # spatial
    RelationType("NEAR", "was near", "was near", "spatial", symmetric=True, description="Within a distance for a minimum time."),
    RelationType("APPROACHED", "approached", "was approached by", "spatial", description="Closed the distance to the other entity by its own movement."),
    RelationType("MOVED_AWAY_FROM", "moved away from", "was left by", "spatial", description="Increased the distance to the other entity by its own movement."),
    RelationType("STOPPED_NEAR", "stopped near", "had stopped near it", "spatial", description="Stood still within a distance of the other entity."),
    # movement
    RelationType("FOLLOWED", "followed", "was followed by", "movement", description="Moved along the other entity's path a few seconds behind it."),
    RelationType("TRAVELLED_WITH", "travelled with", "travelled with", "movement", symmetric=True, description="Moved together: close, same direction, both moving."),
    RelationType("ARRIVED_WITH", "arrived with", "arrived with", "movement", symmetric=True, description="Appeared or entered together with the other entity."),
    RelationType("DEPARTED_WITH", "departed with", "departed with", "movement", symmetric=True, description="Left together with the other entity."),
    # person and vehicle
    RelationType("ENTERED_VEHICLE", "entered vehicle", "was entered by", "vehicle", description="Disappeared right beside a vehicle that stayed in view."),
    RelationType("EXITED_VEHICLE", "exited vehicle", "was exited by", "vehicle", description="Appeared right beside a vehicle that was already there."),
    RelationType("ASSOCIATED_WITH", "associated with", "associated with", "association", symmetric=True, description="Observed together by a configured rule. Not ownership, not a personal relationship."),
    # places
    RelationType("ENTERED", "entered", "was entered by", "place"),
    RelationType("EXITED", "exited", "was exited by", "place"),
    RelationType("CROSSED", "crossed", "was crossed by", "place"),
    RelationType("OCCUPIED", "occupied", "was occupied by", "place", description="Present in the zone from entry to exit."),
    RelationType("REMAINED_IN", "remained in", "held", "place", description="Stayed in the zone for at least the configured time."),
    RelationType("MOVED_FROM", "moved from", "was left for another place by", "place"),
    RelationType("MOVED_TO", "moved to", "was reached from another place by", "place"),
    RelationType("USED_ROUTE", "used route", "was used by", "place"),
    RelationType("PARKED_IN", "parked in", "held parked", "place", description="A vehicle that stood still inside the zone for the configured time."),
    # across cameras (cross-camera correlation with the Location Engine)
    RelationType("SEEN_AT", "was seen at", "saw", "place", description="An identity observed by a camera (one sighting of its journey).", inferable=False),
    RelationType("MOVED_THROUGH", "moved through", "was passed by", "place", description="A place between two cameras that the location model puts on the way.", inferable=False),
    RelationType("ENTERED_SITE_AT", "entered the site at", "was the site entry of", "place", description="The first sighting of a journey, at an entry point of the location model.", inferable=False),
    RelationType("EXITED_SITE_AT", "left the site at", "was the site exit of", "place", description="The last sighting of a journey, at an entry point of the location model.", inferable=False),
    RelationType("CONTINUED_AS", "possibly continued as", "possibly continued from", "movement", description="An anonymous track that is probably the same object as a track on a connected camera (timing only, never above possible).", inferable=False),
    # time
    RelationType("PRECEDED", "preceded", "came after", "temporal", description="Happened before the other, with a gap."),
    RelationType("PRECEDED_BY", "was preceded by", "preceded", "temporal"),
    RelationType("FOLLOWED_AFTER", "followed after", "was followed after by", "temporal"),
    RelationType("FOLLOWED_WITHIN", "followed within", "was followed within the window by", "temporal", description="Happened after the other within a configured time."),
    RelationType("OVERLAPPED_WITH", "overlapped with", "overlapped with", "temporal", symmetric=True),
    RelationType("STARTED_AFTER", "started after", "started before", "temporal"),
    RelationType("ENDED_BEFORE", "ended before", "ended after", "temporal"),
]

_TYPES: dict[str, RelationType] = {t.id: t for t in _BUILTIN}

# Personal, social and ownership relations: never inferred from what a camera sees.
NON_OBSERVABLE = frozenset({
    "FRIEND", "FRIEND_OF", "FAMILY", "FAMILY_OF", "RELATIVE", "RELATIVE_OF", "PARTNER", "PARTNER_OF", "SPOUSE", "SPOUSE_OF",
    "COWORKER", "COWORKER_OF", "COLLEAGUE", "COLLEAGUE_OF", "OWNS", "OWNER", "OWNER_OF", "OWNED_BY", "EMPLOYER", "EMPLOYEE_OF",
    "ACCOMPLICE", "SUSPECT", "KNOWS", "DATING", "MARRIED_TO",
})

_ID = re.compile(r"^[A-Z][A-Z0-9_]{1,59}$")


def relation_type(type_id: str) -> RelationType | None:
    return _TYPES.get(type_id)


def relation_types() -> list[RelationType]:
    return list(_TYPES.values())


def register_relation_type(t: RelationType) -> RelationType:
    """Add a type. A non-observable name is accepted only as ``external_only``."""
    if not _ID.match(t.id):
        raise ValueError("a relationship type id is 2-60 characters: capital letters, digits and _ (for example WAITED_FOR)")
    if t.id in NON_OBSERVABLE and not t.external_only:
        raise ValueError(f"{t.id} describes a personal relationship or ownership, which cannot be inferred from observation; it can only be imported from an authorized registry")
    existing = _TYPES.get(t.id)
    if existing is not None and existing.builtin:
        raise ValueError(f"{t.id} is a built-in type")
    _TYPES[t.id] = t
    return t


def unregister_relation_type(type_id: str) -> None:
    t = _TYPES.get(type_id)
    if t is not None and not t.builtin:
        del _TYPES[type_id]


def check_rule_output(type_id: str) -> RelationType:
    """The relationship a rule may create: known, inferable, observable."""
    if type_id in NON_OBSERVABLE:
        raise ValueError(f"{type_id} is not observable: rules describe what was seen (near, followed, entered...), never personal relationships or ownership")
    t = _TYPES.get(type_id)
    if t is None:
        raise ValueError(f"unknown relationship type '{type_id}' (add it under Relationship settings first)")
    if t.external_only:
        raise ValueError(f"{type_id} can only be imported from an authorized registry, not created by a rule")
    if not t.inferable:
        raise ValueError(f"{type_id} is created from recognition results only")
    return t


def load_custom_types(items: list[dict]) -> None:
    """Replace the user-defined types (stored in the settings table)."""
    for t in [t for t in _TYPES.values() if not t.builtin]:
        del _TYPES[t.id]
    for d in items or []:
        try:
            register_relation_type(RelationType(
                id=str(d["id"]), label=str(d.get("label") or d["id"].lower().replace("_", " ")), inverse=str(d.get("inverse") or ""),
                category=d.get("category") or ("external" if d.get("external_only") else "association"), symmetric=bool(d.get("symmetric", False)),
                description=str(d.get("description") or ""), inferable=not bool(d.get("external_only", False)), external_only=bool(d.get("external_only", False)),
                builtin=False,
            ))
        except (KeyError, ValueError):
            continue
