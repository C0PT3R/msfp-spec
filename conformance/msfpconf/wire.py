"""MSFP v0 on the wire: encodings, I-JSON, signed requests and answers,
an HTTP(S) client with section 3.1's certificate checks, and a small
server that plays the suite's side of a pairing."""

import base64
import hashlib
import hmac
import http.client
import http.server
import json
import os
import re
import socket
import ssl
import struct
import threading
import time

from . import ed25519

REQUEST_LABEL = "overfin-federation-1 request"
ANSWER_LABEL = "overfin-federation-1 response"
PAIRING_LABEL = b"overfin-federation-1 pairing\n"
CODE_PREFIX = "overfin-pair-1."
MAX_INT = 2**53 - 1
FED = "/api/v1/federation/"


# ---- Encodings (section 2.1) ---------------------------------------------

_B64U = re.compile(r"[A-Za-z0-9_-]*")


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def unb64u(text, size=None):
    """Strict base64url: the URL-safe alphabet only, no padding, unused
    bits zero (re-encoding gives the same text). None when invalid."""
    if not isinstance(text, str) or not _B64U.fullmatch(text) or len(text) % 4 == 1:
        return None
    try:
        b = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        return None
    if b64u(b) != text or (size is not None and len(b) != size):
        return None
    return b


def sha256hex(b):
    return hashlib.sha256(b).hexdigest()


class NotIJSON(ValueError):
    pass


class NonInteger(float):
    """A JSON number with a fraction or an exponent."""


class NegativeZero(int):
    """The number -0, which section 2.1 doesn't allow as an integer."""


def _clean_text(s):
    for i, ch in enumerate(s):
        o = ord(ch)
        if 0xD800 <= o <= 0xDFFF:
            return False
        if 0xFDD0 <= o <= 0xFDEF or (o & 0xFFFE) == 0xFFFE:
            return False
    return True


