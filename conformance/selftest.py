#!/usr/bin/env python3
"""Checks the suite's own readers against vectors/v0-strict.json and
vectors/v0.json: keys, signatures, base64url, dates, JSON, addresses and
codes. Needs no server. Exit 0 when every case decides as the file says."""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from msfpconf import ed25519  # noqa: E402
from msfpconf.wire import (NotIJSON, answer_message, check_address, parse_code, parse_ijson, proof,  # noqa: E402
                           request_message, unb64u, b64u, Key, fingerprint, is_int)


def main():
    vec = os.path.join(HERE, "..", "vectors")
    strict = json.load(open(os.path.join(vec, "v0-strict.json")))
    bad = []

    def expect(group, name, want, got):
        if want != got:
            bad.append("%s / %s: expected %s, got %s" % (group, name, want, got))

    for c in strict["keys"]:
        k = unb64u(c["text"], 32)
        expect("keys", c["name"], c["valid"], k is not None and ed25519.valid_point(k))
    for c in strict["signatures"]:
        expect("signatures", c["name"], c["valid"],
               ed25519.verify_strict(unb64u(c["public"], 32), c["message"].encode(), unb64u(c["signature"], 64) or b""))
    for c in strict["base64url"]:
        size = 16 if "nonce" in c["name"] else 32 if "key" in c["name"] else None
        expect("base64url", c["name"], c["valid"], unb64u(c["text"], size) is not None)
    import re
    for c in strict["dates"]:
        t = c["text"]
        expect("dates", t, c["valid"], bool(re.fullmatch(r"[1-9][0-9]*", t)) and int(t) <= 2**53 - 1)
    for c in strict["integers"]:
        try:
            ok = is_int(parse_ijson(('{"n":%s}' % c["text"]).encode())["n"])
        except NotIJSON:
            ok = False
        expect("integers", c["text"], c["valid"], ok)
    for c in strict["json"]:
        raw = bytes.fromhex(c["hex"]) if "hex" in c else c["text"].encode("utf-8", "surrogatepass")
        try:
            parse_ijson(raw)
            ok = True
        except NotIJSON:
            ok = False
        expect("json", c["name"], c["valid"], ok)
    for c in strict["addresses"]:
        expect("addresses", c["text"], c["valid"], check_address(c["text"]) is None)
    for c in strict["codes"]:
        try:
            parse_code(c["text"])
            ok = True
        except ValueError:
            ok = False
        expect("codes", c["name"], c["valid"], ok)

    v0 = json.load(open(os.path.join(vec, "v0.json")))
    a = v0["keys"]["a"]
    k = Key(bytes.fromhex(a["seed"]))
    expect("v0", "key a", a["public"], k.text)
    expect("v0", "fingerprint a", a["fingerprint"], fingerprint(k.pub))

    if bad:
        print("\n".join(bad))
        print("%d case(s) wrong" % len(bad))
        return 1
    print("every case of v0-strict.json, and v0.json's key a, decide as the files say")
    return 0


if __name__ == "__main__":
    sys.exit(main())
