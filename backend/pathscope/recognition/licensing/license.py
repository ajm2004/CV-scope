"""Licence files, trusted issuers and module status.

A licence is a JSON document::

    {"version": 1,
     "payload": {"license_id": "...", "licensee": "Example Research Lab",
                 "issuer": "CV-Scope vendor", "issued_at": "2026-09-22",
                 "expires_at": "2027-09-22", "modules": ["face", "plate"],
                 "max_cameras": 4, "hardware_id": null, "notes": ""},
     "signature": "<hex Ed25519 signature over the canonical payload>",
     "issuer_public_key": "<hex>"}

It is only accepted when the signature verifies under a *trusted issuer key*.
Trusted keys are never hard-coded: they come from the environment variable
``PATHSCOPE_RECOGNITION_ISSUER_KEYS`` (comma-separated hex public keys) and
from ``*.pub`` files in ``<data>/recognition/issuers``. An open-source build
ships without any trusted key, so the modules stay locked; a vendor build adds
its public key at packaging time. Validation is fully offline.

Module status is one of: ``not_licensed``, ``licensed``, ``expired``,
``disabled`` (licensed but switched off by an administrator).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from pathscope.recognition import MODULES
from pathscope.recognition.licensing import ed25519

LICENSE_VERSION = 1
STATE_NOT_LICENSED = "not_licensed"
STATE_LICENSED = "licensed"
STATE_EXPIRED = "expired"
STATE_DISABLED = "disabled"

ENV_ISSUER_KEYS = "PATHSCOPE_RECOGNITION_ISSUER_KEYS"
_HEX = re.compile(r"^[0-9a-fA-F]{64}$")


class LicenseError(ValueError):
    pass


@dataclass
class LicensePayload:
    license_id: str
    licensee: str
    issuer: str
    issued_at: str  # ISO date
    expires_at: str | None  # ISO date, None = perpetual
    modules: list[str]
    max_cameras: int | None = None
    hardware_id: str | None = None
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> LicensePayload:
        try:
            payload = cls(
                license_id=str(d["license_id"]),
                licensee=str(d["licensee"]),
                issuer=str(d.get("issuer", "")),
                issued_at=str(d["issued_at"]),
                expires_at=(str(d["expires_at"]) if d.get("expires_at") else None),
                modules=[str(m) for m in d.get("modules", [])],
                max_cameras=(int(d["max_cameras"]) if d.get("max_cameras") is not None else None),
                hardware_id=(str(d["hardware_id"]) if d.get("hardware_id") else None),
                notes=str(d.get("notes", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LicenseError(f"licence payload is malformed: {exc}") from exc
        for m in payload.modules:
            if m not in MODULES:
                raise LicenseError(f"unknown module '{m}' in licence")
        _parse_date(payload.issued_at)
        if payload.expires_at:
            _parse_date(payload.expires_at)
        return payload

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")

    def expiry_date(self) -> date | None:
        return _parse_date(self.expires_at) if self.expires_at else None


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise LicenseError(f"invalid date '{text}' (use YYYY-MM-DD)") from exc


@dataclass
class LicenseVerdict:
    ok: bool
    state: str  # licensed | expired | not_licensed
    reason: str
    payload: LicensePayload | None = None
    issuer_key: str | None = None  # hex of the trusted key that verified it

    def summary(self) -> dict:
        d = {"state": self.state, "reason": self.reason, "issuer_key": self.issuer_key}
        if self.payload is not None:
            p = self.payload
            exp = p.expiry_date()
            d.update(
                {
                    "license_id": p.license_id,
                    "licensee": p.licensee,
                    "issuer": p.issuer,
                    "issued_at": p.issued_at,
                    "expires_at": p.expires_at,
                    "days_left": (exp - date.today()).days if exp else None,
                    "modules": list(p.modules),
                    "max_cameras": p.max_cameras,
                    "hardware_bound": bool(p.hardware_id),
                    "notes": p.notes,
                }
            )
        return d


@dataclass
class ModuleState:
    module: str
    state: str  # not_licensed | licensed | expired | disabled
    reason: str
    licensed: bool = False  # signature valid and module included (even when expired/disabled)
    active: bool = False  # licensed, not expired, enabled

    def to_dict(self) -> dict:
        return asdict(self)


def hardware_id() -> str:
    """A stable, non-secret fingerprint of this machine a licence may be bound to."""
    raw = f"{platform.node()}|{uuid.getnode()}|{platform.machine()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def issue_license(payload: LicensePayload, secret_key: bytes) -> dict:
    """Vendor side: sign a payload. The secret key never enters CV-Scope."""
    LicensePayload.from_dict(payload.to_dict())  # validate
    signature = ed25519.sign(secret_key, payload.canonical_bytes())
    return {
        "version": LICENSE_VERSION,
        "payload": payload.to_dict(),
        "signature": signature.hex(),
        "issuer_public_key": ed25519.public_key(secret_key).hex(),
    }


def parse_document(text_or_doc: str | bytes | dict) -> dict:
    if isinstance(text_or_doc, dict):
        return text_or_doc
    try:
        doc = json.loads(text_or_doc.decode("utf-8") if isinstance(text_or_doc, bytes) else text_or_doc)
    except (ValueError, UnicodeDecodeError) as exc:
        raise LicenseError(f"licence is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise LicenseError("licence must be a JSON object")
    return doc


def verify_document(doc: dict, trusted_keys: list[bytes], today: date | None = None, machine_id: str | None = None) -> LicenseVerdict:
    """Validate structure, signature (under a trusted key), dates and binding.
    Never raises: every problem is a verdict with a reason (fail closed)."""
    today = today or date.today()
    try:
        if int(doc.get("version", 0)) != LICENSE_VERSION:
            return LicenseVerdict(False, STATE_NOT_LICENSED, f"unsupported licence version {doc.get('version')!r}")
        payload = LicensePayload.from_dict(doc.get("payload") or {})
        sig_hex = str(doc.get("signature", ""))
        signature = bytes.fromhex(sig_hex)
    except (LicenseError, ValueError, TypeError, AttributeError) as exc:
        return LicenseVerdict(False, STATE_NOT_LICENSED, f"licence file is invalid: {exc}")
    if not trusted_keys:
        return LicenseVerdict(False, STATE_NOT_LICENSED, "no trusted issuer key is configured on this installation", payload)
    claimed = str(doc.get("issuer_public_key", "")).lower()
    candidates = [k for k in trusted_keys if not claimed or k.hex() == claimed] or []
    message = payload.canonical_bytes()
    verified_key: bytes | None = None
    for key in candidates:
        if ed25519.verify(key, message, signature):
            verified_key = key
            break
    if verified_key is None:
        return LicenseVerdict(False, STATE_NOT_LICENSED, "the licence signature does not verify under any trusted issuer key", payload)
    if payload.hardware_id and machine_id and payload.hardware_id != machine_id:
        return LicenseVerdict(False, STATE_NOT_LICENSED, "the licence is bound to a different machine", payload, verified_key.hex())
    if not payload.modules:
        return LicenseVerdict(False, STATE_NOT_LICENSED, "the licence enables no module", payload, verified_key.hex())
    exp = payload.expiry_date()
    if exp is not None and today > exp:
        return LicenseVerdict(False, STATE_EXPIRED, f"the licence expired on {payload.expires_at}", payload, verified_key.hex())
    return LicenseVerdict(True, STATE_LICENSED, "valid", payload, verified_key.hex())


class LicenseManager:
    """Reads the installed licence and the trusted issuer keys of this installation."""

    def __init__(self, data_dir: Path, env: dict | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.env = env if env is not None else os.environ
        self._cache: tuple[float, float, LicenseVerdict] | None = None  # (mtime, checked_at, verdict)

    # ------------------------------------------------------------- paths
    @property
    def recognition_dir(self) -> Path:
        return self.data_dir / "recognition"

    @property
    def license_path(self) -> Path:
        return self.recognition_dir / "license.json"

    @property
    def issuers_dir(self) -> Path:
        return self.recognition_dir / "issuers"

    # ------------------------------------------------------------- trusted keys
    def trusted_keys(self) -> list[bytes]:
        keys: list[bytes] = []
        raw = self.env.get(ENV_ISSUER_KEYS, "")
        for part in raw.split(","):
            part = part.strip()
            if _HEX.match(part):
                keys.append(bytes.fromhex(part))
        if self.issuers_dir.exists():
            for p in sorted(self.issuers_dir.glob("*.pub")):
                try:
                    text = p.read_text(encoding="utf-8").strip()
                except OSError:
                    continue
                if _HEX.match(text):
                    keys.append(bytes.fromhex(text))
        # de-duplicate, keep order
        seen: set[bytes] = set()
        out: list[bytes] = []
        for k in keys:
            if k not in seen:
                seen.add(k)
                out.append(k)
        return out

    def add_trusted_key(self, public_key_hex: str, name: str = "issuer") -> Path:
        if not _HEX.match(public_key_hex.strip()):
            raise LicenseError("a public key is 64 hex characters")
        self.issuers_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", name) or "issuer"
        path = self.issuers_dir / f"{safe}.pub"
        path.write_text(public_key_hex.strip().lower() + "\n", encoding="utf-8")
        self._cache = None
        return path

    # ------------------------------------------------------------- licence file
    def load(self) -> dict | None:
        p = self.license_path
        if not p.exists():
            return None
        try:
            return parse_document(p.read_bytes())
        except LicenseError:
            return None

    def verdict(self, today: date | None = None) -> LicenseVerdict:
        p = self.license_path
        mtime = p.stat().st_mtime if p.exists() else -1.0
        now = datetime.now(UTC).timestamp()
        if self._cache is not None and today is None:
            c_mtime, checked_at, verdict = self._cache
            if c_mtime == mtime and now - checked_at < 30.0:
                return verdict
        doc = self.load()
        if doc is None:
            verdict = LicenseVerdict(False, STATE_NOT_LICENSED, "no licence is installed" if not p.exists() else "the installed licence file cannot be read")
        else:
            verdict = verify_document(doc, self.trusted_keys(), today=today, machine_id=hardware_id())
        if today is None:
            self._cache = (mtime, now, verdict)
        return verdict

    def install(self, text_or_doc: str | bytes | dict) -> LicenseVerdict:
        """Validate, then write. An invalid licence is never written."""
        doc = parse_document(text_or_doc)
        verdict = verify_document(doc, self.trusted_keys(), machine_id=hardware_id())
        if not verdict.ok and verdict.state != STATE_EXPIRED:
            raise LicenseError(verdict.reason)
        self.recognition_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.license_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.license_path)
        self._cache = None
        return verdict

    def remove(self) -> bool:
        p = self.license_path
        self._cache = None
        if p.exists():
            p.unlink()
            return True
        return False

    # ------------------------------------------------------------- module status
    def module_state(self, module: str, enabled: bool = True, today: date | None = None) -> ModuleState:
        if module not in MODULES:
            return ModuleState(module, STATE_NOT_LICENSED, f"unknown module '{module}'")
        v = self.verdict(today)
        if v.payload is None or v.state == STATE_NOT_LICENSED:
            return ModuleState(module, STATE_NOT_LICENSED, v.reason)
        if module not in v.payload.modules:
            return ModuleState(module, STATE_NOT_LICENSED, "the installed licence does not include this module")
        if v.state == STATE_EXPIRED:
            return ModuleState(module, STATE_EXPIRED, v.reason, licensed=True)
        if not enabled:
            return ModuleState(module, STATE_DISABLED, "switched off by an administrator (Recognition settings)", licensed=True)
        return ModuleState(module, STATE_LICENSED, "valid licence", licensed=True, active=True)

    def describe(self) -> dict:
        v = self.verdict()
        return {
            "license": v.summary(),
            "license_installed": self.license_path.exists(),
            "trusted_issuers": len(self.trusted_keys()),
            "hardware_id": hardware_id(),
            "license_path": str(self.license_path),
        }


_manager: LicenseManager | None = None


def get_license_manager() -> LicenseManager:
    global _manager
    if _manager is None:
        from pathscope.config import get_settings

        settings = get_settings()
        env = dict(os.environ)
        if settings.recognition_issuer_keys:
            env[ENV_ISSUER_KEYS] = settings.recognition_issuer_keys
        _manager = LicenseManager(settings.resolved_data_dir, env=env)
    return _manager


def reset_license_manager_for_tests(data_dir: Path | None = None) -> LicenseManager:
    global _manager
    from pathscope.config import get_settings

    _manager = LicenseManager(data_dir or get_settings().resolved_data_dir)
    return _manager


@dataclass
class IssuedKeyPair:
    secret_hex: str
    public_hex: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


def generate_issuer_keypair() -> IssuedKeyPair:
    secret, public = ed25519.generate_keypair()
    return IssuedKeyPair(secret.hex(), public.hex())
