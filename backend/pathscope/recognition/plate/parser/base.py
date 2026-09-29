"""Configurable plate-format layer.

    Raw OCR -> normalise characters -> candidate generation -> region-specific
    parser -> validation

A ``PlateFormat`` is a regular expression with named groups over the
normalised text (upper-case letters and digits only), plus country / region
metadata. Candidate generation swaps visually confusable characters
(O/0, I/1, B/8, S/5, Z/2, G/6, D/0, Q/0) in at most two positions so that a
format can repair a misread where its positional character class demands it:
raw ``DXB 12S67`` becomes ``DXB12567`` for the UAE format. A plate with an
undecided character ('?') is never validated.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

CONFUSABLE: dict[str, list[str]] = {
    "O": ["0", "Q", "D"],
    "0": ["O", "D", "Q"],
    "Q": ["0", "O"],
    "D": ["0", "O"],
    "I": ["1"],
    "1": ["I"],
    "B": ["8"],
    "8": ["B"],
    "S": ["5"],
    "5": ["S"],
    "Z": ["2"],
    "2": ["Z"],
    "G": ["6"],
    "6": ["G"],
}

_KEEP = re.compile(r"[^A-Z0-9?]")


def normalize_text(raw: str) -> str:
    return _KEEP.sub("", (raw or "").upper())


def candidates(text: str, max_substitutions: int = 2, limit: int = 200):
    """Yield (candidate, substitutions) with the original first, then single,
    then double substitutions of confusable characters."""
    yield text, 0
    positions = [i for i, ch in enumerate(text) if ch in CONFUSABLE]
    count = 0
    for n in range(1, max_substitutions + 1):
        for combo in itertools.combinations(positions, n):
            options = [CONFUSABLE[text[i]] for i in combo]
            for choice in itertools.product(*options):
                chars = list(text)
                for i, c in zip(combo, choice, strict=False):
                    chars[i] = c
                count += 1
                if count > limit:
                    return
                yield "".join(chars), n


@dataclass
class PlateFormat:
    id: str
    name: str
    country: str = ""  # ISO 3166-1 alpha-2 where applicable
    pattern: str = r"^(?P<number>[A-Z0-9]{2,10})$"
    region: str | None = None  # fixed region for this format (state, emirate) when not parsed
    description: str = ""
    builtin: bool = False
    _compiled: re.Pattern | None = field(default=None, repr=False, compare=False)

    def compiled(self) -> re.Pattern:
        if self._compiled is None:
            self._compiled = re.compile(self.pattern)
        return self._compiled

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "country": self.country, "pattern": self.pattern, "region": self.region, "description": self.description, "builtin": self.builtin}

    @classmethod
    def from_dict(cls, d: dict, builtin: bool = False) -> PlateFormat:
        fmt = cls(
            id=str(d["id"]), name=str(d.get("name", d["id"])), country=str(d.get("country", "")), pattern=str(d.get("pattern", cls.pattern)),
            region=(str(d["region"]) if d.get("region") else None), description=str(d.get("description", "")), builtin=builtin,
        )
        fmt.compiled()  # validate the regex early
        return fmt


@dataclass
class ParsedPlate:
    raw: str
    normalized: str
    valid: bool
    format_id: str | None = None
    format_name: str | None = None
    country: str | None = None
    region: str | None = None
    fields: dict = field(default_factory=dict)
    substitutions: int = 0

    def to_dict(self) -> dict:
        return {
            "raw": self.raw, "normalized": self.normalized, "valid": self.valid, "format": self.format_id, "format_name": self.format_name,
            "country": self.country, "region": self.region, "fields": dict(self.fields), "substitutions": self.substitutions,
        }


class PlateParser:
    def __init__(self, formats: list[PlateFormat], default_region: str = "", max_substitutions: int = 2) -> None:
        self.formats = list(formats)
        self.default_region = default_region or ""
        self.max_substitutions = max_substitutions

    def parse(self, raw: str, region_hint: str | None = None, max_substitutions: int | None = None) -> ParsedPlate:
        """Formats are tried in the configured order; for each, the text as
        read first, then confusable substitutions. Enable only the formats of
        the site and keep ``generic`` last: an earlier format may otherwise
        repair a plate that another format would have accepted as read."""
        base = normalize_text(raw)
        if not base or "?" in base:
            return ParsedPlate(raw, base, False)
        max_subs = self.max_substitutions if max_substitutions is None else max_substitutions
        for fmt in self.formats:
            rx = fmt.compiled()
            for cand, nsub in candidates(base, max_subs):
                m = rx.fullmatch(cand)
                if m is None:
                    continue
                fields = {k: v for k, v in m.groupdict().items() if v is not None}
                region = fields.get("region") or fields.get("emirate") or fields.get("state") or fmt.region or (region_hint or None) or (self.default_region or None)
                return ParsedPlate(raw, cand, True, fmt.id, fmt.name, fmt.country or None, region, fields, nsub)
        return ParsedPlate(raw, base, False)

    def parse_exact(self, raw: str, region_hint: str | None = None) -> ParsedPlate:
        """Like ``parse`` but without confusable substitutions."""
        return self.parse(raw, region_hint, max_substitutions=0)

    def describe(self) -> dict:
        return {"formats": [f.id for f in self.formats], "default_region": self.default_region}