def parse_ijson(raw):
    """A body as section 2.1 reads it (I-JSON, RFC 7493): UTF-8 without a
    byte order mark, no member twice, no surrogates or noncharacters.
    Numbers with a fraction or an exponent come back as NonInteger, -0 as
    NegativeZero; is_int() says whether a value is an integer in section
    2.1's form. Raises NotIJSON."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raise NotIJSON("a byte order mark")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise NotIJSON("invalid UTF-8")

    def pairs(ps):
        seen = set()
        for k, _ in ps:
            if k in seen:
                raise NotIJSON("member %r twice" % k)
            if not _clean_text(k):
                raise NotIJSON("a surrogate or noncharacter in a name")
            seen.add(k)
        return dict(ps)

    def integer(t):
        # Section 2.1's integer rules (not -0, within 2^53 - 1) are about
        # members whose type is integer: is_int() checks them there.
        return NegativeZero(0) if t == "-0" else int(t)

    def constant(t):
        raise NotIJSON("%s isn't JSON" % t)

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_int=integer,
                           parse_float=NonInteger, parse_constant=constant)
    except NotIJSON:
        raise
    except ValueError as e:
        raise NotIJSON("not JSON: %s" % e)

    def walk(v):
        if isinstance(v, str):
            if not _clean_text(v):
                raise NotIJSON("a surrogate or noncharacter in a string")
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(value)
    return value


def is_int(v):
    """An integer in section 2.1's form: no fraction or exponent, not -0,
    within 2^53 - 1."""
    return isinstance(v, int) and not isinstance(v, (bool, NegativeZero)) and abs(v) <= MAX_INT


def dumps(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=True).encode("ascii")


# ---- Addresses (section 5.2) ---------------------------------------------

def check_address(a):
    """None when valid, else why not."""
    if not isinstance(a, str) or len(a) > 512 or not a.isascii():
        return "not 512 bytes of ASCII"
    m = re.fullmatch(r"(https?)://([^/?#@\\]+)", a)
    if not m:
        return "not scheme://host[:port] with nothing after"
    scheme, auth = m.groups()
    host, port = auth, None
    if auth.startswith("["):
        close = auth.find("]")
        if close < 0:
            return "an unclosed ["
        host, rest = auth[: close + 1], auth[close + 1:]
        if rest:
            if not rest.startswith(":"):
                return "junk after ]"
            port = rest[1:]
        try:
            import ipaddress
            ip = ipaddress.IPv6Address(host[1:-1])
            if str(ip) != host[1:-1] or "%" in host:
                return "IPv6 not in RFC 5952 form"
        except ValueError:
            return "not an IPv6 address"
    else:
        if ":" in auth:
            host, port = auth.rsplit(":", 1)
        labels = host.split(".")
        if labels[-1].isdigit():
            if len(labels) != 4 or any(not x.isdigit() or (len(x) > 1 and x[0] == "0") or int(x) > 255 for x in labels):
                return "not an IPv4 address in its one form"
        else:
            if len(host) > 253 or any(not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", x) for x in labels):
                return "not a name in lowercase"
    if port is not None:
        if not re.fullmatch(r"[1-9][0-9]{0,4}", port) or int(port) > 65535:
            return "a port not 1 to 65535 without leading zeros"
        if port == ("443" if scheme == "https" else "80"):
            return "the scheme's default port"
    return None


def host_of(address):
    """The <host> line of a request message (section 6.2)."""
    return address.split("://", 1)[1]


# ---- Pairing codes (section 5.1) -----------------------------------------

def parse_code(text):
    """(key, secret, expiry, address) or raises ValueError, as 5.1 reads it."""
    clean = "".join(ch for ch in text if not ch.isspace())
    if not clean.startswith(CODE_PREFIX):
        raise ValueError("not the prefix overfin-pair-1.")
    rest = clean[len(CODE_PREFIX):]
    if len(rest) > 779:
        raise ValueError("over 779 characters")
    b = unb64u(rest)
    if b is None:
        raise ValueError("not base64url in its one form")
    if len(b) <= 72:
        raise ValueError("72 bytes or fewer")
    key, secret, expiry, addr = b[:32], b[32:64], struct.unpack(">Q", b[64:72])[0], b[72:]
    if not ed25519.valid_point(key):
        raise ValueError("the key breaks section 2.1")
    if expiry > MAX_INT:
        raise ValueError("an expiry above 2^53 - 1")
    try:
        address = addr.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("an address that isn't ASCII")
    why = check_address(address)
    if why:
        raise ValueError("address: " + why)
    return key, secret, expiry, address


def proof(secret, caller_key, address):
    return hmac.new(secret, PAIRING_LABEL + caller_key + b"\n" + address.encode(), hashlib.sha256).digest()


# ---- Keys and messages (sections 4 and 6) ----------------------------------

class Key:
    def __init__(self, seed=None):
        self.seed = seed if seed is not None else os.urandom(32)
        self.pub = ed25519.public_key(self.seed)
        self.text = b64u(self.pub)

    @classmethod
    def load_or_make(cls, path):
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                return cls(f.read())
        k = cls()
        if path:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(k.seed)
        return k

    def sign(self, m):
        return ed25519.sign(self.seed, m)


def fingerprint(pub):
    h = hashlib.sha256(pub).digest()[:15]
    t = base64.b32encode(h).decode()
    return "-".join(t[i:i + 4] for i in range(0, 24, 4))


def request_message(method, host, target, date, nonce, body):
    return "\n".join([REQUEST_LABEL, method, host, target, date, nonce, sha256hex(body)]).encode("ascii")


def answer_message(nonce, status, body):
    return "\n".join([ANSWER_LABEL, nonce, str(status), sha256hex(body)]).encode("ascii")


# ---- Certificates (section 3.1) ------------------------------------------

def _der(b, i):
    """(tag, start of content, end) of the DER element at i."""
    tag = b[i]
    n = b[i + 1]
    j = i + 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(b[j:j + k], "big")
        j += k
    return tag, j, j + n


def spki_pin(cert_der):
    """The pin of section 3.1: SHA-256 of the SubjectPublicKeyInfo, base64url."""
    _, c, _ = _der(cert_der, 0)          # Certificate
    _, t, t_end = _der(cert_der, c)      # tbsCertificate
    i = t
    if cert_der[i] == 0xA0:              # [0] version
        i = _der(cert_der, i)[2]
    for _ in range(5):                   # serial, signature, issuer, validity, subject
        i = _der(cert_der, i)[2]
    _, s, e = _der(cert_der, i)          # subjectPublicKeyInfo
    return b64u(hashlib.sha256(cert_der[i:e]).digest())


class CertificateRefused(Exception):
    pass


# ---- A call to the target --------------------------------------------------

def content_coding(headers):
    """The answer's Content-Encoding when it is other than identity, else ""."""
    codings = [v.strip().lower() for k, v in headers if k.lower() == "content-encoding"]
    coded = [x for v in codings for x in (s.strip() for s in v.split(",")) if x and x != "identity"]
    return ", ".join(coded)


