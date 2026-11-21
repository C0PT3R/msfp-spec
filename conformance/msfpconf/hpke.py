"""HPKE (RFC 9180) base mode with DHKEM(X25519, HKDF-SHA256), HKDF-SHA256
and AES-128-GCM, as groups section 5 seals the mail: in plain Python, slow
and not constant-time, for a test suite only. X25519 is RFC 7748's ladder;
AES-128 and GCM follow FIPS 197 and SP 800-38D."""

import hashlib
import hmac
import os

# ---- X25519 (RFC 7748) ----------------------------------------------------------

P = 2 ** 255 - 19
A24 = 121665


def _clamp(k):
    k = bytearray(k)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    return int.from_bytes(k, "little")


def x25519(k, u):
    k = _clamp(k)
    x1 = int.from_bytes(u, "little") & ((1 << 255) - 1)
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    for t in reversed(range(255)):
        kt = (k >> t) & 1
        swap ^= kt
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = kt
        a, b = (x2 + z2) % P, (x2 - z2) % P
        aa, bb = a * a % P, b * b % P
        e = (aa - bb) % P
        c, d = (x3 + z3) % P, (x3 - z3) % P
        da, cb = d * a % P, c * b % P
        x3 = (da + cb) ** 2 % P
        z3 = x1 * (da - cb) ** 2 % P
        x2 = aa * bb % P
        z2 = e * (aa + A24 * e) % P
    if swap:
        x2, z2 = x3, z3
    return (x2 * pow(z2, P - 2, P) % P).to_bytes(32, "little")


def x25519_public(sk):
    return x25519(sk, (9).to_bytes(32, "little"))


# ---- AES-128 (FIPS 197) ------------------------------------------------------------

def _sbox():
    s, p, q = [0] * 256, 1, 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        s[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    s[0] = 0x63
    return s


SBOX = _sbox()


def _xt(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _expand(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = [SBOX[b] for b in t[1:] + t[:1]]
            t[0] ^= rcon
            rcon = _xt(rcon)
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(11)]


def _encrypt_block(rk, block):
    s = [b ^ k for b, k in zip(block, rk[0])]
    for r in range(1, 11):
        s = [SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]       # ShiftRows (column-major state)
        if r != 10:
            m = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                t = a[0] ^ a[1] ^ a[2] ^ a[3]
                m += [a[i] ^ t ^ _xt(a[i] ^ a[(i + 1) % 4]) for i in range(4)]
            s = m
        s = [b ^ k for b, k in zip(s, rk[r])]
    return bytes(s)


# ---- GCM (SP 800-38D) --------------------------------------------------------------

def _gmul(x, y):
    r, z, v = 0xE1 << 120, 0, y
    for i in range(127, -1, -1):
        if (x >> i) & 1:
            z ^= v
        v = (v >> 1) ^ r if v & 1 else v >> 1
    return z


def _ghash(h, aad, ct):
    def blocks(b):
        b = b + b"\x00" * (-len(b) % 16)
        return [int.from_bytes(b[i:i + 16], "big") for i in range(0, len(b), 16)]
    y = 0
    for x in blocks(aad) + blocks(ct) + [(len(aad) * 8 << 64) | (len(ct) * 8)]:
        y = _gmul(y ^ x, h)
    return y


def _ctr(rk, j0, data):
    out = bytearray()
    for i in range(0, len(data), 16):
        cb = (j0 & ~0xFFFFFFFF) | ((j0 + 1 + i // 16) & 0xFFFFFFFF)
        ks = _encrypt_block(rk, cb.to_bytes(16, "big"))
        out += bytes(a ^ b for a, b in zip(data[i:i + 16], ks))
    return bytes(out)


def gcm_seal(key, nonce, aad, pt):
    rk = _expand(key)
    h = int.from_bytes(_encrypt_block(rk, b"\x00" * 16), "big")
    j0 = int.from_bytes(nonce + b"\x00\x00\x00\x01", "big")
    ct = _ctr(rk, j0, pt)
    tag = (_ghash(h, aad, ct) ^ int.from_bytes(_encrypt_block(rk, j0.to_bytes(16, "big")), "big")).to_bytes(16, "big")
    return ct + tag


def gcm_open(key, nonce, aad, data):
    if len(data) < 16:
        raise ValueError("shorter than the tag")
    ct, tag = data[:-16], data[-16:]
    rk = _expand(key)
    h = int.from_bytes(_encrypt_block(rk, b"\x00" * 16), "big")
    j0 = int.from_bytes(nonce + b"\x00\x00\x00\x01", "big")
    want = (_ghash(h, aad, ct) ^ int.from_bytes(_encrypt_block(rk, j0.to_bytes(16, "big")), "big")).to_bytes(16, "big")
    if not hmac.compare_digest(want, tag):
        raise ValueError("the tag doesn't verify")
    return _ctr(rk, j0, ct)


# ---- HPKE (RFC 9180), mode base ----------------------------------------------------

KEM, KDF, AEAD = 0x0020, 0x0001, 0x0001
KEM_ID = b"KEM" + KEM.to_bytes(2, "big")
SUITE_ID = b"HPKE" + KEM.to_bytes(2, "big") + KDF.to_bytes(2, "big") + AEAD.to_bytes(2, "big")


def _extract(salt, ikm):
    return hmac.new(salt or b"\x00" * 32, ikm, hashlib.sha256).digest()


def _expand_kdf(prk, info, n):
    out, t, i = b"", b"", 1
    while len(out) < n:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:n]


def _labeled_extract(sid, salt, label, ikm):
    return _extract(salt, b"HPKE-v1" + sid + label + ikm)


def _labeled_expand(sid, prk, label, info, n):
    return _expand_kdf(prk, n.to_bytes(2, "big") + b"HPKE-v1" + sid + label + info, n)


def _shared_secret(dh, enc, pkr):
    prk = _labeled_extract(KEM_ID, b"", b"eae_prk", dh)
    return _labeled_expand(KEM_ID, prk, b"shared_secret", enc + pkr, 32)


def _key_schedule(shared, info):
    psk_id_hash = _labeled_extract(SUITE_ID, b"", b"psk_id_hash", b"")
    info_hash = _labeled_extract(SUITE_ID, b"", b"info_hash", info)
    ctx = b"\x00" + psk_id_hash + info_hash
    secret = _labeled_extract(SUITE_ID, shared, b"secret", b"")
    return _labeled_expand(SUITE_ID, secret, b"key", ctx, 16), _labeled_expand(SUITE_ID, secret, b"base_nonce", ctx, 12)


def seal(pkr, info, aad, pt, ephemeral=None):
    """enc (32 bytes) followed by the ciphertext, as groups section 5's sealed."""
    ske = ephemeral or os.urandom(32)
    enc = x25519_public(ske)
    dh = x25519(ske, pkr)
    if dh == b"\x00" * 32:
        raise ValueError("an all-zero shared secret")
    key, nonce = _key_schedule(_shared_secret(dh, enc, pkr), info)
    return enc + gcm_seal(key, nonce, aad, pt)


def open_(skr, info, aad, sealed):
    if len(sealed) < 32 + 16:
        raise ValueError("too short")
    enc, ct = sealed[:32], sealed[32:]
    dh = x25519(skr, enc)
    if dh == b"\x00" * 32:
        raise ValueError("an all-zero shared secret")
    key, nonce = _key_schedule(_shared_secret(dh, enc, x25519_public(skr)), info)
    return gcm_open(key, nonce, aad, ct)
