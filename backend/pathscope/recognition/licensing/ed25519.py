"""Ed25519 signatures (RFC 8032) in pure Python.

Licence files are signed by the issuer's private key and verified against the
issuer's public key. A pure-Python implementation keeps the open-source core
free of extra dependencies while still able to report licence status. It is
not constant-time and must not be used where the private key is exposed to
timing attacks; issuing happens offline on the vendor's machine, and
verification only handles public data. Roughly 10 ms per verification.

Twisted Edwards curve edwards25519 in extended coordinates (X:Y:Z:T) with the
complete addition law ("add-2008-hwcd-3"), which is also used for doubling.
"""

from __future__ import annotations

import hashlib
import os

P = 2**255 - 19
Q = 2**252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P
_I = pow(2, (P - 1) // 4, P)

Point = tuple[int, int, int, int]


def _inv(x: int) -> int:
    return pow(x, P - 2, P)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(D * y * y + 1) % P
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P != 0:
        x = x * _I % P
    if x % 2 != 0:
        x = P - x
    return x


_BY = 4 * _inv(5) % P
_BX = _xrecover(_BY)
B: Point = (_BX, _BY, 1, _BX * _BY % P)
IDENTITY: Point = (0, 1, 1, 0)


def _add(p: Point, q: Point) -> Point:
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = t1 * 2 * D % P * t2 % P
    d = z1 * 2 * z2 % P
    e = b - a
    f = d - c
    g = d + c
    h = b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _double(p: Point) -> Point:
    x1, y1, z1, _ = p
    a = x1 * x1 % P
    b = y1 * y1 % P
    c = 2 * z1 * z1 % P
    dd = (-a) % P
    e = ((x1 + y1) * (x1 + y1) - a - b) % P
    g = (dd + b) % P
    f = (g - c) % P
    h = (dd - b) % P
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(k: int, p: Point) -> Point:
    r = IDENTITY
    for bit in bin(k)[2:]:
        r = _double(r)
        if bit == "1":
            r = _add(r, p)
    return r


def encode_point(p: Point) -> bytes:
    x, y, z, _ = p
    zi = _inv(z)
    x = x * zi % P
    y = y * zi % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def decode_point(b: bytes) -> Point:
    if len(b) != 32:
        raise ValueError("point must be 32 bytes")
    v = int.from_bytes(b, "little")
    sign = v >> 255
    y = v & ((1 << 255) - 1)
    if y >= P:
        raise ValueError("invalid point")
    x = _xrecover(y)
    if x == 0 and sign == 1:
        raise ValueError("invalid point")
    if x & 1 != sign:
        x = P - x
    if (-x * x + y * y - 1 - D * x * x * y * y) % P != 0:
        raise ValueError("point is not on the curve")
    return (x, y, 1, x * y % P)


def _expand(secret: bytes) -> tuple[int, bytes]:
    if len(secret) != 32:
        raise ValueError("secret key must be 32 bytes")
    h = hashlib.sha512(secret).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(secret: bytes) -> bytes:
    a, _ = _expand(secret)
    return encode_point(_mul(a, B))


def generate_keypair() -> tuple[bytes, bytes]:
    """(secret 32 bytes, public 32 bytes)."""
    secret = os.urandom(32)
    return secret, public_key(secret)


def sign(secret: bytes, message: bytes) -> bytes:
    a, prefix = _expand(secret)
    pk = encode_point(_mul(a, B))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % Q
    rb = encode_point(_mul(r, B))
    k = int.from_bytes(hashlib.sha512(rb + pk + message).digest(), "little") % Q
    s = (r + k * a) % Q
    return rb + s.to_bytes(32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    if len(signature) != 64 or len(public) != 32:
        return False
    try:
        a_point = decode_point(public)
        r_point = decode_point(signature[:32])
    except ValueError:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= Q:
        return False
    k = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % Q
    left = encode_point(_mul(s, B))
    right = encode_point(_add(r_point, _mul(k, a_point)))
    return left == right