class Answer:
    def __init__(self, status, headers, body, signed, sig_header_count, nonce, leaf_pin=None, trusted=None):
        self.status, self.headers, self.body = status, headers, body
        self.signed = signed                  # signature verified under the peer's key
        self.sig_header_count = sig_header_count
        self.nonce = nonce
        self.leaf_pin, self.trusted = leaf_pin, trusted
        self._json, self._json_error = None, None
        # A content coding other than identity: such an answer counts as
        # badly signed, whatever its signature (section 3).
        self.coding = content_coding(headers)
        if self.coding:
            self.signed = False

    @property
    def json(self):
        if self._json is None and self._json_error is None:
            try:
                self._json = parse_ijson(self.body)
            except NotIJSON as e:
                self._json_error = str(e)
        return self._json

    @property
    def json_error(self):
        _ = self.json
        return self._json_error

    def short(self):
        b = self.body[:160]
        return "%s%s %r" % (self.status, " signed" if self.signed else " unsigned", b)


def _split(hostport, default):
    if hostport.startswith("["):
        close = hostport.index("]")
        h, rest = hostport[1:close], hostport[close + 1:]
        return h, int(rest[1:]) if rest else default
    if ":" in hostport:
        h, port = hostport.rsplit(":", 1)
        return h, int(port)
    return hostport, default


