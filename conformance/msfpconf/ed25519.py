# Ed25519 (pure Ed25519, RFC 8032), with the strict checks of MSFP core 0
# section 2.1 (spec/v0/core.md) on top.
#
# The arithmetic below (point_add to verify) is the reference code of
# RFC 8032, section 6, lightly adapted (Python 3 only, no exceptions for
# control flow). Code components of RFCs are licensed under the
# Simplified BSD License:
#
#   Copyright (c) 2017 IETF Trust and the persons identified as authors of
#   the code (S. Josefsson, I. Liusvaara). All rights reserved.
#
#   Redistribution and use in source and binary forms, with or without
#   modification, are permitted provided that the following conditions
#   are met:
#   - Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
#   - Redistributions in binary form must reproduce the above copyright
#     notice, this list of conditions and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   - Neither the name of Internet Society, IETF or IETF Trust, nor the
#     names of specific contributors, may be used to endorse or promote
#     products derived from this software without specific prior written
#     permission.
#
#   THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
#   "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
#   LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
#   A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
#   OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
#   SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
#   LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
#   DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
#   THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#   (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
#   OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# The strict checks (valid_point, verify_strict) are part of the
# conformance suite, under its MIT license (see LICENSE).
#
# This is test code: it is slow and not constant-time. Never use it to
# hold a key that matters.

import functools
import hashlib

p = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493


def _sha512(s):
    return hashlib.sha512(s).digest()


def _inv(x):
    return pow(x, p - 2, p)


d = -121665 * _inv(121666) % p
_SQRT_M1 = pow(2, (p - 1) // 4, p)


def point_add(P, Q):
    A, B = (P[1] - P[0]) * (Q[1] - Q[0]) % p, (P[1] + P[0]) * (Q[1] + Q[0]) % p
    C, D = 2 * P[3] * Q[3] * d % p, 2 * P[2] * Q[2] % p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F, G * H, F * G, E * H)


def point_mul(s, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = point_add(Q, P)
        P = point_add(P, P)
        s >>= 1
    return Q


def point_equal(P, Q):
    if (P[0] * Q[2] - Q[0] * P[2]) % p != 0:
        return False
    if (P[1] * Q[2] - Q[1] * P[2]) % p != 0:
        return False
    return True


IDENTITY = (0, 1, 1, 0)


def _recover_x(y, sign):
    if y >= p:
        return None
    x2 = (y * y - 1) * _inv(d * y * y + 1)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p != 0:
        x = x * _SQRT_M1 % p
    if (x * x - x2) % p != 0:
        return None
    if (x & 1) != sign:
        x = p - x
    return x


_GY = 4 * _inv(5) % p
_GX = _recover_x(_GY, 0)
G = (_GX, _GY, 1, _GX * _GY % p)


def point_compress(P):
    zinv = _inv(P[2])
    x = P[0] * zinv % p
    y = P[1] * zinv % p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def point_decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % p)


def _expand(secret):
    h = _sha512(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed):
    a, _ = _expand(seed)
    return point_compress(point_mul(a, G))


def sign(seed, msg):
    a, prefix = _expand(seed)
    A = point_compress(point_mul(a, G))
    r = int.from_bytes(_sha512(prefix + msg), "little") % L
    R = point_compress(point_mul(r, G))
    h = int.from_bytes(_sha512(R + A + msg), "little") % L
    s = (r + h * a) % L
    return R + int.to_bytes(s, 32, "little")


# ---- MSFP core 0 section 2.1 ------------------------------------------------

@functools.lru_cache(maxsize=4096)
def valid_point(b):
    """A public key, or R, as section 2.1 accepts it: 32 bytes, the
    canonical encoding of a point on the curve (y below p, the sign bit 0
    when x = 0), in the prime-order subgroup and not the identity: [L]A
    is the identity and A is not. That excludes the 8 points of small
    order and every point with a small-order part."""
    if len(b) != 32:
        return False
    P = point_decompress(b)
    if P is None:
        return False
    if point_equal(P, IDENTITY):
        return False
    return point_equal(point_mul(L, P), IDENTITY)


def verify_strict(public, msg, signature):
    """Section 2.1: the key valid, R valid, S below L, then [S]B = R + [k]A."""
    if len(public) != 32 or len(signature) != 64:
        return False
    if not valid_point(public) or not valid_point(signature[:32]):
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= L:
        return False
    A = point_decompress(public)
    R = point_decompress(signature[:32])
    k = int.from_bytes(_sha512(signature[:32] + public + msg), "little") % L
    return point_equal(point_mul(s, G), point_add(R, point_mul(k, A)))
