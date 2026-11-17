"""The checks. Each one names the section of spec/v0.md (as corrected on
2026-11-16) it tests, and whether that section says must or should."""

import concurrent.futures
import os
import re
import time

from . import ed25519
from .report import FAIL, PASS, SKIP, Result
from .wire import (FED, CertificateRefused, Client, Key, PeerServer, answer_message, b64u, check_address,
                   dumps, fingerprint, host_of, is_int, parse_code, proof, request_message, unb64u)


class Skip(Exception):
    pass


class Fail(Exception):
    pass


NOT_FOUND = b'{"type":"not-found","title":"Not found","status":404}\n'

# Section 2.1's forged signature: the identity as key, R the identity, S 0.
# A library that skips the point checks accepts it for every message.
IDENTITY_KEY = "AQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
IDENTITY_SIG = "AQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
SMALL_ORDER_KEY = "JuiVj8KyJ7BFw_SJ8u-Y8NXfrAXTxjM5sTgCiG1T_AU"
MIXED_ORDER_KEY = "sVS9YhiK4oPdGH_v6MMfXidu3wg7TP8RydXP-FbHREA"
NON_CANONICAL_KEY = "7v_______________________________________38"

KINDS = {"movies", "tvshows", "music", "musicvideos", "homevideos", "boxsets", "books", "photos", "mixed", ""}
TITLE_KEY = re.compile(r"(movie)/tmdb/([1-9][0-9]{0,9})|(series)/tmdb/([1-9][0-9]{0,9})"
                       r"(?:/s(0|[1-9][0-9]{0,3})(?:/e(0|[1-9][0-9]{0,4}))?|/e([1-9][0-9]{0,9}))?")
TAG = re.compile(r"[A-Za-z0-9-]{2,12}")


def key_kind(k):
    """The kind a title key names, or None when it isn't canonical (section 11)."""
    m = TITLE_KEY.fullmatch(k) if isinstance(k, str) else None
    if not m:
        return None
    if m.group(1):
        return "movie" if int(m.group(2)) <= 9999999999 else None
    if int(m.group(4)) > 9999999999:
        return None
    if m.group(7):
        return "episode"
    if m.group(6) is not None:
        return "episode"
    if m.group(5) is not None:
        return "season"
    return "series"


def conventional_case(tag):
    """BCP 47's case conventions (section 2.1): language lowercase, script
    title case, region uppercase."""
    parts = tag.split("-")
    if parts[0] != parts[0].lower():
        return False
    for x in parts[1:]:
        if len(x) == 4 and x.isalpha() and x != x.title():
            return False
        if len(x) == 2 and x.isalpha() and x != x.upper():
            return False
    return True


