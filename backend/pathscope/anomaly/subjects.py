"""Who or what took part in an anomaly, without names.

Objects inside an anomalous zone get an alias per kind ("Person A",
"Vehicle A", "Animal A"). When a licensed recognition module is active the
alias carries what it resolved to - the opaque ids and the status (enrolled
person recognized, unknown face, registered vehicle) - but never a name or a
plate number. Descriptions refer to subjects as ``[Person A]``; the user
interface replaces the placeholder with the name only for viewers holding a
recognition token, and a vision model never sees a name at all.
"""

from __future__ import annotations

import re

from pathscope.domain.scene import VEHICLE_CLASSES

ANIMAL_CLASSES = {"dog", "cat", "horse", "bird", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"}
RECOGNIZED = "recognized"
PLACEHOLDER = re.compile(r"\[((?:Person|Vehicle|Animal|Object) [A-Z]{1,2})\]")


def group_of(object_class: str) -> str:
    if object_class == "person":
        return "Person"
    if object_class in VEHICLE_CLASSES:
        return "Vehicle"
    if object_class in ANIMAL_CLASSES:
        return "Animal"
    return "Object"


def _letters(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


class SubjectBook:
    """Turns the objects of an anomaly into aliased subjects (resolver optional)."""

    def __init__(self, resolver=None) -> None:
        self.resolver = resolver  # pathscope.domain.entities.EntityResolver

    def describe(self, objects: list[dict]) -> list[dict]:
        counters: dict[str, int] = {}
        out: list[dict] = []
        for o in objects:
            group = group_of(o["object_class"])
            alias = f"{group} {_letters(counters.get(group, 0))}"
            counters[group] = counters.get(group, 0) + 1
            s = {"alias": alias, "track_id": o["track_id"], "object_class": o["object_class"], "detector_confidence": o.get("confidence")}
            if self.resolver is not None:
                try:
                    entity = self.resolver.resolve(int(o["track_id"]), o["object_class"])
                    s.update(entity.to_context())  # kind, identity_id / vehicle_id, status, confidence
                except Exception:  # noqa: BLE001 - recognition must never stop the anomaly
                    pass
            out.append(s)
        return out


def subject_phrase(s: dict, placeholder: bool = True) -> str:
    """Short anonymous phrase for one subject."""
    cls = s.get("object_class", "object")
    kind = s.get("kind")
    status = s.get("status")
    alias = f"[{s['alias']}]" if placeholder else s["alias"]
    if kind == "enrolled_person" and status == RECOGNIZED:
        return f"{alias} (recognized person)"
    if kind == "registered_vehicle" and status == RECOGNIZED:
        return f"{alias} (registered vehicle)"
    if kind == "recognized_plate":
        return f"a {cls} with an unregistered plate"
    if status == "unknown":
        return "an unknown person" if cls == "person" else f"an unknown {cls}"
    if status == "possible_match":
        return f"a {cls} (possible match, not confirmed)"
    return f"a {cls}"


def generic_names(text: str, subjects: list[dict]) -> str:
    """Replace ``[Person A]`` placeholders with anonymous words (webhooks, exports)."""
    by_alias = {s["alias"]: s for s in subjects}

    def repl(m: re.Match) -> str:
        s = by_alias.get(m.group(1))
        if s is None:
            return m.group(1)
        if s.get("kind") == "enrolled_person":
            return "a recognized person"
        if s.get("kind") == "registered_vehicle":
            return "a registered vehicle"
        return f"a {s.get('object_class', 'object')}"

    out = PLACEHOLDER.sub(repl, text or "")
    # "[Person A] (recognized person)" became "a recognized person (recognized person)"
    for phrase in ("recognized person", "registered vehicle"):
        out = out.replace(f"a {phrase} ({phrase})", f"a {phrase}")
    return out[:1].upper() + out[1:] if out.startswith("a ") else out
