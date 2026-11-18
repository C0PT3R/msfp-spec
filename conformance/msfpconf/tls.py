"""A self-signed certificate for the suite's own HTTPS server, made in
pure Python (core 1 section 3.2 recommends ECDSA P-256 or Ed25519, kept
apart from the federation key; P-256 is the one every TLS stack takes).

Test code: the ECDSA arithmetic is slow and not constant-time. The key
is made for one run and thrown away."""

import datetime
import hashlib
import hmac
import ipaddress
import os
import tempfile

# ---- P-256 (FIPS 186-4, SEC 2) --------------------------------------------

_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
      0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0] and (p[1] + q[1]) % _P == 0:
        return None
    if p == q:
        lam = (3 * p[0] * p[0] + _A) * pow(2 * p[1], -1, _P) % _P
    else:
        lam = (q[1] - p[1]) * pow(q[0] - p[0], -1, _P) % _P
    x = (lam * lam - p[0] - q[0]) % _P
    return x, (lam * (p[0] - x) - p[1]) % _P


def _mul(k, p):
    r = None
    while k:
        if k & 1:
            r = _add(r, p)
        p = _add(p, p)
        k >>= 1
    return r


def _sign(d, msg):
    """ECDSA with SHA-256; k from RFC 6979's idea (an HMAC of the key and
    the hash), so no weak random source can leak d."""
    z = int.from_bytes(hashlib.sha256(msg).digest(), "big")
    ctr = 0
    while True:
        k = int.from_bytes(hmac.new(d.to_bytes(32, "big"), msg + ctr.to_bytes(4, "big"), hashlib.sha512).digest(), "big") % _N
        ctr += 1
        if not k:
            continue
        r = _mul(k, _G)[0] % _N
        if not r:
            continue
        s = pow(k, -1, _N) * (z + r * d) % _N
        if s:
            return r, s


# ---- DER ----------------------------------------------------------------------

def _len(n):
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag, content):
    return bytes([tag]) + _len(len(content)) + content


def _seq(*xs):
    return _tlv(0x30, b"".join(xs))


def _int(v):
    b = v.to_bytes(v.bit_length() // 8 + 1, "big")
    return _tlv(0x02, b)


def _oid(text):
    parts = [int(x) for x in text.split(".")]
    out = bytes([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        enc = [p & 0x7F]
        p >>= 7
        while p:
            enc.append(0x80 | (p & 0x7F))
            p >>= 7
        out += bytes(reversed(enc))
    return _tlv(0x06, out)


def _name(cn):
    return _seq(_tlv(0x31, _seq(_oid("2.5.4.3"), _tlv(0x0C, cn.encode()))))


def _time(t):
    return _tlv(0x17, t.strftime("%y%m%d%H%M%SZ").encode())


def _bits(b):
    return _tlv(0x03, b"\x00" + b)


def _pem(label, der):
    import base64
    t = base64.b64encode(der).decode()
    return "-----BEGIN %s-----\n%s\n-----END %s-----\n" % (label, "\n".join(t[i:i + 64] for i in range(0, len(t), 64)), label)


class Certificate:
    """A self-signed P-256 certificate for `hosts` (names or IP
    addresses), valid from a day ago for `days`. `pin` is core 1 section
    3.2's: base64url of SHA-256 of the SubjectPublicKeyInfo."""

    def __init__(self, hosts, days=30):
        d = int.from_bytes(os.urandom(32), "big") % (_N - 1) + 1
        q = _mul(d, _G)
        point = b"\x04" + q[0].to_bytes(32, "big") + q[1].to_bytes(32, "big")
        alg = _seq(_oid("1.2.840.10045.2.1"), _oid("1.2.840.10045.3.1.7"))
        self.spki = _seq(alg, _bits(point))
        sans = []
        for h in hosts:
            try:
                sans.append(_tlv(0x87, ipaddress.ip_address(h).packed))
            except ValueError:
                sans.append(_tlv(0x82, h.encode()))
        ext = _seq(_oid("2.5.29.17"), _tlv(0x04, _seq(*sans)))
        now = datetime.datetime.now(datetime.timezone.utc)
        sig_alg = _seq(_oid("1.2.840.10045.4.3.2"))
        name = _name("MSFP conformance suite")
        tbs = _seq(_tlv(0xA0, _int(2)), _int(int.from_bytes(os.urandom(16), "big") >> 1),
                   sig_alg, name, _seq(_time(now - datetime.timedelta(days=1)), _time(now + datetime.timedelta(days=days))),
                   name, self.spki, _tlv(0xA3, _seq(ext)))
        r, s = _sign(d, tbs)
        self.der = _seq(tbs, sig_alg, _bits(_seq(_int(r), _int(s))))
        key = _seq(_int(1), _tlv(0x04, d.to_bytes(32, "big")), _tlv(0xA0, _oid("1.2.840.10045.3.1.7")), _tlv(0xA1, _bits(point)))
        from .wire import b64u
        self.pin = b64u(hashlib.sha256(self.spki).digest())
        self.dir = tempfile.mkdtemp(prefix="msfpconf-")
        import atexit
        import shutil
        atexit.register(shutil.rmtree, self.dir, True)
        self.cert_file = os.path.join(self.dir, "cert.pem")
        self.key_file = os.path.join(self.dir, "key.pem")
        with open(self.cert_file, "w") as f:
            f.write(_pem("CERTIFICATE", self.der))
        fd = os.open(self.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(_pem("EC PRIVATE KEY", key))

    def context(self):
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(self.cert_file, self.key_file)
        return ctx


class FileCertificate(Certificate):
    """A certificate and key the user gives (PEM files)."""

    def __init__(self, cert_file, key_file):
        import base64
        import re
        from .wire import b64u, spki_of
        self.cert_file, self.key_file = cert_file, key_file
        text = open(cert_file).read()
        m = re.search(r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", text, re.S)
        if not m:
            raise ValueError("%s holds no PEM certificate" % cert_file)
        self.der = base64.b64decode("".join(m.group(1).split()))
        self.spki = spki_of(self.der)
        self.pin = b64u(hashlib.sha256(self.spki).digest())
