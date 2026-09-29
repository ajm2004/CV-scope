"""Encryption at rest for biometric templates and enrollment media.

Uses only the Python standard library so the open-source core needs no extra
dependency to keep the modules locked or to inspect their status:

* keys are 32 random bytes kept in files outside the database
  (``<data>/recognition/keys`` by default, ``PATHSCOPE_RECOGNITION_KEY_DIR``
  to move them to another volume);
* ``seal`` derives an encryption key and a MAC key from the file key with
  HKDF-SHA256, produces a keystream with HMAC-SHA256 in counter mode
  (a PRF in CTR mode is a standard stream-cipher construction), and
  authenticates nonce, associated data and ciphertext with HMAC-SHA256
  (encrypt-then-MAC). ``open_sealed`` verifies the tag in constant time
  before decrypting.

The blob layout is ``b"PSR1" || nonce(16) || ciphertext || tag(32)``.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import stat
from pathlib import Path

MAGIC = b"PSR1"
NONCE_LEN = 16
TAG_LEN = 32
KEY_LEN = 32


class CryptoError(ValueError):
    pass


def hkdf_sha256(key: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, key, hashlib.sha256).digest()
    out = b""
    block = b""
    counter = 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def _subkeys(key: bytes) -> tuple[bytes, bytes]:
    if len(key) != KEY_LEN:
        raise CryptoError("key must be 32 bytes")
    material = hkdf_sha256(key, b"pathscope-recognition", b"seal-v1", 64)
    return material[:32], material[32:]


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    blocks = []
    n = (length + 31) // 32
    for i in range(n):
        blocks.append(hmac.new(enc_key, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest())
    return b"".join(blocks)[:length]


def _xor(a: bytes, b: bytes) -> bytes:
    if not a:
        return b""
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(len(a), "big")


def _tag(mac_key: bytes, nonce: bytes, aad: bytes, ciphertext: bytes) -> bytes:
    m = hmac.new(mac_key, digestmod=hashlib.sha256)
    m.update(MAGIC)
    m.update(len(aad).to_bytes(8, "big"))
    m.update(aad)
    m.update(nonce)
    m.update(ciphertext)
    return m.digest()


def seal(key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    enc_key, mac_key = _subkeys(key)
    nonce = os.urandom(NONCE_LEN)
    ciphertext = _xor(plaintext, _keystream(enc_key, nonce, len(plaintext)))
    return MAGIC + nonce + ciphertext + _tag(mac_key, nonce, aad, ciphertext)


def open_sealed(key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    enc_key, mac_key = _subkeys(key)
    if len(blob) < len(MAGIC) + NONCE_LEN + TAG_LEN or not blob.startswith(MAGIC):
        raise CryptoError("not a sealed blob")
    nonce = blob[len(MAGIC) : len(MAGIC) + NONCE_LEN]
    ciphertext = blob[len(MAGIC) + NONCE_LEN : -TAG_LEN]
    tag = blob[-TAG_LEN:]
    if not hmac.compare_digest(tag, _tag(mac_key, nonce, aad, ciphertext)):
        raise CryptoError("authentication failed (wrong key or tampered data)")
    return _xor(ciphertext, _keystream(enc_key, nonce, len(ciphertext)))


class KeyStore:
    """Named 32-byte keys in files, created on first use."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self._cache: dict[str, bytes] = {}

    def path(self, name: str) -> Path:
        return self.directory / f"{name}.key"

    def key(self, name: str) -> bytes:
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        p = self.path(name)
        if p.exists():
            raw = bytes.fromhex(p.read_text(encoding="utf-8").strip())
            if len(raw) != KEY_LEN:
                raise CryptoError(f"key file {p} is corrupt")
        else:
            self.directory.mkdir(parents=True, exist_ok=True)
            raw = os.urandom(KEY_LEN)
            tmp = p.with_suffix(".key.tmp")
            tmp.write_text(raw.hex(), encoding="utf-8")
            try:
                os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:  # pragma: no cover - permissions are best effort on Windows
                pass
            os.replace(tmp, p)
        self._cache[name] = raw
        return raw

    def exists(self, name: str) -> bool:
        return self.path(name).exists()
