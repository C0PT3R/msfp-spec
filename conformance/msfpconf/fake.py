"""A minimal MSFP version 0 server, in process, for selftest.py: the suite
runs against it and must pass. It is built from spec/v0/ and from the
vectors (its keys are vectors/v0/keys.json's "a", "a2", "a3"; its
playlists, subtitles and PGS come from vectors/v0/media.json), and does
only what the suite needs. Test code: never a server for real use."""

import hashlib
import hmac
import http.client
import http.server
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.parse

from . import ed25519
from .tls import Certificate
from .wire import (VERSION, FED, H_DATE, H_KEY, H_NONCE, H_SIG, Answer, Key, NotIJSON, answer_message, b64u,
                   check_address, check_destination, check_uncallable_address, clean_name, commitment, decimal,
                   dumps, has_null, host_of, is_int, make_code, make_revocation, make_rotation,
                   parse_ijson, proof, read_pins, read_revocation, read_rotation, request_message,
                   split_hostport, spki_pin, unb64u)
from .content import video_key

HERE = os.path.dirname(os.path.abspath(__file__))
VEC = os.path.join(HERE, "..", "..", "vectors", "v0")
PARTS = {"catalog": [VERSION], "playback": [VERSION], "media": [VERSION], "video": [VERSION], "music": [VERSION]}
NEEDS = {"catalog": (), "media": (), "playback": ("catalog", "media"),
         "video": ("catalog", "playback", "media"), "music": ("catalog", "playback", "media")}
