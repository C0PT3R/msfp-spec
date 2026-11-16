# Proposal 3: Key rotation and revocation

Status: Adopted whole (2026-11-16); open points still open.
Touches: sections 4, 6.4, 6.5, 7, 9.1, 9.2 and 14 of
[spec/v0.md](../spec/v0.md); adds two calls.

## Problem

A server is its Ed25519 key (section 4.1): "made once, on first start,
and kept". Peers store it as the pairing's identity (section 7.2).
Nothing in version 0 lets the key change. So:

- **Routine rotation is impossible.** Moving to a new machine, restoring
  from a backup made by another tool, or simply following a key-lifetime
  policy, all mean every peer must pair again by hand, with a new code
  and a new fingerprint call between operators.
- **Compromise has no answer.** If the seed leaks, the thief is the
  server toward every peer until each peer's operator ends the pairing.
  The real server can't even tell its peers. Section 14 says only "a
  peer's key, if stolen, can name any certificate; it can already do
  more".
- **What a peer stores is keyed on the key.** Overfin's `peers` table has
  `public_key BLOB NOT NULL UNIQUE`, and `forgotten_peers` stores the
  key's SHA-256. The plugin does the same (per its SPEC-GAPS.md, 7.4).
  Any later change of identity touches both.

Adding this later is harder than now: every pairing made before the
feature has no way to opt in to its protections (see "the next key"
below), and every implementation's storage assumes one key per peer.

## Proposal

### Terms

- **Current key**: the key a peer knows a server by now.
- **Next key commitment**: SHA-256 of a public key the server has made
  but not used yet, sent base64url (43 characters). A peer stores it and
  accepts a rotation only to that key, as long as the server isn't asking
  its operator.

### The rotation statement

A server that rotates from key O to key N makes this statement: five
lines joined by `\n`, no trailing `\n`, ASCII.

```
msfp-key-rotation-1
<O, base64url>
<N, base64url>
<the commitment to the key after N, base64url, or "-">
<date, Unix seconds, decimal>
```

It signs the statement with O (`oldSignature`) and with N
(`newSignature`). The second signature proves the server holds N, so
nobody can rotate a server to a key someone else holds.

### The `rotate` call

`POST /api/v1/federation/rotate`, signed with O (the request headers of
section 6), sent to every peer in any state.

Request:

| Field | Type | Required | Content |
|-------|------|----------|---------|
| `newKey` | string | yes | N |
| `nextCommitment` | string | no | the commitment to the key after N |
| `date` | integer | yes | the statement's date |
| `oldSignature` | string | yes | O's signature of the statement |
| `newSignature` | string | yes | N's signature of the statement |

What the receiver does:

1. It rebuilds the statement from the request (O from `Overfin-Key`) and
   checks both signatures, under the rules of proposal 1 for N. It
   checks that the date is within 5 minutes of its clock, and that N
   isn't a key it knows as another peer or has forgotten.
2. **If it holds a commitment for O's server, and SHA-256(N) matches
   it**, it makes N the current key at once.
3. **If it holds a commitment and N doesn't match**, it refuses the
   rotation (`409`, type `rotation-refused`), keeps O, and shows its
   operator a warning: someone holding O tried to move the pairing to
   another key.
4. **If it holds no commitment** (pairings from version 0), it keeps O,
   marks the rotation pending, and asks its operator to confirm N's
   fingerprint with the other operator, as in pairing (section 7.1,
   step 6). It answers `202` with `{"state":"pending"}`. Once its
   operator confirms, it makes N the current key.
5. When N becomes current, it stores `nextCommitment` as the new
   commitment (or none), keeps the statement and its two signatures in
   the peer's history, and answers `200` with `{"state":"rotated"}`.

The answer is signed with the receiver's own key, as any answer.

A `rotate` repeated with the same statement, after it took effect, is
answered `200` `rotated` again, so a server can retry safely.

### What each side does during the change

**The rotating server** keeps O until every peer has rotated, or until
30 days have passed, whichever comes first:

- toward a peer that hasn't answered `rotated`, it signs requests and
  answers with O, and sends `rotate` again at each contact (at least
  daily);
- toward a peer that answered `rotated`, it signs with N only;
- after 30 days, it deletes O. A peer still on O must pair again; its
  operator sees why.

**The receiving server**, after N became current, still accepts requests
signed with O for 10 minutes (requests already on the way), and checks
answers from that peer against N only.

A rotation changes nothing else: address, name, states, offers, wants,
limits, pins and catalogs stay.

### The next key commitment

- `pair` requests and `pair` answers gain an optional `nextCommitment`
  field. Each side stores the other's.
- A commitment is set only by `pair` or by a rotation. `hello` can't
  change it. Otherwise a thief holding the current key could replace the
  commitment, then rotate.