class Client:
    """Signed calls to one target address, checked as sections 3.1 and 6.6
    say. `connect` overrides where to connect (host:port), for tests behind
    a different network path; the signed host stays the address's."""

    def __init__(self, key, address, peer_pub=None, connect=None, timeout=20, any_certificate=False):
        self.key, self.address, self.peer_pub = key, address, peer_pub
        self.host = host_of(address)
        self.https = address.startswith("https://")
        self.connect_to = connect
        self.timeout = timeout
        self.any_certificate = any_certificate   # a stranger has no pins to check against
        self.pins = []           # named in the target's latest signed hello
        self.log = []            # (path, request headers, body, Answer)

    def _conn(self, checked):
        host, port = _split(self.connect_to or self.host, 443 if self.https else 80)
        if not self.https:
            return http.client.HTTPConnection(host, port, timeout=self.timeout), None, None
        sni = None if _is_ip(host) else host
        # Trusted first, as for any site.
        ctx = ssl.create_default_context()
        try:
            c = http.client.HTTPSConnection(host, port, timeout=self.timeout, context=ctx)
            if sni is None:
                ctx.check_hostname = True
            c.connect()
            leaf = c.sock.getpeercert(binary_form=True)
            return c, spki_pin(leaf), True
        except ssl.SSLCertVerificationError:
            pass
        ctx = ssl._create_unverified_context()
        c = http.client.HTTPSConnection(host, port, timeout=self.timeout, context=ctx)
        c.connect()
        pin = spki_pin(c.sock.getpeercert(binary_form=True))
        if checked and not self.any_certificate and pin not in self.pins:
            c.close()
            raise CertificateRefused("the leaf %s is neither trusted nor named" % pin)
        return c, pin, False

    def raw(self, path, body, headers, method="POST", checked=None, sign_path=None):
        """Sends exactly these headers (a list of pairs) and body."""
        if checked is None:
            checked = not (path.startswith(FED + "pair") or path.startswith(FED + "hello"))
        c, pin, trusted = self._conn(checked)
        c.putrequest(method, path, skip_accept_encoding=True)
        for k, v in headers:
            c.putheader(k, v)
        c.putheader("Content-Length", str(len(body)))
        c.endheaders(body)
        r = c.getresponse()
        data = r.read()
        hdrs = r.getheaders()
        c.close()
        nonce = next((v for k, v in headers if k.lower() == "overfin-nonce"), "")
        sigs = [v for k, v in hdrs if k.lower() == "overfin-signature"]
        signed = False
        if len(sigs) == 1 and self.peer_pub is not None:
            sig = unb64u(sigs[0].strip(), 64)
            if sig is not None:
                try:
                    signed = ed25519.verify_strict(self.peer_pub, answer_message(nonce, r.status, data), sig)
                except ValueError:
                    signed = False
        a = Answer(r.status, hdrs, data, signed, len(sigs), nonce, pin, trusted)
        self.log.append((path, headers, body, a))
        return a

    def burst(self, path, body, header_sets, connections=32):
        """Sends many prepared requests over a few kept-alive connections
        (a load check): a list of Answers, or exceptions, in order."""
        import concurrent.futures
        chunks = [list(range(i, len(header_sets), connections)) for i in range(connections)]
        out = [None] * len(header_sets)

        def worker(idx):
            conn = None
            for i in idx:
                try:
                    if conn is None:
                        conn = self._conn(True)[0]
                    conn.putrequest("POST", path, skip_accept_encoding=True)
                    for k, v in header_sets[i]:
                        conn.putheader(k, v)
                    conn.putheader("Content-Length", str(len(body)))
                    conn.endheaders(body)
                    r = conn.getresponse()
                    data = r.read()
                    hdrs = r.getheaders()
                    nonce = dict(header_sets[i])["Overfin-Nonce"]
                    sigs = [v for k, v in hdrs if k.lower() == "overfin-signature"]
                    signed = False
                    if len(sigs) == 1 and self.peer_pub is not None:
                        sig = unb64u(sigs[0].strip(), 64)
                        signed = sig is not None and ed25519.verify_strict(self.peer_pub, answer_message(nonce, r.status, data), sig)
                    out[i] = Answer(r.status, hdrs, data, signed, len(sigs), nonce)
                    if (r.getheader("Connection") or "").lower() == "close":
                        conn.close()
                        conn = None
                except (OSError, http.client.HTTPException) as e:
                    out[i] = e if isinstance(e, OSError) else OSError(str(e))
                    if conn is not None:
                        conn.close()
                    conn = None
            if conn is not None:
                conn.close()

        with concurrent.futures.ThreadPoolExecutor(connections) as ex:
            list(ex.map(worker, chunks))
        return out

    def headers(self, path, body, date=None, nonce=None, key=None, sign_host=None, sign_path=None, method="POST"):
        key = key or self.key
        date = str(int(time.time())) if date is None else date
        nonce = b64u(os.urandom(16)) if nonce is None else nonce
        msg = request_message(method, sign_host or self.host, sign_path or path, date, nonce, body)
        return [("Content-Type", "application/json"), ("Overfin-Key", key.text), ("Overfin-Date", date),
                ("Overfin-Nonce", nonce), ("Overfin-Signature", b64u(key.sign(msg)))]

    def call(self, name, body, **kw):
        if isinstance(body, (dict, list)):
            body = dumps(body)
        path = FED + name
        return self.raw(path, body, self.headers(path, body, **{k: v for k, v in kw.items() if k in ("date", "nonce", "key", "sign_host")}))


def _is_ip(h):
    try:
        socket.inet_pton(socket.AF_INET6 if ":" in h else socket.AF_INET, h)
        return True
    except OSError:
        return False


# ---- The suite's own server -------------------------------------------------

