# Proposal 7: HTTPS only

Status: Adopted (2026-11-16); open points still open.
Touches: sections 3, 3.1, 5.2, 10, 14 and open question 4 of
[spec/history/test-draft.md](../spec/history/test-draft.md).

## Problem

Version 0 allows plain `http` (section 3). Over `http`, signatures keep
servers from being impersonated, but section 14 lists what is lost:

- an observer reads titles, names, and **tickets**, and "can fetch media
  with a ticket it read while the playback lives";
- an on-path attacker can **change media bytes**: media is not signed
  (open question 4);
- everything a peer's viewer watches, and when, is visible on the path.

Plain `http` was allowed because a server without a certificate from a
public authority had no other way to federate. Section 3.1 (HTTPS
certificates, added at commit `9b15c83`) removed that reason: a server's
key now vouches for its certificate through pins, so a self-signed
certificate works. What remains of `http` is the risk, plus a second code
path in every implementation (the plugin's SPEC-GAPS.md has a whole
section on 3.1 cases that exist only because `https` and `http` mix).

It is cheaper to drop `http` now. Every pairing stores its address with
its scheme, and the scheme is part of the code and the pair request.
Each `http` pairing made from now on is one more to migrate later.

## Proposal

1. **Addresses are `https` only.** In section 5.2 (or proposal 1's C6),
   `scheme = "https"`. A reader refuses a code whose address is `http`;
   a maker refuses a pair request whose `address` is `http`.
2. **Media is fetched over `https` only**, under the checks of section
   3.1 (*trusted* or *named*).
3. **A server without a public certificate** makes a self-signed one
   (or uses a private authority's) and names its pin in `hello`, as
   section 3.1 already describes. The specification adds a short
   recommendation: an Ed25519 or ECDSA P-256 key for the certificate,
   kept apart from the federation key; a lifetime of a year or less;
   the pin named in `hello` before the switch to a renewed certificate.
4. **Section 14** loses the "Plain HTTP" paragraph, and open question 4
   narrows to "media is protected by TLS only", which is then true in
   every case.
5. **Section 3.1's "any" check** stays, for `pair` and `hello`, so that
   pins can be learnt.

## Alternatives considered

1. **Keep `http`, with warnings** (version 0). No cost. Keeps tickets in
   the clear and media open to change, for people who may not read the
   warnings.
2. **Allow `http` only for private addresses** (RFC 1918, RFC 4193,
   loopback). Covers two servers on one home network. But "private"
   says nothing about who is on that network, and the rule needs a list
   of ranges every implementation must keep the same.
3. **Sign media** (an HMAC per segment, or signed HLS playlists with
   hashes). Fixes integrity over `http`, not confidentiality, and costs
   far more than TLS: every media response would need it.
4. **Allow `http` behind an operator setting** marked unsafe. Keeps both
   code paths in every implementation.

## Cost

**Specification.** Small: a word in section 5.2, a sentence in section
10, a paragraph removed from section 14, a short recommendation in 3.1.
Test vectors: key "b"'s address `http://192.0.2.10:8096` becomes
`https://192.0.2.10:8096`, so the vectors of sections 15.2 to 15.5
change (the proof and the signed messages cover the address and host).
That can wait for the next vector revision.

**Overfin.**

- `checkAddress`: refuse `http`. Trivial.
- Serving TLS where there is no reverse proxy: Overfin's gateway already
  listens with TLS (`cmd/overfin-gateway`), so the gateway deployment is
  covered. A single Overfin without a proxy and without a public
  certificate needs a self-signed certificate made and served by
  Overfin, and its pin named (the pin reading of section 3.1 already
  works on any certificate). This is the main cost: certificate
  generation, renewal, and a TLS listener option.
- Existing `http` pairings: see Compatibility.

**Plugin.** Refuse `http` addresses. Jellyfin serves HTTPS itself when
its operator gives it a certificate; a self-signed one works with
pins. The plugin's own-certificate reading already exists. Its
`http`-only cases in SPEC-GAPS.md (pins over `http`) disappear.

## Compatibility

- Toward version 0 peers on `http`: an upgraded server keeps existing
  `http` pairings working for a transition period, but makes no new
  ones. Its panel shows them as "insecure, move to HTTPS".
- Moving a pairing from `http` to `https` is an address change.
  Proposal 8 gives a signed way to do it without pairing again. Without
  proposal 8, both operators pair again.
- After the transition (one release, or a date the owner picks),
  `http` pairings stop.

## Open points

1. The length of the transition, and whether the cut-off is a version
   (core 1, proposal 4) or a date.
2. Whether the specification should go further and say how a server
   makes its self-signed certificate (key type, names), or leave it to
   implementations.
3. Local testing: implementations will want `http` in development. That
   can stay an implementation's test switch, outside the protocol.