- For pairings made before this proposal, the first `hello` after both
  sides upgrade may carry `nextCommitment`, accepted only when none is
  stored. This is trust on first use, signed by the current key: weaker
  than a commitment from `pair`, and the operator's panel says so.
- A server keeps the seed of its next key apart from the current one.
  It should let its operator export it (as text to keep offline) and
  then delete it from the server. With the seed offline, a thief who
  copies the server's storage can't rotate.

### Revocation

`POST /api/v1/federation/revoke`, signed with the key being revoked.

The statement, signed as `signature` in the body, with `date`:

```
msfp-key-revocation-1
<the revoked key, base64url>
<date>
```

Anyone holding the key can send it, and gains nothing by it: a thief
could already misuse the pairing, and revoking only stops it.

What the receiver does:

- It marks the peer `suspended`: it answers no call from that key
  except `rotate`, and `hello`, which gets a signed `404` as for a
  forgotten key. Its own calls to that peer stop.
- It shows its operator a warning.
- A `rotate` from the suspended key to a key matching the stored
  commitment lifts the suspension and rotates. A `rotate` without a
  match is refused: after a compromise, only the committed key, or a new
  pairing, can restore trust.
- Its operator can end the pairing (section 7.4) at any time.

### What to do on compromise

The specification's security section gains this procedure:

1. If the next key's seed is safe (offline): the operator revokes the
   current key and rotates to the next key, in one action. Peers that
   hold the commitment follow automatically.
2. If it isn't, or no commitment exists: the operator revokes the key,
   then pairs again with each peer, with new codes and fingerprint
   calls. Revoking first stops the thief at once at every peer the
   server can reach.
3. In both cases, the operator makes a new next key and stores it
   offline.

### Storage

For each peer, besides what section 7.2 lists: the current key, the
commitment (or none), a pending rotation (or none), the previous key and
until when it is accepted, the history of rotation statements, and a
`suspended` flag. Ending a pairing (section 7.4) records every key in the
peer's history as forgotten, not just the current one.

## Alternatives considered

1. **Re-pair on every key change** (version 0). No cost in the protocol.
   Costs two operators a phone call per pairing per change, and leaves
   compromise without an answer.
2. **Rotation signed by the old key only, no commitment.** Simple. But a
   thief holding the key rotates every peer to the thief's key, and the
   real server is then locked out. The commitment is what makes rotation
   safe after a compromise.
3. **Always ask the receiving operator** (no automatic rotation).
   Safest, but a routine rotation then costs as much as a re-pairing.
   Kept only for pairings without a commitment.
4. **Long-lived identity key plus short-lived signing keys**, the
   identity key signing certificates for the others. Common in larger
   systems. More moving parts (expiry, a certificate format) than
   version 1 needs; the commitment gives most of the benefit.
5. **Pre-rotation with several keys committed** (as in KERI). More
   robust, more state. One next key is enough for manual pairing.

## Cost

**Specification.** About three pages: one new section after section 7,
two calls in section 9, a paragraph in section 14, the `suspended` state
in section 7.3, and test vectors for both statements.

**Overfin.** Moderate to large:

- `internal/store`: a migration splitting the peer's key into current
  and previous keys plus commitment, history and flags. `PeerByKey` must
  find a peer by either key while the previous one is accepted.
  `public_key UNIQUE` stays true of the current key.
- `internal/federation`: the two calls; a second seed (sealed like the
  first, `KeepFederationSeed`), its export, and the per-peer choice of
  signing key during the 30 days; the `Verifier` hears a previous key
  for 10 minutes.
- `internal/admin`: panel actions (rotate, revoke, export the next key)
  and warnings (pending, refused, suspended).
- `pair` and `hello`: the `nextCommitment` field.

**Plugin.** The same pieces, in its own storage and configuration page.
BouncyCastle signs and verifies the statements as any other message.

## Compatibility

- Every new field and call is optional. A version 0 peer answers
  `rotate` and `revoke` with an unsigned `404` (an unknown path), and
  ignores `nextCommitment`.
- A rotating server knows from `hello` (proposal 4) whether a peer
  supports rotation. Toward a peer that doesn't, it keeps O for that
  peer only, for as long as the pairing lasts, or its operator chooses
  to pair again. Holding O longer is safe if O isn't compromised.
- Existing pairings get a commitment by trust on first use, as above,
  or by pairing again.

## Open points

1. The overlap of 30 days: long enough for a peer that is off for a
   holiday; long enough also to keep a retired key around. A shorter
   default with an operator setting is possible.
2. Should a rotation statement also be accepted from an unknown key
   (N), carrying O's signature, so that a server that lost O after
   rotating can still catch up a peer? This needs care with section
   6.5's "who is heard" rule, which keeps strangers' nonces out.
3. Whether `suspended` should become `gone` after some time without a
   valid rotation.
4. How a server proves to its own operator that the exported next key
   matches the commitment it sent (showing the commitment's fingerprint
   next to the export is enough, probably).