class PeerServer:
    """Answers the target's calls as a paired peer would: hello, libraries
    and titles, signed, from the target's key only. Every request it gets
    is checked as section 6.4 says and kept in `requests`."""

    def __init__(self, key, address, listen, target_pub=None):
        self.key, self.address = key, address
        self.host = host_of(address)
        self.target_pub = target_pub
        self.state = "theirs"                 # we used the target's code
        self.offer = []                       # libraries offered to the target
        self.pages = {}                       # after -> titles answer object
        self.requests = []                    # dicts, see _record
        self.nonces = set()
        self.lock = threading.Lock()
        self.started = time.time()
        self.ended = False
        h, port = _split(listen, 8000)
        srv = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                srv._handle(self)

            def do_GET(self):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.httpd = http.server.ThreadingHTTPServer((h, port), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()

    def _check(self, h, body):
        """Section 6.4 for a request from the target; returns a list of faults."""
        faults = []
        names = [k.lower() for k in h.headers.keys()]
        vals = {}
        for n in ("overfin-key", "overfin-date", "overfin-nonce", "overfin-signature"):
            c = names.count(n)
            if c != 1:
                faults.append("%s sent %d times (2.1)" % (n, c))
            else:
                vals[n] = h.headers.get(n).strip()
                if "," in vals[n]:
                    faults.append("%s holds a comma (2.1)" % n)
        if "?" in h.path:
            faults.append("a query in the target (6.2)")
        ct = (h.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ct != "application/json":
            faults.append("Content-Type %r (3)" % ct)
        if any(k.lower().startswith("sec-fetch-") for k in h.headers.keys()):
            faults.append("Sec-Fetch-* headers (3)")
        if (h.headers.get("Content-Encoding") or "identity").lower() != "identity":
            faults.append("a Content-Encoding on the request")
        if len(vals) == 4:
            key = unb64u(vals["overfin-key"], 32)
            if key is None:
                faults.append("Overfin-Key isn't base64url of 32 bytes (2.1)")
            elif self.target_pub is not None and key != self.target_pub:
                faults.append("Overfin-Key isn't the target's key")
            d = vals["overfin-date"]
            if not re.fullmatch(r"[1-9][0-9]*", d) or int(d) > MAX_INT:
                faults.append("Overfin-Date %r not a positive integer in its one form (2.1)" % d)
            elif abs(time.time() - int(d)) > 300:
                faults.append("Overfin-Date %s more than 5 minutes off (6.4)" % d)
            if unb64u(vals["overfin-nonce"], 16) is None:
                faults.append("Overfin-Nonce isn't base64url of 16 bytes (2.1, 6.1)")
            elif vals["overfin-nonce"] in self.nonces:
                faults.append("a nonce used twice (6.5)")
            sig = unb64u(vals["overfin-signature"], 64)
            if sig is None:
                faults.append("Overfin-Signature isn't base64url of 64 bytes (2.1)")
            elif key is not None:
                msg = request_message("POST", self.host, h.path, d, vals["overfin-nonce"], body)
                if not ed25519.verify_strict(key, msg, sig):
                    faults.append("the signature doesn't verify over this server's host %s (6.2)" % self.host)
        try:
            parse_ijson(body)
        except NotIJSON as e:
            faults.append("the body isn't I-JSON: %s (2.1)" % e)
        return faults, vals.get("overfin-nonce")

    def _handle(self, h):
        n = int(h.headers.get("Content-Length") or 0)
        body = h.rfile.read(n) if n else b""
        call = h.path.split("?")[0].rsplit("/", 1)[-1] if h.path.startswith(FED) else None
        with self.lock:
            faults, nonce = self._check(h, body)
            if nonce:
                self.nonces.add(nonce)
            rec = {"t": time.time(), "call": call, "path": h.path, "faults": faults, "body": body}
            self.requests.append(rec)
            known = (not faults) and call in ("hello", "libraries", "titles", "pair")
            if not known or call == "pair":
                self._send(h, 404, b"", None)
                return
            try:
                j = parse_ijson(body)
            except NotIJSON:
                j = None
            status, out = self._answer(call, j)
            self._send(h, status, out, nonce)

    def _answer(self, call, j):
        nf = b'{"type":"not-found","title":"Not found","status":404}\n'
        if self.ended:
            return 404, nf
        if call == "hello":
            st = j.get("state") if isinstance(j, dict) else None
            if not isinstance(st, str):
                return 404, nf
            if st == "ended":
                self.ended = True
                return 200, dumps({"state": "ended"})
            if st == "paired" and self.state == "theirs":
                self.state = "paired"
            return 200, dumps({"state": "paired" if self.state == "paired" else "waiting"})
        if self.state != "paired" or not isinstance(j, dict):
            return 404, nf
        if call == "libraries":
            return 200, dumps({"name": "MSFP conformance suite", "libraries": self.offer})
        if call == "titles":
            after = j.get("after", "")
            page = self.pages.get(after if isinstance(after, str) else "")
            if page is None:
                page = {"titles": [], "seq": self.pages.get("", {}).get("seq", 1)}
            return 200, dumps(page)
        return 404, nf

    def _send(self, h, status, body, nonce):
        h.send_response(status)
        if status == 200:
            h.send_header("Content-Type", "application/json")
        elif body:
            h.send_header("Content-Type", "application/problem+json")
        if nonce is not None:
            h.send_header("Overfin-Signature", b64u(self.key.sign(answer_message(nonce, status, body))))
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)