class Suite:
    def __init__(self, args, report):
        self.a = args
        self.r = report
        self.code = None
        self.target_pub = None
        self.target = args.target
        self.key = Key.load_or_make(args.key) if args.key else Key()
        self.client = None
        self.server = None
        self.paired = False
        self.libraries = []
        self.seq = None
        self.whole = None
        self.answers = []          # every Answer that had to be signed

    # ---- running a check ---------------------------------------------------

    def check(self, cid, section, title, fn, level="MUST"):
        try:
            out = fn()
            status, detail = (PASS, out) if isinstance(out, str) or out is None else out
        except Skip as e:
            status, detail = SKIP, str(e)
        except Fail as e:
            status, detail = FAIL, str(e)
        except CertificateRefused as e:
            status, detail = FAIL, "certificate: %s" % e
        except (OSError, ValueError) as e:
            status, detail = FAIL, "%s: %s" % (type(e).__name__, e)
        self.r.add(Result(cid, section, title, level, status, detail or ""))
        return status == PASS

    @staticmethod
    def unsigned_404(a, also=()):
        if a.signed:
            raise Fail("signed answer %s; expected the unsigned 404 of a failed check" % a.short())
        if a.status != 404 and a.status not in also:
            raise Fail("got %s; expected the unsigned 404" % a.short())
        return "unsigned %d" % a.status

    def signed(self, a, status, what="answer"):
        self.answers.append(a)
        if a.status != status:
            raise Fail("got %s; expected a signed %d" % (a.short(), status))
        if not a.signed:
            raise Fail("the %d isn't signed by the target's key (section 6.6): %s" % (status, a.short()))
        if a.sig_header_count != 1:
            raise Fail("Overfin-Signature sent %d times (section 2.1)" % a.sig_header_count)
        if status == 200:
            if a.json_error:
                raise Fail("the 200 isn't I-JSON (section 2.1): %s" % a.json_error)
            if not isinstance(a.json, dict):
                raise Fail("the 200 isn't a JSON object")
            if _has_null(a.json):
                raise Fail("the answer sends null (section 2, since 2026-11-16 a sender must not)")
        return a

    # ---- the run -------------------------------------------------------------

    def run(self):
        a = self.a
        if a.code:
            self.check("C1", "5.1", "the pairing code reads as section 5.1 says", self.c_code)
        if not self.target:
            self.r.note("no target: give --target, or a --code that names one")
            return
        self.r.note("target %s, this peer's key %s (fingerprint %s)" % (self.target, self.key.text, fingerprint(self.key.pub)))
        self.client = Client(self.key, self.target, peer_pub=self.target_pub, connect=a.connect)
        try:
            Client(Key(), self.target, connect=a.connect, timeout=10).call("hello", {"state": "waiting"})
        except (OSError, CertificateRefused) as e:
            self.r.add(Result("S0", "3", "the target answers at its address", "MUST", FAIL, "%s: %s" % (type(e).__name__, e)))
            return
        self.stranger()
        if not a.code:
            self.r.note("no --code: the pairing and paired checks are skipped")
            return
        if not a.address:
            self.r.note("no --address: the suite can't pair (the target must reach it)")
            return
        self.server = PeerServer(self.key, a.address, a.listen, self.target_pub)
        # What this peer offers the target, from the start (section 9.3):
        # one library, three titles on two pages.
        self.server.offer = [{"id": "lib_conformance", "name": "Conformance films", "kind": "movies"}]
        self.server.pages = {
            "": {"titles": [{"key": "movie/tmdb/550", "kind": "movie", "library": "lib_conformance", "audio": ["en"]},
                            {"key": "movie/tmdb/603", "kind": "movie", "library": "lib_conformance", "audio": ["en"]}],
                 "next": "movie/tmdb/603", "seq": 1},
            "movie/tmdb/603": {"titles": [{"key": "movie/tmdb/949", "kind": "movie", "library": "lib_conformance", "audio": ["en"]}],
                               "seq": 1},
        }
        try:
            if not self.pairing():
                return
            self.waiting()
            if not self.wait_for_accept():
                return
            self.paired_checks()
        finally:
            self.server.close()

    # ---- the code ----------------------------------------------------------

    def c_code(self):
        key, secret, expiry, address = parse_code(self.a.code)
        self.code = (key, secret, expiry, address)
        self.target_pub = key
        if self.target and self.target != address:
            self.r.note("--target %s differs from the code's address %s: the code's is used" % (self.target, address))
        self.target = address
        if expiry <= time.time():
            raise Fail("the code expired at %d" % expiry)
        left = expiry - time.time()
        if left > 24 * 3600 + 60:
            raise Fail("expires in %.0f hours; section 5.1 says 24" % (left / 3600))
        return "key %s, address %s, expires in %.1f hours" % (b64u(key), address, left / 3600)

    # ---- strangers (no pairing) -----------------------------------------------

    def stranger(self):
        st = Key()
        # A stranger knows no pins: it takes any certificate, as only
        # refusals are checked here.
        c = Client(st, self.target, connect=self.a.connect, any_certificate=True)

        def unknown_key():
            return self.unsigned_404(c.call("hello", {"state": "waiting"}))
        self.check("S1", "6.4", "a stranger's hello gets the unsigned 404", unknown_key)

        def other_calls():
            for name in ("libraries", "titles"):
                self.unsigned_404(c.call(name, {} if name == "libraries" else {"libraries": []}))
            return "libraries and titles: unsigned 404"
        self.check("S2", "6.4", "a stranger's libraries and titles get the unsigned 404", other_calls)

        def same_as_missing():
            a = c.call("hello", {"state": "waiting"})
            path = FED + "conformance-no-such-call"
            body = dumps({"state": "waiting"})
            b = c.raw(path, body, c.headers(path, body))
            if a.status != b.status or a.body != b.body:
                raise Fail("failed check: %d %r; missing path: %d %r" % (a.status, a.body[:60], b.status, b.body[:60]))
            ct = lambda x: [v for k, v in x.headers if k.lower() == "content-type"]
            if ct(a) != ct(b):
                raise Fail("Content-Type differs: %s vs %s" % (ct(a), ct(b)))
            return "same status, body and type"
        self.check("S3", "3, 14", "the unsigned 404 can't be told from a path that doesn't exist", same_as_missing, "SHOULD")

        def wrong_method():
            path = FED + "hello"
            c2 = c._conn(False)[0]
            c2.request("GET", path)
            r = c2.getresponse(); r.read(); c2.close()
            path2 = FED + "conformance-no-such-call"
            c3 = c._conn(False)[0]
            c3.request("GET", path2)
            r2 = c3.getresponse(); r2.read(); c3.close()
            if r.status != r2.status:
                raise Fail("GET on hello: %d; GET on a missing path: %d" % (r.status, r2.status))
            return "both %d" % r.status
        self.check("S4", "3, 14", "a wrong method on a federation path answers like a missing path", wrong_method, "SHOULD")

    # ---- pairing ------------------------------------------------------------------

    def pair_body(self, key, address=None, secret=None, name="MSFP conformance suite"):
        _, code_secret, _, _ = self.code
        address = address or self.a.address
        s = secret or code_secret
        return dumps({"address": address, "name": name,
                      "secretHash": b64u(__import__("hashlib").sha256(code_secret).digest()),
                      "proof": b64u(proof(s, key.pub, address))})

    def pairing(self):
        c = self.client
        why = check_address(self.a.address)
        if why:
            self.r.note("--address %s breaks section 5.2 (%s); the target should refuse it" % (self.a.address, why))

        def wrong_proof():
            body = self.pair_body(self.key, secret=os.urandom(32))
            return self.unsigned_404(c.raw(FED + "pair", body, c.headers(FED + "pair", body)))
        self.check("P1", "9.1, 6.6", "pair with a wrong proof: the unsigned 404, and the code stays live", wrong_proof)

        def forged_identity():
            fake = Key()
            fake.text = IDENTITY_KEY
            body = self.pair_body(fake)
            h = c.headers(FED + "pair", body)
            h = [(k, IDENTITY_KEY if k == "Overfin-Key" else IDENTITY_SIG if k == "Overfin-Signature" else v) for k, v in h]
            a = c.raw(FED + "pair", body, h)
            if a.status == 200:
                raise Fail("ACCEPTED a pair signed by the identity key with R = identity, S = 0: "
                           "the target skips section 2.1's point checks, and anyone can forge its peers' requests")
            return self.unsigned_404(a)
        self.check("P2", "2.1, 4.1", "pair under the identity key with a forged signature is refused", forged_identity)

        def bad_keys():
            out = []
            for name, text in (("a point of order 8", SMALL_ORDER_KEY), ("a key with a small-order part", MIXED_ORDER_KEY),
                               ("a non-canonical encoding", NON_CANONICAL_KEY)):
                k = Key()
                body = self.pair_body(k)
                h = [(x, text if x == "Overfin-Key" else v) for x, v in c.headers(FED + "pair", body, key=k)]
                a = c.raw(FED + "pair", body, h)
                if a.status == 200:
                    raise Fail("accepted %s as Overfin-Key" % name)
                self.unsigned_404(a)
                out.append(name)
            return "refused: " + ", ".join(out)
        self.check("P3", "2.1, 4.1", "pair under keys section 2.1 refuses (small order, not canonical) is refused", bad_keys)

        def stale():
            body = self.pair_body(self.key)
            return self.unsigned_404(c.raw(FED + "pair", body, c.headers(FED + "pair", body, date=str(int(time.time()) - 400))))
        self.check("P4", "6.4", "pair dated 400 seconds ago is refused", stale)

        def bad_addresses():
            bad = ["HTTPS://a.example.org", "http://10.0.0.1:80", "http://10.0.0.1/", "http://10.0.0.010:8000",
                   "http://Upper.example.org", "http://10.0.0.1:08000"]
            for addr in bad:
                k = Key()
                body = self.pair_body(k, address=addr)
                a = c.raw(FED + "pair", body, c.headers(FED + "pair", body, key=k))
                if a.status == 200:
                    raise Fail("accepted the address %r (the code is now used: pairing can't go on)" % addr)
                self.unsigned_404(a)
            return "refused %d addresses that break section 5.2" % len(bad)
        if not self.check("P5", "5.2, 9.1", "pair naming an invalid address is refused, the code stays live", bad_addresses):
            if self.r.results[-1].status == FAIL and "code is now used" in self.r.results[-1].detail:
                return False

        state = {}

        def pair():
            body = self.pair_body(self.key)
            h = c.headers(FED + "pair", body)
            state["req"] = (body, h)
            a = c.raw(FED + "pair", body, h)
            if a.status != 200:
                raise Fail("got %s: check that the code is live and that the target reaches %s" % (a.short(), self.a.address))
            self.signed(a, 200)
            name = a.json.get("name")
            if not isinstance(name, str):
                raise Fail("no name string in %r" % a.body[:100])
            self.target_name = name
            return "paired from this side; the target calls itself %r" % name
        if not self.check("P6", "9.1, 7.1", "pair with the code: 200, signed by the code's key", pair):
            return False

        def replay():
            body, h = state["req"]
            return self.unsigned_404(c.raw(FED + "pair", body, h))
        self.check("P7", "6.5", "the same pair request again (its nonce replayed) gets the unsigned 404", replay)

        def code_used():
            body = self.pair_body(self.key)
            a = c.raw(FED + "pair", body, c.headers(FED + "pair", body))
            if a.status == 200:
                raise Fail("the code worked twice")
            if a.status == 409 and a.signed:
                return "signed 409 (the code is gone, so a 404 was expected; 7.1 step 4 deletes it)"
            return self.signed(a, 404) and "signed 404"
        self.check("P8", "9.1, 7.1", "the used code again, from the now known key: a signed 404", code_used)
        self.paired = True
        return True

    # ---- waiting for the target's operator -------------------------------------

    def waiting(self):
        c = self.client

        def hello_waiting():
            a = self.signed(c.call("hello", {"state": "waiting"}), 200)
            if a.json.get("state") not in ("waiting", "paired"):
                raise Fail("state %r" % a.json.get("state"))
            self.read_pins(a)
            return "state %s" % a.json["state"]
        self.check("W1", "9.2, 7.3", "hello waiting: 200 signed, state waiting", hello_waiting)

        def cant_force():
            a = self.signed(c.call("hello", {"state": "paired"}), 200)
            if a.json.get("state") == "paired":
                raise Skip("the target was already accepted, so this can't be told")
            again = self.signed(c.call("hello", {"state": "waiting"}), 200)
            if again.json.get("state") != "waiting":
                raise Fail("a hello paired from a peer waiting for the target's operator changed its state")
            return "still waiting"
        self.check("W2", "7.1, 9.2", "hello paired from a waiting peer changes nothing", cant_force)

        def libs_waiting():
            a = c.call("libraries", {})
            if a.status == 200 and a.signed:
                if self.signed(c.call("hello", {"state": "waiting"}), 200).json.get("state") == "paired":
                    raise Skip("already accepted")
                raise Fail("libraries answered 200 before the target's operator accepted")
            return self.signed(a, 404) and "signed 404"
        self.check("W3", "7.3", "libraries before the target's operator accepts: a signed 404", libs_waiting)

    def wait_for_accept(self):
        c = self.client
        self.r.note("now accept the pairing on the target's side: peer %r, fingerprint %s (waiting up to %d s)"
                    % ("MSFP conformance suite", fingerprint(self.key.pub), self.a.accept_timeout))
        end = time.time() + self.a.accept_timeout
        while time.time() < end:
            if self.server.state == "paired":
                break
            a = c.call("hello", {"state": "waiting"})
            if a.signed and a.status == 200 and a.json and a.json.get("state") == "paired":
                self.server.state = "paired"
                self.r.note("the target answered paired before telling this peer")
                break
            time.sleep(min(10, max(0, end - time.time())))
        if self.server.state != "paired":
            self.r.add(Result("W4", "7.1", "the target's operator accepted", "MUST", SKIP,
                              "not accepted within %d s: the paired checks are skipped" % self.a.accept_timeout))
            return False

        def told_us():
            hellos = [x for x in self.server.requests if x["call"] == "hello"]
            if not hellos:
                raise Fail("the target never sent this peer a hello (7.1 step 6), or it couldn't reach %s" % self.a.address)
            bad = [x for x in hellos if x["faults"]]
            if bad:
                raise Fail("; ".join(bad[0]["faults"]))
            return "%d hello(s), all well signed" % len(hellos)
        self.check("W4", "7.1, 6.4", "on accepting, the target sends this peer a signed hello paired", told_us)
        return True

    def read_pins(self, a):
        if isinstance(a.json, dict) and isinstance(a.json.get("certificates"), list):
            pins = []
            for p in a.json["certificates"]:
                if isinstance(p, str) and len(p) == 43 and unb64u(p, 32) is not None and p not in pins and len(pins) < 8:
                    pins.append(p)
            self.client.pins = pins
        elif isinstance(a.json, dict):
            self.client.pins = []

    # ---- paired ------------------------------------------------------------------------

    def paired_checks(self):
        c = self.client

        def hello_paired():
            a = self.signed(c.call("hello", {"state": "paired"}), 200)
            if a.json.get("state") != "paired":
                raise Fail("state %r" % a.json.get("state"))
            certs = a.json.get("certificates")
            if certs is not None and not isinstance(certs, list):
                raise Fail("certificates isn't an array")
            self.read_pins(a)
            return "paired; pins named: %s" % (self.client.pins or "none")
        self.check("H1", "9.2", "hello paired: 200 signed, state paired", hello_paired)

        def pins_match():
            if not self.target.startswith("https://"):
                raise Skip("an http target names no pins")
            a = c.call("hello", {"state": "paired"})
            if a.trusted:
                return "the certificate is publicly trusted (pins optional)"
            if a.leaf_pin not in self.client.pins:
                raise Fail("the leaf served (%s) isn't among the pins named (%s)" % (a.leaf_pin, self.client.pins))
            return "the served leaf %s is named" % a.leaf_pin
        self.check("H2", "3.1", "over https, the target names the pin of the certificate it serves", pins_match, "SHOULD")

        def checked_call_tls():
            if not self.target.startswith("https://"):
                raise Skip("http target")
            a = c.call("libraries", {})
            return "libraries passed the trusted-or-named check: %s" % a.status
        self.check("H3", "3.1", "over https, checked calls pass with the certificate trusted or named", checked_call_tls)

        self.hello_bodies()
        self.signing_rules()
        self.replay_rules()
        self.libraries_checks()
        self.titles_checks()
        self.reader_checks()
        if self.a.load:
            self.load_checks()
        else:
            self.r.add(Result("R1", "8.3", "past a peer's limit: a signed 429 with retryAfter", "MUST", SKIP,
                              "sends several hundred calls at once: run with --load"))
        if self.a.end:
            self.end_checks()
        else:
            self.r.add(Result("E1", "7.4", "ending: hello ended, then the target forgets this peer", "MUST", SKIP,
                              "ends the pairing: run with --end"))

        bad = [a for a in self.answers if not a.signed]
        self.check("A1", "6.6", "every answer the suite checked was signed by the target's key",
                   lambda: "%d answers" % len(self.answers) if not bad else (FAIL, "%d unsigned" % len(bad)))

    def hello_bodies(self):
        c = self.client
        refused = [
            ("no state", b'{}'),
            ("state not a string", b'{"state":7}'),
            ("state null", b'{"state":null}'),
            ("State in another case", b'{"State":"paired"}'),
            ("certificates not an array", b'{"state":"paired","certificates":"x"}'),
            ("an array, not an object", b'[]'),
            ("not JSON", b'state=paired'),
            ("state twice", b'{"state":"paired","state":"ended"}'),
            ("state twice, once escaped", b'{"state":"paired","\\u0073tate":"ended"}'),
            ("a member twice, nested", b'{"state":"paired","x":{"a":1,"a":2}}'),
            ("a lone high surrogate, escaped", b'{"state":"paired","x":"\\ud800"}'),
            ("a lone low surrogate, escaped", b'{"state":"paired","x":"\\udc00x"}'),
            ("a noncharacter", b'{"state":"paired","x":"\xef\xbf\xbf"}'),
            ("invalid UTF-8", b'{"state":"paired","x":"\xff"}'),
            ("a byte order mark", b'\xef\xbb\xbf{"state":"paired"}'),
        ]
        accepted = [
            ("white space between tokens", b'{ "state" : "paired" }'),
            ("a surrogate pair, escaped", b'{"state":"paired","x":"\\ud83c\\udfac"}'),
            ("an unknown member", b'{"state":"paired","x":[1,{"y":null}]}'),
            ("certificates null", b'{"state":"paired","certificates":null}'),
            ("an unknown state string", b'{"state":"conformance"}'),
        ]

        def run_refused():
            bad = []
            for name, body in refused:
                a = c.raw(FED + "hello", body, c.headers(FED + "hello", body))
                if not (a.status == 404 and a.signed):
                    bad.append("%s: %s" % (name, a.short()))
                self.answers.append(a)
            if bad:
                raise Fail("expected a signed 404 for:\n" + "\n".join(bad))
            return "%d bodies refused with a signed 404" % len(refused)
        self.check("J1", "2.1, 9.2", "hello bodies that aren't valid (I-JSON, state) get a signed 404", run_refused)

        def run_accepted():
            bad = []
            for name, body in accepted:
                a = c.raw(FED + "hello", body, c.headers(FED + "hello", body))
                try:
                    self.signed(a, 200)
                except Fail as e:
                    bad.append("%s: %s" % (name, e))
            if bad:
                raise Fail("\n".join(bad))
            return "%d accepted" % len(accepted)
        self.check("J2", "2.1, 9.2", "valid hello bodies (white space, surrogate pairs, unknown members, null) pass", run_accepted)

    def signing_rules(self):
        c = self.client
        body = dumps({"state": "paired"})
        p = FED + "hello"
        now = int(time.time())

        def h(**kw):
            return c.headers(p, body, **kw)

        def mutate(hs, name, value):
            return [(k, value if k == name else v) for k, v in hs]

        cases = [
            ("dated 330 seconds ago", h(date=str(int(time.time()) - 330))),
            ("dated 330 seconds ahead", h(date=str(int(time.time()) + 330))),
            ("a date with a plus sign", None, "+"),
            ("a date with a leading zero", None, "0"),
            ("a date with a fraction", None, ".0"),
            ("a date of 0", h(date="0")),
            ("a date of 2^53", h(date=str(2**53))),
            ("a nonce of 15 bytes", h(nonce=b64u(os.urandom(15)))),
            ("a padded nonce", h(nonce=b64u(os.urandom(16)) + "==")),
            ("a nonce with nonzero unused bits", h(nonce=b64u(b"\0" * 16)[:-1] + "B")),
            ("a nonce in the standard alphabet", h(nonce="+" + b64u(os.urandom(16))[1:])),
            ("signed for another host", h(sign_host="conformance.example.org")),
            ("signed for another path", h(sign_path=FED + "libraries")),
        ]

        def run():
            bad = []
            for case in cases:
                name, hs = case[0], case[1]
                if hs is None:
                    base = h()
                    d = dict(base)["Overfin-Date"]
                    nd = "+" + d if case[2] == "+" else ("0" + d if case[2] == "0" else d + ".0")
                    msg = request_message("POST", c.host, p, nd, dict(base)["Overfin-Nonce"], body)
                    hs = mutate(mutate(base, "Overfin-Date", nd), "Overfin-Signature", b64u(self.key.sign(msg)))
                a = c.raw(p, body, hs)
                if a.status == 200 or a.signed:
                    bad.append("%s: %s" % (name, a.short()))
            # The key with a nonzero unused bit (another text of the same bytes).
            k = self.key.text
            alt = k[:-1] + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"[
                ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_".index(k[-1]) + 1) % 64]
            hs = mutate(h(), "Overfin-Key", alt)
            a = c.raw(p, body, hs)
            if a.status == 200:
                bad.append("a key text with nonzero unused bits: %s" % a.short())
            if bad:
                raise Fail("expected the unsigned 404 for:\n" + "\n".join(bad))
            return "%d forms refused" % (len(cases) + 1)
        self.check("G1", "2.1, 6.4", "dates, nonces, keys and signatures outside their one form, or signed for another host or path, are refused", run)

        def headers():
            base = h()
            sig = base[-1]
            forms = [
                ("the signature header twice", base + [sig]),
                ("the nonce header twice", base + [base[3]]),
                ("a comma in the signature", base[:-1] + [(sig[0], sig[1] + "," + sig[1])]),
                ("a tab inside the date", mutate(base, "Overfin-Date", base[2][1][:3] + "\t" + base[2][1][3:])),
            ]
            bad = []
            for name, hs in forms:
                a = c.raw(p, body, hs)
                if a.status == 200 or a.signed:
                    bad.append("%s: %s" % (name, a.short()))
            if bad:
                raise Fail("expected the unsigned 404 for:\n" + "\n".join(bad))
            return "%d forms refused" % len(forms)
        self.check("G2", "2.1, 6.4", "each signature header exactly once, no comma, no inner white space", headers)

        def lenient_forms():
            forms = [("lowercase header names", lambda hs: [(k.lower(), v) for k, v in hs]),
                     ("spaces around a value", lambda hs: mutate(hs, "Overfin-Date", "  " + dict(hs)["Overfin-Date"] + " ")),
                     ("Content-Type with a charset", lambda hs: mutate(hs, "Content-Type", "application/json; charset=utf-8"))]
            bad = []
            for name, f in forms:
                a = c.raw(p, body, f(h()))
                if not (a.status == 200 and a.signed):
                    bad.append("%s: %s" % (name, a.short()))
            if bad:
                raise Fail("\n".join(bad))
            return "accepted"
        self.check("G3", "2.1", "header names in any case, optional white space and media type parameters are accepted", lenient_forms)

        def query():
            path = p + "?conformance=1"
            a = c.raw(path, body, c.headers(path, body))
            if a.status == 200:
                raise Fail("a hello signed over %s was answered 200" % path)
            return self.unsigned_404(a)
        self.check("G4", "6.2, 6.4", "a federation call with a query is refused, even when signed so", query)

        def percent():
            path = FED + "%68ello"
            a = c.raw(path, body, c.headers(path, body, sign_path=FED + "hello"))
            if a.status == 200:
                raise Fail("a request to %s signed over the decoded path passed: the target rebuilds <target> from a decoded path" % path)
            return self.unsigned_404(a, also=(400,))
        self.check("G5", "6.2", "the target is taken as received: a percent-encoded path signed decoded fails", percent)

        def media_type():
            out = []
            for ct, name in ((None, "no Content-Type"), ("text/plain", "text/plain")):
                hs = [x for x in h() if x[0] != "Content-Type"] + ([("Content-Type", ct)] if ct else [])
                a = c.raw(p, body, hs)
                if a.status == 200 or a.signed:
                    raise Fail("%s: %s" % (name, a.short()))
                out.append("%s: unsigned %d" % (name, a.status))
            return "; ".join(out) + " (section 3 says the unsigned 404; Overfin's 415 is a version 0 note)"
        self.check("G6", "3", "a request that isn't application/json is refused, unsigned", media_type)

        def cross_site():
            a = c.raw(p, body, h() + [("Sec-Fetch-Site", "cross-site")])
            if a.status == 200 or a.signed:
                raise Fail(a.short())
            return "unsigned %d" % a.status
        self.check("G7", "3", "a cross-site Sec-Fetch-Site is refused, unsigned", cross_site)

    def replay_rules(self):
        c = self.client
        p = FED + "hello"

        def same_twice():
            body = dumps({"state": "paired"})
            hs = c.headers(p, body)
            self.signed(c.raw(p, body, hs), 200)
            return self.unsigned_404(c.raw(p, body, hs))
        self.check("N1", "6.5", "a request replayed with its nonce gets the unsigned 404", same_twice)

        def nonce_reused():
            n = b64u(os.urandom(16))
            body = dumps({"state": "paired"})
            self.signed(c.raw(p, body, c.headers(p, body, nonce=n)), 200)
            body2 = dumps({"state": "waiting"})
            return self.unsigned_404(c.raw(p, body2, c.headers(p, body2, nonce=n)))
        self.check("N2", "6.5", "a nonce used again in a new, validly signed request gets the unsigned 404", nonce_reused)

        def answer_bound():
            a = c.call("hello", {"state": "paired"})
            sig = unb64u([v for k, v in a.headers if k.lower() == "overfin-signature"][0].strip(), 64)
            other = b64u(os.urandom(16))
            if ed25519.verify_strict(self.target_pub, answer_message(other, a.status, a.body), sig):
                raise Fail("the answer's signature verifies for another nonce")
            return "the answer's signature covers the request's nonce"
        self.check("N3", "6.3", "the answer's signature is bound to the request's nonce", answer_bound)

    # ---- libraries and titles ----------------------------------------------------------

    def libraries_checks(self):
        c = self.client

        def libs():
            a = self.signed(c.call("libraries", {}), 200)
            j = a.json
            if "name" in j and not isinstance(j["name"], str):
                raise Fail("name isn't a string")
            libs = j.get("libraries")
            if not isinstance(libs, list):
                raise Fail("libraries isn't an array")
            notes, ids = [], []
            for lib in libs:
                if not isinstance(lib, dict):
                    raise Fail("a library that isn't an object: %r" % lib)
                i = lib.get("id")
                if not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", i):
                    raise Fail("an ID outside 1 to 64 characters of A-Z a-z 0-9 _ -: %r" % i)
                if i in ids:
                    raise Fail("the ID %r twice" % i)
                ids.append(i)
                if not isinstance(lib.get("name"), str):
                    raise Fail("library %s: name isn't a string" % i)
                if lib.get("kind") not in KINDS:
                    raise Fail("library %s: kind %r isn't one of section 9.3's" % (i, lib.get("kind")))
            lim = j.get("limits")
            if lim is not None:
                if not isinstance(lim, dict):
                    raise Fail("limits isn't an object")
                s, t, b = lim.get("streams"), lim.get("transcodes"), lim.get("bitrateKbps")
                if not (is_int(s) and 0 <= s <= 50 and is_int(t) and 0 <= t <= s and is_int(b) and 0 <= b <= 1000000):
                    raise Fail("limits out of range: %r" % lim)
            self.libraries = libs
            return "%d librar%s offered: %s" % (len(libs), "y" if len(libs) == 1 else "ies", ", ".join("%s (%s)" % (x["id"], x["kind"]) for x in libs) or "none")
        self.check("L1", "9.3", "libraries: 200 signed, IDs and kinds in their forms, no ID twice, limits in range", libs)

        def opaque():
            if not self.libraries:
                raise Skip("nothing offered to this peer")
            looks = [x["id"] for x in self.libraries if re.fullmatch(r"[0-9a-f]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", x["id"])]
            if looks:
                raise Fail("IDs shaped like a media server's item IDs (32 hex digits or a GUID): %s; section 9.3 "
                           "says they must not be one (a heuristic: a random value may look so)" % looks)
            return "none looks like a media server ID"
        self.check("L2", "9.3, 12", "library IDs don't look like the media server's own IDs", opaque, "SHOULD")

        def bad_body():
            out = []
            for name, body in (("an array", b"[]"), ("not JSON", b"libraries"), ("a member twice", b'{"a":1,"a":2}')):
                a = c.raw(FED + "libraries", body, c.headers(FED + "libraries", body))
                self.signed(a, 404)
                out.append(name)
            return "signed 404 for " + ", ".join(out)
        self.check("L3", "9.3, 2.1", "a libraries body that isn't an I-JSON object gets a signed 404", bad_body)

    def read_titles(self, libs, since=None, after="", limit_pages=200):
        """One reading; returns (pages, problems)."""
        pages, problems = [], []
        c = self.client
        while len(pages) < limit_pages:
            req = {"libraries": libs, "after": after}
            if since is not None:
                req["since"] = since
            a = self.signed(c.call("titles", req), 200)
            pages.append(a.json)
            nxt = a.json.get("next")
            if not isinstance(nxt, str) or nxt == "" or nxt <= after:
                break
            after = nxt
        return pages

    def validate_page(self, j, libs, after, whole):
        bad = []
        titles = j.get("titles")
        if titles is not None and not isinstance(titles, list):
            return ["titles isn't an array"]
        titles = titles or []
        keys = []
        for t in titles:
            if not isinstance(t, dict):
                bad.append("a title that isn't an object")
                continue
            k, kind, lib = t.get("key"), t.get("kind"), t.get("library")
            kk = key_kind(k)
            if kk is None:
                bad.append("%r isn't a canonical TMDB title key (section 11)" % k)
            elif kk != kind:
                bad.append("%s: kind %r, the key names %s" % (k, kind, kk))
            if lib not in libs:
                bad.append("%s: library %r wasn't asked for" % (k, lib))
            if isinstance(k, str):
                keys.append(k)
            for f in ("audio", "subtitles"):
                v = t.get(f)
                if v is None:
                    continue
                if kind in ("series", "season") and v:
                    bad.append("%s (%s) carries %s (section 9.4: films and episodes only)" % (k, kind, f))
                if not isinstance(v, list) or len(v) > 12:
                    bad.append("%s: %s isn't an array of at most 12 tags" % (k, f))
                    continue
                seen = set()
                for tag in v:
                    if not isinstance(tag, str) or not TAG.fullmatch(tag):
                        bad.append("%s: %s tag %r isn't 2 to 12 characters of A-Z a-z 0-9 -" % (k, f, tag))
                    elif tag.lower() in seen:
                        bad.append("%s: %s tag %r twice (compared without case)" % (k, f, tag))
                    elif tag.split("-")[0].lower() in ("und", "mul", "zxx", "mis"):
                        bad.append("%s: %s tag %r is one section 9.4 says isn't sent" % (k, f, tag))
                    elif not conventional_case(tag):
                        bad.append("%s: %s tag %r not in BCP 47's case conventions (section 2.1)" % (k, f, tag))
                    elif len(tag.split("-")[0]) == 3 and tag.split("-")[0].lower() in ISO639_2_WITH_1:
                        bad.append("%s: %s tag %r has a two-letter code (section 9.4: the shortest)" % (k, f, tag))
                    if isinstance(tag, str):
                        seen.add(tag.lower())
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            bad.append("keys not in strictly ascending byte order")
        if any(k <= after for k in keys):
            bad.append("keys not greater than after %r" % after)
        gone = j.get("gone") or []
        if len(titles) + (len(gone) if isinstance(gone, list) else 0) > 5000:
            bad.append("more than 5,000 keys in a page")
        if whole and "next" in j and isinstance(j["next"], str) and j["next"] and len(titles) < 5000:
            bad.append("a whole-list page with next but fewer than 5,000 titles (section 9.4: next only when full)")
        if whole and j.get("next") and keys and j["next"] != keys[-1]:
            bad.append("next isn't the page's last key")
        seq = j.get("seq")
        if seq is not None and not (is_int(seq) and seq > 0):
            bad.append("seq %r isn't a positive integer" % seq)
        if "changes" in j and not isinstance(j["changes"], bool):
            bad.append("changes isn't a boolean")
        return bad

    def titles_checks(self):
        c = self.client
        libs = sorted(x["id"] for x in self.libraries)

        def need():
            if not libs:
                raise Skip("the target offers this peer no library: offer one on the target, then run again")

        def whole():
            need()
            pages = self.read_titles(libs)
            bad = []
            after = ""
            for j in pages:
                if j.get("changes") is True:
                    bad.append("a reading without since answered with changes")
                bad += self.validate_page(j, libs, after, True)
                ks = [t["key"] for t in (j.get("titles") or []) if isinstance(t, dict) and isinstance(t.get("key"), str)]
                if ks:
                    after = ks[-1]
            if bad:
                raise Fail("\n".join(bad[:20]))
            self.whole = [t for j in pages for t in (j.get("titles") or [])]
            self.seq = pages[0].get("seq")
            return "%d titles in %d page(s), seq %s" % (len(self.whole), len(pages), self.seq)
        self.check("T1", "9.4, 11", "titles, the whole list: keys, kinds, libraries, language tags, order, paging", whole)

        def paging():
            need()
            if not self.whole or len(self.whole) < 2:
                raise Skip("fewer than 2 titles offered")
            after = self.whole[0]["key"]
            pages = self.read_titles(libs, after=after)
            got = [t["key"] for j in pages for t in (j.get("titles") or [])]
            want = [t["key"] for t in self.whole[1:]]
            if got != want:
                raise Fail("after %r gave %d titles; the whole list has %d after it" % (after, len(got), len(want)))
            return "after %r gives the rest of the list" % after
        self.check("T2", "9.4", "a page starts strictly after `after`", paging)

        def changes():
            need()
            if not self.seq:
                raise Skip("the target sends no seq: it is asked for the whole list every time (allowed)")
            j = self.read_titles(libs, since=self.seq)[0]
            if j.get("changes") is not True:
                return (PASS, "answered with the whole list (allowed: the target may not keep a change log)")
            bad = self.validate_page(j, libs, "", False)
            if bad:
                raise Fail("\n".join(bad))
            return "changes: %d new or changed, %d gone, seq %s" % (len(j.get("titles") or []), len(j.get("gone") or []), j.get("seq"))
        self.check("T3", "9.4", "titles since the current seq: a changes answer (or the whole list)", changes)

        def above():
            need()
            if not self.seq:
                raise Skip("no seq")
            j = self.read_titles(libs, since=self.seq + 1000000)[0]
            if j.get("changes") is True:
                raise Fail("since above the current seq was answered with changes; section 9.4: the whole list")
            return "the whole list"
        self.check("T4", "9.4", "since above the current seq: the whole list", above)

        def negative():
            need()
            j = self.read_titles(libs, since=-1)[0]
            if j.get("changes") is True:
                raise Fail("a negative since was answered with changes")
            return "the whole list"
        self.check("T5", "9.4", "a negative since is answered like 0", negative)

        def bad_requests():
            need()
            forms = [
                ("since as a string", {"libraries": libs, "since": "5"}),
                ("since 1.0", None, b'{"libraries":%s,"since":1.0}'),
                ("since 1e1", None, b'{"libraries":%s,"since":1e1}'),
                ("since 2^53", None, b'{"libraries":%s,"since":9007199254740992}'),
                ("since -0", None, b'{"libraries":%s,"since":-0}'),
                ("after over 512 bytes", {"libraries": libs, "after": "a" * 513}),
                ("a library ID that isn't a string", {"libraries": libs + [7]}),
                ("libraries missing", {}),
                ("libraries null", {"libraries": None}),
            ]
            bad = []
            for f in forms:
                name = f[0]
                body = dumps(f[1]) if f[1] is not None else (f[2] % dumps(libs))
                a = c.raw(FED + "titles", body, c.headers(FED + "titles", body))
                self.answers.append(a)
                if not (a.status == 404 and a.signed):
                    bad.append("%s: %s" % (name, a.short()))
            if bad:
                raise Fail("expected a signed 404 for:\n" + "\n".join(bad))
            return "%d bad requests refused" % len(forms)
        self.check("T6", "9.4, 2.1, 9", "bad titles requests (since not an integer, after too long, libraries missing) get a signed 404", bad_requests)

        def unknown_library():
            need()
            j = self.read_titles(["lib_conformance_not_offered"])[0]
            if j.get("titles"):
                raise Fail("titles for a library that isn't offered: %r" % j["titles"][:2])
            return "ignored"
        self.check("T7", "9.4, 12", "a library ID that isn't offered is ignored", unknown_library)

        def watch():
            need()
            if not self.a.watch_changes:
                raise Skip("run with --watch-changes SECONDS, then add one title to an offered library and remove one, on the target")
            if not self.seq:
                raise Skip("the target sends no seq")
            self.r.note("now add one title to an offered library and remove one on the target; waiting %d s" % self.a.watch_changes)
            end = time.time() + self.a.watch_changes
            old = {t["key"] for t in self.whole}
            while time.time() < end:
                time.sleep(15)
                j = self.read_titles(libs, since=self.seq)
                first = j[0]
                if first.get("changes") is True and ((first.get("titles") or []) or (first.get("gone") or [])):
                    new = [t["key"] for p in j for t in (p.get("titles") or [])]
                    gone = [k for p in j for k in (p.get("gone") or [])]
                    bad = sum((self.validate_page(p, libs, "", False) for p in j), [])
                    if any(g not in old for g in gone):
                        bad.append("gone holds keys that weren't in the list: %s" % [g for g in gone if g not in old])
                    if bad:
                        raise Fail("\n".join(bad))
                    whole_now = {t["key"] for p in self.read_titles(libs) for t in (p.get("titles") or [])}
                    expect = (old - set(gone)) | set(new)
                    if whole_now != expect:
                        raise Fail("the changes don't add up to the new whole list: %s vs %s" % (sorted(expect ^ whole_now), ""))
                    return "changes: %s new or changed, %s gone, and they add up to the whole list" % (new, gone)
            raise Skip("no change seen in %d s" % self.a.watch_changes)
        self.check("T8", "9.4", "after a change on the target: changes and gone add up to the new whole list", watch)

    # ---- the target as a reader of this peer ------------------------------------------------

    def reader_checks(self):
        s = self.server
        if not self.a.reader_timeout:
            self.r.add(Result("Q1", "9.3, 9.4, 6.4", "the target reads this peer's libraries and titles, well signed, following next",
                              "MUST", SKIP, "run with --reader-timeout SECONDS and, on the target, want this peer's library %r" % "Conformance films"))
            return
        self.r.note("this peer now offers one library, 'Conformance films' (3 titles on 2 pages): on the target, "
                    "want it; waiting up to %d s for the target to read it" % self.a.reader_timeout)
        end = time.time() + self.a.reader_timeout
        while time.time() < end:
            calls = [x for x in s.requests if x["call"] == "titles"]
            if any(b'"after":"movie/tmdb/603"' in x["body"] for x in calls):
                break
            time.sleep(5)
        time.sleep(2)

        def reads():
            lib = [x for x in s.requests if x["call"] == "libraries"]
            ts = [x for x in s.requests if x["call"] == "titles"]
            if not lib and not ts:
                raise Skip("the target didn't call this peer within %d s" % self.a.reader_timeout)
            bad = [f for x in lib + ts for f in x["faults"]]
            if bad:
                raise Fail("\n".join(sorted(set(bad))))
            if not ts:
                raise Fail("the target read libraries but asked for no titles")
            return "%d libraries and %d titles calls, all well signed" % (len(lib), len(ts))
        self.check("Q1", "6.4, 9.3, 9.4", "the target's calls to this peer are well signed and well formed", reads)

        def bodies():
            bad = []
            for x in s.requests:
                if x["call"] != "titles":
                    continue
                try:
                    from .wire import parse_ijson
                    j = parse_ijson(x["body"])
                except Exception as e:
                    bad.append(str(e))
                    continue
                if not isinstance(j.get("libraries"), list) or any(not isinstance(i, str) for i in j["libraries"]):
                    bad.append("libraries isn't an array of strings: %r" % x["body"][:100])
                elif set(j["libraries"]) - {"lib_conformance"}:
                    bad.append("asks for libraries this peer doesn't offer: %r" % j["libraries"])
                if "after" in j and not isinstance(j["after"], str):
                    bad.append("after isn't a string")
                if "since" in j and not is_int(j["since"]):
                    bad.append("since isn't an integer: %r" % j["since"])
            if not any(x["call"] == "titles" for x in s.requests):
                raise Skip("no titles call")
            if bad:
                raise Fail("\n".join(bad))
            return "well formed"
        self.check("Q2", "9.4", "the target's titles requests: libraries offered, after a string, since an integer", bodies)

        def follows():
            ts = [x for x in s.requests if x["call"] == "titles"]
            if not ts:
                raise Skip("no titles call")
            if not any(b'"after":"movie/tmdb/603"' in x["body"] for x in ts):
                raise Fail("the target didn't ask for the page after next = movie/tmdb/603")
            return "followed next (this peer sends next on a short page on purpose, to see it followed)"
        self.check("Q3", "9.4", "the target follows next to the following page", follows)

    # ---- destructive or heavy ------------------------------------------------------------

    def load_checks(self):
        c = self.client
        p = FED + "hello"
        body = dumps({"state": "paired"})
        n = self.a.load_count
        self.r.note("signing %d requests for the load check (pure Python: this takes a while)" % n)
        reqs = [c.headers(p, body) for _ in range(n)]

        def flood():
            t0 = time.time()
            res = c.burst(p, body, reqs)
            took = max(time.time() - t0, 0.001)
            ok = [a for a in res if not isinstance(a, Exception) and a.status == 200]
            limited = [a for a in res if not isinstance(a, Exception) and a.status in (429, 503) and a.signed]
            errors = [a for a in res if isinstance(a, Exception)]
            other = [a for a in res if not isinstance(a, Exception) and a not in ok and a not in limited]
            summary = "%d calls in %.1f s (%.0f a second): %d passed, %d signed 429/503, %d other (%s), %d connection errors" % (
                len(res), took, len(res) / took, len(ok), len(limited), len(other), sorted({a.status for a in other}), len(errors))
            for a in limited:
                ra = a.json.get("retryAfter") if isinstance(a.json, dict) else None
                if ra is not None and not (is_int(ra) and 1 <= ra <= 3600):
                    raise Fail("retryAfter %r isn't an integer from 1 to 3,600; %s" % (ra, summary))
                t = a.json.get("type") if isinstance(a.json, dict) else None
                if (a.status, t) not in ((429, "rate-limited"), (503, "server-busy")):
                    raise Fail("a %d of type %r (section 8.2: 429 rate-limited, 503 server-busy); %s" % (a.status, t, summary))
            if not limited and not other:
                # The numbers are each implementation's (section 8.3): a
                # limit not reached proves nothing unless the burst was big.
                if len(ok) >= 1000 and len(res) / took >= 300:
                    raise Fail("no limit at all: " + summary)
                raise Skip("no limit reached, which this burst can't tell from no limit: %s. "
                           "Raise --load-count, or run the suite nearer the target" % summary)
            if errors and not limited and not other:
                raise Fail("connections dropped instead of answers (section 8.3: answer, never hang): " + summary)
            if not limited:
                return (PASS, summary + " (only refusals before the signature: allowed, but a signed 429 tells the peer when to come back)")
            self.retry_after = max((a.json.get("retryAfter") or 0) for a in limited)
            return summary
        self.check("R1", "8.3", "past a peer's limit: a signed 429 rate-limited (or 503) with retryAfter", flood)

        def recovers():
            if not hasattr(self, "retry_after"):
                raise Skip("no signed 429 or 503 in the burst")
            wait = self.retry_after or 5
            time.sleep(min(wait, 60) + 1)
            return self.signed(c.call("hello", {"state": "paired"}), 200) and "answered again after %d s" % wait
        self.check("R2", "8.3", "after retryAfter, calls pass again", recovers)

    def end_checks(self):
        c = self.client

        def end():
            a = self.signed(c.call("hello", {"state": "ended"}), 200)
            if a.json.get("state") != "ended":
                raise Fail("state %r; expected ended" % a.json.get("state"))
            if "certificates" in a.json:
                return (PASS, "ended (it also sent certificates, which Overfin leaves out)")
            return "ended"
        if not self.check("E1", "7.4, 9.2", "hello ended: 200 signed, state ended", end):
            return

        def forgotten():
            a = c.call("hello", {"state": "waiting"})
            if a.status == 200:
                raise Fail("the target still answers this peer: %s" % a.short())
            return self.unsigned_404(a)
        self.check("E2", "7.4, 6.4", "after ended, the target has deleted this peer: an unsigned 404 (it doesn't record the ender as forgotten)", forgotten)


def _has_null(v):
    if v is None:
        return True
    if isinstance(v, dict):
        return any(_has_null(x) for x in v.values())
    if isinstance(v, list):
        return any(_has_null(x) for x in v)
    return False


# ISO 639-2 codes whose language has an ISO 639-1 code (a common subset):
# a tag written with them isn't the shortest form section 9.4 asks for.
ISO639_2_WITH_1 = {
    "eng", "fre", "fra", "ger", "deu", "spa", "ita", "por", "rus", "jpn", "chi", "zho", "kor", "ara", "hin", "dut",
    "nld", "swe", "nor", "nob", "nno", "dan", "fin", "pol", "cze", "ces", "slo", "slk", "hun", "rum", "ron", "gre",
    "ell", "tur", "heb", "tha", "vie", "ind", "msa", "may", "ukr", "bul", "hrv", "srp", "slv", "est", "lav", "lit",
    "per", "fas", "cat", "baq", "eus", "glg", "ice", "isl", "gle", "wel", "cym", "tam", "tel", "ben", "urd",
}