JPEG = (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xc0\x00\x11\x08\x00\x5a\x00\xa0\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01\xff\xd9")


def problem(status, typ, title, **extra):
    d = {"type": typ, "title": title, "status": status}
    d.update(extra)
    return dumps(d) + b"\n"


NF = problem(404, "not-found", "Not found")
NS = problem(404, "not-supported", "Not supported")
BAD = problem(400, "invalid-request", "Invalid request")


class Peer:
    def __init__(self, key, address, name):
        self.key, self.address, self.name = key, address, name
        self.state = "ours"
        self.was_paired = False
        self.commitment = None
        self.prev = None                # (key, until)
        self.pending = None
        self.suspended = False
        self.history = [key]
        self.inbound = True
        self.confirmed_inbound = True
        self.pins = []
        self.versions = (None, None)
        self.nonces = set()
        self.sign_key = None            # the server's key toward this peer
        self.push = None                # (old, new, nc): a rotate to send
        self.pull = None                # (old, new, nc): a rotation pulled by hello
        self.revoked = None             # a revoked Key, carried in hello answers
        self.calls = []                 # (time, bucket)


class FakeServer:
    def __init__(self, resolve, allow_http=False, faults=()):
        self.faults = set(faults)       # deliberate faults, for the self-test's second pass
        keys = json.load(open(os.path.join(VEC, "keys.json")))["keys"]
        self.media = json.load(open(os.path.join(VEC, "media.json")))
        self.key = Key(bytes.fromhex(keys["a"]["seed"]))
        self.next = [Key(bytes.fromhex(keys["a2"]["seed"])), Key(bytes.fromhex(keys["a3"]["seed"]))] + [Key() for _ in range(4)]
        self.resolve = resolve          # names the operator lets this server reach, -> IP
        self.allow_http = allow_http
        self.lock = threading.RLock()
        self.codes = {}                 # secret hash -> (secret, expiry)
        self.peers = {}                 # key bytes -> Peer
        self.forgotten = set()
        self.started = time.time() - 2
        self.seen = set()               # (key, nonce) accepted
        self.inflight = {}              # claimed key -> requests in flight (core 8.3 item 3)
        self.playbacks = {}             # id -> dict
        self.tickets = {}               # ticket -> id
        self.seq = 1
        self.log = []                   # (seq, key, "add"/"gone")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.address = "%s://server.example.org:%d" % ("http" if allow_http else "https", self.port)
        self.host = host_of(self.address)
        self.cert = None if allow_http else Certificate(["server.example.org"])
        self.libraries = [{"id": "Lq3vB9xYpW2kT7mN4rS6aC", "name": "Films", "kind": "movies"},
                          {"id": "Ze8hJ1uQ5dF0gK3lP7oV2w", "name": "Séries", "kind": "tvshows"},
                          {"id": "Mu5c0R4nH8sT2vX6yB9eQa", "name": "Music", "kind": "music"}]
        L0, L1, L2 = (x["id"] for x in self.libraries)
        self.titles = {
            "movie/tmdb/550": {"kind": "movie", "library": L0, "audio": ["en", "fr"], "subtitles": ["en", "fr"], "ids": {"imdb": "tt0137523"}},
            "movie/tmdb/603": {"kind": "movie", "library": L0, "audio": ["en"]},
            "series/tmdb/1399": {"kind": "series", "library": L1, "ids": {"tvdb": "121361"}},
            "series/tmdb/1399/s1": {"kind": "season", "library": L1},
            "series/tmdb/1399/e63056": {"kind": "episode", "library": L1, "audio": ["en"], "place": {"season": 1, "episode": 1}, "with": ["series/tmdb/1399/e63057"] if "with" not in self.faults else ["series/tmdb/1400/e1"]},
            "series/tmdb/1399/e63057": {"kind": "episode", "library": L1, "audio": ["en"], "place": {"season": 1, "episode": 2}, "with": ["series/tmdb/1399/e63056"]},
            "track/mb/0c000000-0000-4000-8000-000000000003": {"kind": "track", "library": L2, "name": "The Boxer",
                                                             "artists": ["artist/mb/0a000000-0000-4000-8000-000000000001"],
                                                             "artistNames": "Simon & Garfunkel", "durationMs": 308000},
        }
        self.changes = {k: 1 for k in self.titles}
        self.limits = {"streams": 2, "transcodes": 1, "bitrateKbps": 0}
        self.peer_rate = (200.0, 400)   # calls a second, burst
        self.httpd = self._serve()

    # ---- codes and operator actions ---------------------------------------------

    def make_code(self):
        secret = os.urandom(32)
        expiry = int(time.time()) + 86400
        with self.lock:
            self.codes[hashlib.sha256(secret).digest()] = (secret, expiry)
        return make_code(self.key.pub, secret, expiry, self.address)

    def operator(self, action):
        getattr(self, "op_" + action.replace("2", "_again") if action.endswith("2") else "op_" + action)()

    def op_accept(self, want_inbound=True):
        with self.lock:
            ps = [p for p in self.peers.values() if p.state == "ours" and p.inbound == want_inbound]
        for p in ps:
            with self.lock:
                p.state, p.was_paired = "paired", True
            if p.inbound:
                self.call(p, "hello", self.hello_body(p, "paired"))

    def op_accept_again(self):
        self.op_accept(want_inbound=False)

    def op_want(self):
        for p in list(self.peers.values()):
            if p.state != "paired" or not p.inbound:
                continue
            a = self.call(p, "libraries", {})
            libs = [x["id"] for x in a.json.get("libraries", [])] if a and a.status == 200 else []
            after = ""
            for _ in range(10):
                a = self.call(p, "titles", {"libraries": libs, "after": after})
                if not a or a.status != 200:
                    break
                nxt = a.json.get("next")
                if not isinstance(nxt, str) or not nxt or nxt <= after:
                    break
                after = nxt

    watch_seconds = 30

    def op_watch(self):
        """A viewer of the suite's film Heat: play, paused at once, reported
        paused every 10 seconds, stopped after watch_seconds."""
        for p in list(self.peers.values()):
            if p.state != "paired" or not p.inbound:
                continue
            a = self.call(p, "play", {"title": "movie/tmdb/949", "capabilities": {"containers": ["mp4"],
                                                                                    "videoCodecs": ["h264"],
                                                                                    "audioCodecs": ["aac"]}})
            if not a or a.status != 200 or not isinstance(a.json.get("id"), str):
                return
            pid = a.json["id"]
            if "quietpause" in self.faults:
                # A viewer's server that says nothing while its viewer pauses.
                time.sleep(self.watch_seconds)
            else:
                self.call(p, "progress", {"id": pid, "positionMs": 0, "paused": True})
                end = time.time() + self.watch_seconds
                while time.time() < end:
                    time.sleep(max(0, min(10, end - time.time())))
                    self.call(p, "progress", {"id": pid, "positionMs": 0, "paused": True})
            self.call(p, "stop", {"id": pid, "positionMs": -1 if "badstop" in self.faults else 0})
            return

    def op_confirm(self):
        with self.lock:
            for p in self.peers.values():
                if p.pending:
                    p.pending = ("confirmed", p.pending[1] if isinstance(p.pending, tuple) else p.pending)

    def op_change(self):
        with self.lock:
            self.seq += 1
            self.titles["movie/tmdb/680"] = {"kind": "movie", "library": self.libraries[0]["id"], "audio": ["en"]}
            self.changes["movie/tmdb/680"] = self.seq
            self.titles.pop("movie/tmdb/603", None)
            self.changes["movie/tmdb/603"] = self.seq

    def _rotate_own(self):
        old, new = self.key, self.next.pop(0)
        nc = self.next[0].commitment
        self.key = new
        return old, new, nc

    def op_rotate(self):
        with self.lock:
            old, new, nc = self._rotate_own()
            todo = []
            for p in self.peers.values():
                p.sign_key = old
                if p.inbound:
                    p.push = (old, new, nc)
                    todo.append(p)
                else:
                    p.pull = (old, new, nc)
        for p in todo:
            self.push_rotation(p)

    def op_rotate_again(self):
        self.op_rotate()

    def op_revoke(self):
        """Revokes the current key and rotates to the next in one action (core 12.7 case 1)."""
        with self.lock:
            k = self.key
            old, new, nc = self._rotate_own()
            for p in self.peers.values():
                p.sign_key = old
                if p.inbound:
                    p.push = (old, new, nc)
                else:
                    p.revoked = k
                    p.pull = (old, new, nc)

    def push_rotation(self, p):
        if not p.push:
            return
        old, new, nc = p.push
        a = self.call(p, "rotate", make_rotation(old, new, nc), key=old)
        if a and a.status == 200 and a.signed:
            with self.lock:
                p.push = None
                if "oldkey" not in self.faults:
                    p.sign_key = None

    # ---- the HTTP server -----------------------------------------------------------------

    def _serve(self):
        srv = self
        ctx = self.cert.context() if self.cert else None

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = 30

            def log_message(self, *a):
                pass

            def do_POST(self):
                srv.handle_post(self)

            def do_GET(self):
                srv.handle_get(self)

            def do_HEAD(self):
                srv.handle_get(self, head=True)

            def do_PUT(self):
                srv.send(self, 405, b"")

            def do_DELETE(self):
                srv.send(self, 405, b"")

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

            def finish_request(self, request, client_address):
                request.settimeout(30)
                if ctx is not None:
                    try:
                        request = ctx.wrap_socket(request, server_side=True)
                    except (ssl.SSLError, OSError):
                        return
                self.RequestHandlerClass(request, client_address, self)

        httpd = Server(("127.0.0.1", self.port), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def send(self, h, status, body, nonce=None, key=None, ctype=None, extra=()):
        try:
            h.send_response(status)
            mt = ctype or ("application/json" if body and status in (200, 202) else "application/problem+json" if body else "-")
            if mt != "-":
                h.send_header("Content-Type", mt)
            if nonce and key:
                h.send_header(H_SIG, b64u(key.sign(answer_message(nonce, status, mt.split(";")[0], body))))
            for k, v in extra:
                h.send_header(k, v)
            h.send_header("Content-Length", str(len(body)))
            h.end_headers()
            if h.command != "HEAD":
                h.wfile.write(body)
        except OSError:
            pass

    def handle_post(self, h):
        n = int(h.headers.get("Content-Length") or 0)
        body = h.rfile.read(n) if n else b""
        path = h.path
        if not path.startswith(FED) or "/" in path[len(FED):]:
            return self.send(h, 404, b"")
        call = path[len(FED):]
        claimed = (h.headers.get("MSFP-Key") or "").strip()
        with self.lock:
            self.inflight[claimed] = self.inflight.get(claimed, 0) + 1
        try:
            self._post(h, call, body, claimed)
        finally:
            with self.lock:
                self.inflight[claimed] -= 1

    def _post(self, h, call, body, claimed):
        with self.lock:
            out = self.check(h, call, body)
            busy = self.inflight.get(claimed, 0) > 8
        if out is None:
            return self.send(h, 404, b"")
        key, nonce, peer, signed404 = out
        if signed404:
            return self.send(h, 404, NF, nonce, self.sign_key(peer))
        if peer is not None and busy:
            return self.send(h, 429, problem(429, "rate-limited", "Too many requests", retryAfter=1), nonce,
                             self.sign_key(peer), extra=[("Retry-After", "1")])
        if peer is not None and not self.rate_ok(peer):
            return self.send(h, 429, problem(429, "rate-limited", "Too many requests", retryAfter=1), nonce,
                             self.sign_key(peer), extra=[("Retry-After", "1")])
        try:
            j = parse_ijson(body)
        except NotIJSON:
            j = None
        with self.lock:
            status, out_body, sign = self.route(call, key, peer, j, h)
        if status is None:
            return self.send(h, 404, b"")
        self.send(h, status, out_body, nonce if sign else None, sign)
        if peer is not None and peer.push and call != "rotate":
            threading.Thread(target=self.push_rotation, args=(peer,), daemon=True).start()

    def sign_key(self, peer):
        if peer is not None and peer.sign_key is not None:
            return peer.sign_key
        return self.key

    def rate_ok(self, peer):
        rate, burst = self.peer_rate
        now = time.time()
        with self.lock:
            peer.calls = [t for t in peer.calls if t > now - burst / rate]
            if len(peer.calls) >= burst:
                return False
            peer.calls.append(now)
        return True

    def check(self, h, call, body):
        """Core 6.4. None: the unsigned 404. Else (key, nonce, peer, signed404)."""
        hs = [k.lower() for k in h.headers.keys()]
        vals = {}
        for name in ("msfp-key", "msfp-date", "msfp-nonce", "msfp-signature"):
            if hs.count(name) != 1:
                return None
            v = h.headers.get(name).strip(" \t")
            if "," in v or re.search(r"\s", v):
                return None
            vals[name] = v
        if "?" in h.path or len(body) > 65536:
            return None
        ct = h.headers.get_all("Content-Type") or []
        if len(ct) != 1 or ct[0].split(";")[0].strip().lower() != "application/json":
            return None
        sfs = h.headers.get("Sec-Fetch-Site")
        if sfs is not None and sfs.strip() not in ("same-origin", "none"):
            return None
        if (h.headers.get("Content-Encoding") or "identity").strip().lower() != "identity":
            return None
        key = unb64u(vals["msfp-key"], 32)
        d = decimal(vals["msfp-date"])
        if key is None or d is None or d == 0 or abs(time.time() - d) > 300 or d < int(self.started):
            return None
        nonce, sig = vals["msfp-nonce"], unb64u(vals["msfp-signature"], 64)
        if unb64u(nonce, 16) is None or sig is None or not ed25519.valid_point(key):
            return None
        if not ed25519.verify_strict(key, request_message("POST", self.host, h.path, vals["msfp-date"], nonce, body), sig):
            return None
        if (key, nonce) in self.seen and "nonce" not in self.faults:
            return None
        peer = self.peer_of(key)
        if peer is None:
            if call == "pair" and any(e > time.time() for _, e in self.codes.values()):
                self.seen.add((key, nonce))
                return key, nonce, None, False
            if hashlib.sha256(key).digest() in self.forgotten:
                return key, nonce, None, True
            return None
        self.seen.add((key, nonce))
        if peer.suspended and call not in ("rotate", "revoke"):
            return key, nonce, peer, True
        return key, nonce, peer, False

    def peer_of(self, key):
        p = self.peers.get(key)
        if p:
            return p
        for p in self.peers.values():
            if p.prev and p.prev[0] == key and p.prev[1] > time.time():
                return p
        return None

    def parts_on(self, peer):
        core, parts = peer.versions
        if not isinstance(core, list) or VERSION not in [x for x in core[:8] if is_int(x)]:
            return set()
        theirs = parts if isinstance(parts, dict) else {}
        on = set()
        for p in ("catalog", "media", "playback", "video", "music"):
            v = theirs.get(p)
            if isinstance(v, list) and VERSION in [x for x in v[:8] if is_int(x)] and all(n in on for n in NEEDS[p]):
                on.add(p)
        return on

    # ---- the calls ----------------------------------------------------------------------------

    def route(self, call, key, peer, j, h):
        sk = self.sign_key(peer)
        if call == "pair":
            return self.pair(key, peer, j)
        if peer is None:
            return None, b"", None
        if call == "hello":
            return self.hello(key, peer, j)
        if call == "rotate":
            return self.rotate(key, peer, j)
        if call == "revoke":
            if not isinstance(j, dict):
                return 400, BAD, sk
            try:
                read_revocation(key, j)
            except ValueError:
                return 400, BAD, sk
            peer.suspended = True
            return 200, dumps({"state": "suspended"}), sk
        if peer.state != "paired":
            return 404, NF, sk
        on = self.parts_on(peer)
        if call in ("libraries", "titles"):
            if "catalog" not in on:
                return 404, NS, sk
            if not isinstance(j, dict) or has_null(j):
                return 404, NF, sk
            if call == "libraries":
                out = {"name": "Fake server", "libraries": self.libraries}
                if "playback" in on:
                    out["limits"] = self.limits
                return 200, dumps(out), sk
            return self.titles_call(j, on, sk)
        if call in ("play", "progress", "stop"):
            if "playback" not in on:
                return 404, NS, sk
            if not isinstance(j, dict) or has_null(j):
                return 400, BAD, sk
            return getattr(self, call)(peer, j, on, sk)
        return None, b"", None

    def pair(self, key, peer, j):
        if not isinstance(j, dict) or has_null(j):
            return (404, NF, self.sign_key(peer)) if peer else (None, b"", None)
        addr, name, sh, pf = j.get("address"), j.get("name", ""), j.get("secretHash"), j.get("proof")
        nc, inbound = j.get("nextCommitment"), j.get("inbound", True)
        refuse = (404, NF, self.sign_key(peer)) if peer else (None, b"", None)
        if not isinstance(addr, str) or check_address(addr, self.allow_http) or not isinstance(name, str):
            return refuse
        if unb64u(sh, 32) is None or unb64u(pf, 32) is None or ("nextCommitment" in j and unb64u(nc, 32) is None):
            return refuse
        if not isinstance(inbound, bool) or (inbound is False and check_uncallable_address(addr)):
            return refuse
        code = self.codes.get(unb64u(sh, 32))
        if not code or code[1] <= time.time():
            return refuse
        if not hmac.compare_digest(proof(code[0], key, addr), unb64u(pf, 32)):
            return refuse
        if peer is not None:
            return 409, b"", self.sign_key(peer)
        del self.codes[unb64u(sh, 32)]
        self.forgotten.discard(hashlib.sha256(key).digest())
        p = Peer(key, addr, clean_name(name) or host_of(addr))
        p.commitment, p.inbound = nc, inbound
        self.peers[key] = p
        return 200, dumps({"name": "Fake server", "nextCommitment": self.next[0].commitment}), self.key

    def hello_body(self, peer, state):
        if state == "ended":
            return {"state": "ended"}
        b = {"state": state, "core": [VERSION], "parts": PARTS}
        if self.cert:
            b["certificates"] = [self.cert.pin]
        b["address"] = self.address
        return b

    def hello(self, key, peer, j):
        sk = self.sign_key(peer)
        if not isinstance(j, dict) or not isinstance(j.get("state"), str):
            return 404, NF, sk
        if "null" in self.faults:
            j = {k: v for k, v in j.items() if v is not None}
        types = {"core": list, "parts": dict, "certificates": list, "address": str, "inbound": bool, "nextCommitment": str}
        for f, t in types.items():
            if f in j and not isinstance(j[f], t):
                return 404, NF, sk
        if isinstance(j.get("parts"), dict):
            for n in PARTS:
                if n in j["parts"] and not isinstance(j["parts"][n], list):
                    return 404, NF, sk
        uncallable = j.get("inbound") is False
        if uncallable:
            for f in ("knownKey", "rotation"):
                if f in j and not isinstance(j[f], str):
                    return 404, NF, sk
            if check_uncallable_address(j.get("address", peer.address)):
                return 404, NF, sk
        st = j["state"]
        if st == "ended":
            self.peers.pop(peer.key, None)
            return 200, dumps({"state": "ended"}), sk
        if st == "paired" and (peer.state == "theirs" or (peer.state == "gone" and peer.was_paired)):
            peer.state = "paired"
        peer.versions = (j.get("core"), j.get("parts"))
        peer.pins = read_pins(j.get("certificates"))
        was = peer.inbound
        peer.inbound = j.get("inbound", True)
        addr = j.get("address")
        if not peer.inbound:
            if isinstance(addr, str):
                peer.address = addr
            peer.confirmed_inbound = False
        elif (isinstance(addr, str) and addr != peer.address) or (not was):
            threading.Thread(target=self.confirm, args=(peer, addr if isinstance(addr, str) else peer.address), daemon=True).start()
        out = self.hello_body(peer, "paired" if peer.state == "paired" else "waiting")
        if uncallable:
            known = unb64u(j.get("knownKey"), 32)
            if peer.pull and known == peer.pull[1].pub:
                peer.pull, peer.sign_key, peer.revoked = None, None, None
                sk = self.key
            elif peer.pull:
                old, new, nc = peer.pull
                out["rotation"] = make_rotation(old, new, nc)
                sk = old
            if peer.revoked is not None and sk is peer.revoked:
                out["revocation"] = make_revocation(peer.revoked)
        return 200, dumps(out), sk

    def confirm(self, peer, addr):
        """Core 13.2 step 2 (and core 7.5, inbound back to true): a hello at the new address."""
        if check_address(addr, self.allow_http):
            return
        time.sleep(0.3)
        old = peer.address
        peer.address = addr
        try:
            self.get(peer, "/.well-known/msfp")
            a = self.call(peer, "hello", self.hello_body(peer, "paired" if peer.state == "paired" else "waiting"), confirming=True)
        except OSError:
            a = None
        with self.lock:
            if a is not None and a.signed and a.status == 200:
                peer.confirmed_inbound = True
                if addr != old:
                    peer.pins = read_pins(a.json.get("certificates")) if isinstance(a.json, dict) else []
            else:
                peer.address = old

    def rotate(self, key, peer, j):
        sk = self.sign_key(peer)
        if not isinstance(j, dict):
            return 400, BAD, sk
        if key != peer.key:
            if peer.prev and key == peer.prev[0] and j.get("newKey") == b64u(peer.key):
                try:
                    read_rotation(key, j)
                    return 200, dumps({"state": "rotated"}), sk
                except ValueError:
                    return 400, BAD, sk
            return 409, problem(409, "rotation-refused", "Rotation refused"), sk
        try:
            new, nc = read_rotation(key, j)
        except ValueError:
            return 400, BAD, sk
        if new in self.peers or hashlib.sha256(new).digest() in self.forgotten:
            return 409, problem(409, "rotation-refused", "Rotation refused"), sk
        match = peer.commitment is not None and commitment(new) == peer.commitment
        if not match and (peer.suspended or peer.commitment is not None):
            return 409, problem(409, "rotation-refused", "Rotation refused"), sk
        if not match:
            if peer.pending == ("confirmed", new):
                pass
            else:
                if not (isinstance(peer.pending, bytes) and peer.pending == new):
                    peer.pending = new
                return 202, dumps({"state": "pending"}), sk
        del self.peers[peer.key]
        peer.prev = (peer.key, time.time() + 600)
        peer.key, peer.commitment, peer.pending, peer.suspended = new, nc, None, False
        peer.history.append(new)
        self.peers[new] = peer
        return 200, dumps({"state": "rotated"}), sk

    def titles_call(self, j, on, sk):
        libs, after, since = j.get("libraries"), j.get("after", ""), j.get("since", 0)
        if not isinstance(libs, list) or any(not isinstance(x, str) for x in libs):
            return 404, NF, sk
        if not isinstance(after, str) or len(after.encode()) > 512 or not is_int(since):
            return 404, NF, sk
        offered = {x["id"] for x in self.libraries}

        def shown(k, t):
            part = "video" if video_key(k) else "music"
            return part in on and t["library"] in libs and t["library"] in offered

        if 0 < since <= self.seq or ("since" in self.faults and since > self.seq):
            keys = sorted((k for k, s in self.changes.items() if s > since), key=str.encode)
            titles = [dict(self.titles[k], key=k) for k in keys if k in self.titles and shown(k, self.titles[k])]
            gone = [k for k in keys if k not in self.titles]
            return 200, dumps({"titles": [self._order(t) for t in titles], "gone": gone, "changes": True, "seq": self.seq}), sk
        keys = sorted((k for k, t in self.titles.items() if shown(k, t) and k.encode() > after.encode()), key=str.encode)
        page = keys[:5000]
        out = {"titles": [self._order(dict(self.titles[k], key=k)) for k in page], "seq": self.seq}
        if len(page) == 5000 and len(keys) > 5000:
            out["next"] = page[-1]
        return 200, dumps(out), sk

    @staticmethod
    def _order(t):
        return dict([("key", t["key"]), ("kind", t["kind"]), ("library", t["library"])] +
                    [(k, v) for k, v in t.items() if k not in ("key", "kind", "library")])

    # ---- playback -----------------------------------------------------------------------------

    def play(self, peer, j, on, sk):
        t = j.get("title")
        tag = re.compile(r"[A-Za-z0-9-]{1,12}")
        if not isinstance(t, str):
            return 400, BAD, sk
        vk = video_key(t)
        mk = re.fullmatch(r"track/mb/[0-9a-f-]{36}", t)
        if not ((vk and vk[0] in ("movie", "episode") and "video" in on) or (mk and "music" in on)):
            return 400, BAD, sk
        for f, lo, hi in (("startPositionMs", 0, 8640000000), ("maxBitrateKbps", 0, 10000000)):
            if f in j and not (is_int(j[f]) and lo <= j[f] <= hi):
                return 400, BAD, sk
        for f in ("audioLanguage", "subtitleLanguage"):
            if f in j and not (isinstance(j[f], str) and tag.fullmatch(j[f])):
                return 400, BAD, sk
        if "versionId" in j and not isinstance(j["versionId"], str):
            return 400, BAD, sk
        caps = j.get("capabilities", {})
        if not isinstance(caps, dict):
            return 400, BAD, sk
        for f in ("containers", "audioCodecs", "videoCodecs", "hdr", "subtitles"):
            if f in caps and (not isinstance(caps[f], list) or any(not isinstance(x, str) for x in caps[f])):
                return 400, BAD, sk
        if self.limits["streams"] == 0:
            return 409, problem(409, "stream-limit-reached", "Too many streams on this account"), sk
        if t not in self.titles:
            return 404, NF, sk
        if "audioTrack" in j and not (isinstance(j["audioTrack"], str) and re.fullmatch(r"a[0-9]{1,3}", j["audioTrack"])):
            return 400, BAD, sk
        if "subtitleTrack" in j and not (isinstance(j["subtitleTrack"], str) and re.fullmatch(r"s[0-9]{1,3}|off", j["subtitleTrack"])):
            return 400, BAD, sk
        versions = [{"id": "v_Kd8sQ2", "name": "1080p"}, {"id": "v_Pz4nW7", "name": "720p"}]
        vid = j.get("versionId") if j.get("versionId") in [v["id"] for v in versions] else versions[0]["id"]
        audio = [{"id": "a1", "label": "English", "language": "en", "channels": 6, "default": True},
                 {"id": "a2", "label": "Français", "language": "fr", "channels": 2}]
        at = j.get("audioTrack")
        if at not in ("a1", "a2"):
            at = next((x["id"] for x in audio if j.get("audioLanguage") and x["language"].split("-")[0] ==
                       j["audioLanguage"].lower().split("-")[0]), "a1")
        caps_all = set(caps.get("containers", [])) & {"mp4", "mkv"} and "h264" in caps.get("videoCodecs", [])
        method = "direct" if caps_all else "transcode"
        mine = [p for p in self.playbacks.values() if p["peer"] is peer and p["live"]]
        if len(mine) >= self.limits["streams"] and "limits" not in self.faults:
            return 409, problem(409, "stream-limit-reached", "Too many streams on this account"), sk
        if method == "transcode" and sum(1 for p in mine if p["method"] == "transcode") >= self.limits["transcodes"]:
            return 503, problem(503, "server-busy", "The server is busy; try again shortly"), sk
        pid = "play_" + b64u(os.urandom(20)).lower().replace("-", "a").replace("_", "b")[:26]
        pid = "play_" + "".join(ch if ch in "abcdefghijklmnopqrstuvwxyz234567" else "q" for ch in pid[5:])
        ticket = b64u(os.urandom(24))
        root = self.address + "/api/v1/stream/" + ticket + "/"
        out = {"id": pid, "method": method,
               "stream": {"url": root + ("file" if method == "direct" else "master.m3u8"),
                          "protocol": "file" if method == "direct" else "hls"},
               "positionMs": j.get("startPositionMs", 0), "durationMs": 7200000, "versions": versions, "versionId": vid,
               "audioTracks": audio, "audioTrack": at, "maxBitrateKbps": 120000}
        if vk:
            subs = [{"id": "s1", "label": "English", "language": "en", "url": root + "subtitles/s1"},
                    {"id": "s2", "label": "Français", "language": "fr", "pictures": True, "url": root + "pictures/s2"}]
            st = j.get("subtitleTrack")
            if st not in ("s1", "s2", "off"):
                st = next((x["id"] for x in subs if j.get("subtitleLanguage") and x["language"] ==
                           j["subtitleLanguage"].lower().split("-")[0]), None)
            out.update({"subtitleTracks": subs, "subtitleStretchSeconds": 120,
                        "segments": [{"kind": "intro", "startMs": 0, "endMs": 30000}],
                        "trickplay": {"tileWidth": 160, "tileHeight": 90, "columns": 10, "rows": 10, "intervalMs": 10000,
                                      "tileCount": 50, "sheets": [root + "trickplay/0"]}})
            if st and st != "off":
                out["subtitleTrack"] = st
        self.playbacks[pid] = {"peer": peer, "live": True, "method": method, "ticket": ticket}
        self.tickets[ticket] = pid
        return 200, dumps(out), sk

    def progress(self, peer, j, on, sk):
        pid = j.get("id")
        if not isinstance(pid, str) or not re.fullmatch(r"play_[a-z2-7]{26}", pid):
            return 400, BAD, sk
        if "positionMs" in j and not (is_int(j["positionMs"]) and 0 <= j["positionMs"] <= 8640000000):
            return 400, BAD, sk
        if "paused" in j and not isinstance(j["paused"], bool):
            return 400, BAD, sk
        p = self.playbacks.get(pid)
        if (not p or not p["live"] or p["peer"] is not peer) and "progress" not in self.faults:
            return 410, problem(410, "playback-stopped", "Playback was stopped"), sk
        return 200, b"{}", sk

    def stop(self, peer, j, on, sk):
        pid = j.get("id")
        if not isinstance(pid, str) or not re.fullmatch(r"play_[a-z2-7]{26}", pid):
            return 400, BAD, sk
        if "positionMs" in j and not (is_int(j["positionMs"]) and 0 <= j["positionMs"] <= 8640000000):
            return 400, BAD, sk
        p = self.playbacks.get(pid)
        if p and p["peer"] is peer:
            p["live"] = False
        return 200, b"{}", sk

    # ---- media (media 2, 3; video 6) ----------------------------------------------------------

    def handle_get(self, h, head=False):
        u = urllib.parse.urlsplit(h.path)
        if not h.path.startswith("/api/v1/stream/"):
            return self.send(h, 404, b"")
        if ((u.query or "?" in h.path) and "query" not in self.faults) or any(h.headers.get(x) for x in ("Origin", "Sec-Fetch-Site", "Sec-Fetch-Mode")):
            return self.send(h, 404, b"")
        parts = u.path[len("/api/v1/stream/"):].split("/")
        with self.lock:
            pid = self.tickets.get(parts[0])
            live = pid and self.playbacks[pid]["live"]
        if not live:
            return self.send(h, 404, b"")
        name = "/".join(parts[1:])
        vec = {c["name"]: c for c in self.media["hls"]}
        body, ctype, ranged = None, "application/octet-stream", False
        if name == "master.m3u8":
            body, ctype = vec["a master playlist"]["text"].encode(), "application/vnd.apple.mpegurl"
        elif name == "v0.m3u8":
            body, ctype = vec["a media playlist"]["text"].encode(), "application/vnd.apple.mpegurl"
        elif name in ("init.mp4", "seg0.mp4", "seg-1.mp4", "file"):
            body, ctype, ranged = (bytes(range(256)) * 40)[: 4000 if name != "file" else 10000], "video/mp4", True
        elif name == "subtitles/s1/0":
            body, ctype = self.media["webvtt"][0]["output"].encode(), "text/vtt; charset=utf-8"
            if "vtt" in self.faults:
                body = self.media["webvtt"][1]["text"].encode()
        elif name == "pictures/s2/0":
            body = bytes.fromhex(self.media["pgs"][0]["hex"])
        elif name == "trickplay/0":
            body, ctype = JPEG, "image/jpeg"
        if body is None:
            return self.send(h, 404, b"")
        rng = h.headers.get_all("Range") or []
        if ranged and rng:
            if len(rng) != 1:
                return self.send(h, 416, b"")
            r0 = rng[0].split(",")[0] if "range" in self.faults else rng[0]
            m = re.fullmatch(r"bytes=([0-9]{1,15})-([0-9]{1,15})?|bytes=-([0-9]{1,15})", r0)
            if not m:
                return self.send(h, 416, b"")
            total = len(body)
            if m.group(3) is not None:
                cnt = int(m.group(3))
                if cnt < 1:
                    return self.send(h, 416, b"")
                start, end = max(total - cnt, 0), total - 1
            else:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) is not None else total - 1
                if (m.group(2) is not None and start > end) or start >= total:
                    return self.send(h, 416, b"")
                end = min(end, total - 1)
            return self.send(h, 206, body[start:end + 1], ctype=ctype,
                             extra=[("Content-Range", "bytes %d-%d/%d" % (start, end, total))])
        self.send(h, 200, body, ctype=ctype)

    # ---- calls to a peer ----------------------------------------------------------------------

    def _connect(self, peer, checked):
        scheme, hp = peer.address.split("://", 1)
        host, port = split_hostport(hp, 443 if scheme == "https" else 80)
        name = host.strip("[]")
        ip = self.resolve.get(name)
        if ip is None:
            try:
                ip = socket.getaddrinfo(name, port)[0][4][0]
            except OSError:
                raise OSError("can't resolve %s" % name)
            if check_destination(ip) and "loopback" not in self.faults:
                raise OSError("refused destination %s (core 3.3)" % ip)
        sock = socket.create_connection((ip, port), 10)
        if scheme == "http":
            c = http.client.HTTPConnection(ip, port, timeout=10)
            c.sock = sock
            return c
        ctx = ssl._create_unverified_context()
        s = ctx.wrap_socket(sock, server_hostname=name if not re.fullmatch(r"[0-9.:]+", name) else None)
        if checked and spki_pin(s.getpeercert(binary_form=True)) not in peer.pins:
            s.close()
            raise OSError("the peer's certificate is neither trusted nor named")
        c = http.client.HTTPSConnection(ip, port, timeout=10, context=ctx)
        c.sock = s
        return c

    def get(self, peer, path):
        c = self._connect(peer, False)
        try:
            c.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
            c.putheader("Host", host_of(peer.address))
            c.endheaders()
            r = c.getresponse()
            r.read()
        finally:
            c.close()

    def call(self, peer, name, body, key=None, confirming=False):
        """A signed call to a peer (never to one that can't be called)."""
        if not peer.inbound and not confirming:
            return None
        key = key or self.sign_key(peer)
        raw = dumps(body)
        path = FED + name
        date, nonce = str(int(time.time())), b64u(os.urandom(16))
        host = host_of(peer.address)
        hs = [("Content-Type", "application/json"), (H_KEY, key.text), (H_DATE, date), (H_NONCE, nonce),
              (H_SIG, b64u(key.sign(request_message("POST", host, path, date, nonce, raw))))]
        try:
            c = self._connect(peer, name not in ("pair", "hello"))
        except OSError:
            return None
        try:
            c.putrequest("POST", path, skip_host=True, skip_accept_encoding=True)
            c.putheader("Host", host)
            for k, v in hs:
                c.putheader(k, v)
            c.putheader("Content-Length", str(len(raw)))
            c.endheaders(raw)
            r = c.getresponse()
            data = r.read()
            a = Answer(r.status, r.getheaders(), data, nonce, [peer.key])
        except (OSError, http.client.HTTPException):
            return None
        finally:
            c.close()
        if a.signed and name == "hello" and a.status == 200 and isinstance(a.json, dict):
            with self.lock:
                if a.json.get("state") == "paired" and peer.state == "theirs":
                    peer.state = "paired"
                peer.versions = (a.json.get("core"), a.json.get("parts"))
                peer.pins = read_pins(a.json.get("certificates"))
        return a

