# MSFP version 1

**Draft. Nothing implements version 1 yet.** [Version 0](../v0.md) is what
Overfin and the Jellyfin plugin speak today, and stays the compatibility
baseline: a version 1 server speaks version 0 to a peer that speaks only
version 0 ([core section 16](core.md#16-coexisting-with-version-0)).

Version 1 is made of a core and three parts, each with its own version.
This lets an implementation build the parts at different times, and lets
the parts change at different speeds: the trust part (keys, signatures,
pairing) rarely and carefully, the media formats more often.

## The documents

| Document | Version | What it holds |
|----------|---------|---------------|
| [core.md](core.md) | core 1 | encodings and canonical forms, HTTPS, keys and fingerprints, the pairing code, signed requests and answers, pairing and its states, `pair`, `hello`, key rotation and revocation (`rotate`, `revoke`), address changes, versions and parts, the discovery document, coexisting with version 0 |
| [catalog.md](catalog.md) | `catalog` 1 | `libraries` and `titles`, opaque library IDs, title keys and their identity rules (TMDB's numbering, several episodes in one copy, other identifiers) |
| [playback.md](playback.md) | `playback` 1 | `play`, `progress`, `stop`, limits, seek-bar previews, what the owning server enforces |
| [media.md](media.md) | `media` 1 | what the stream URLs serve: HLS, the file, subtitles, PGS, preview sheets; how long a ticket works |

Read the core first. Each part says what it needs from the core, and
refers to it by section.

## Dependencies

- `catalog` needs only the core.
- `media` needs only the core.
- `playback` needs `catalog` (it plays title keys from `titles`) and
  `media` (its answers point at media URLs). The `limits` member of
  `libraries` belongs to `playback`.

A part whose dependency is off between two servers is off too. For
example, a server that speaks `catalog` but not `media` can share its
catalog, but nobody plays from it.

## Negotiation in hello

Each server announces, in every `hello` request and answer, the core
versions and the part versions it speaks
([core section 10](core.md#10-versions-and-parts)):

```json
{"state":"paired","core":[0,1],"parts":{"catalog":[1],"playback":[1],"media":[1]}}
```

- For the core and for each part, two servers use the highest version
  both list. No common version: that part is off between them.
- A `hello` without `core` means core 0; without `parts`, it means
  `catalog`, `playback` and `media` at version 0. So a version 0 server,
  which sends neither, is understood as speaking all of version 0.
- Each side keeps what the peer's latest signed `hello` listed.
- A caller makes no call of a part that is off, and shows its people
  nothing that needs it. A receiver answers such a call with a signed
  `404` of type `not-supported`, which doesn't mean "not paired".
- The core's version also shows in every signed message: core 1 uses the
  labels `msfp-1 …` and the headers `MSFP-*`; core 0 uses
  `overfin-federation-1 …` and `Overfin-*`. A message signed under one
  core never verifies under another.

An optional discovery document, `GET /.well-known/msfp`, lets a server
see a peer's versions and base path before pairing. It is unsigned,
proves nothing, and is off by default
([core section 11](core.md#11-the-discovery-document)).

## Versioning

- The core and each part have their own version: a non-negative integer.
  Version 0 of each is [spec/v0.md](../v0.md), as corrected on
  2026-11-16. Version 1 of each is the documents above.
- **A new version of a part** is needed when an existing member's meaning
  changes, or when a receiver of the older version would misread a
  message.
- **Adding an optional member** doesn't need a new version, as long as
  its absence keeps the old behaviour. Receivers ignore unknown members
  ([core section 2.3](core.md#23-json)), so this is safe.
- **A change to keys, signatures, the code or pairing** is a new core
  version, with new labels and headers, and a new code prefix, so that a
  server of the older core refuses the new messages instead of misreading
  them.
- A server lists in `hello` every version it speaks, and keeps an older
  one for as long as it has a peer that needs it.
- Corrections that change nothing an honest sender writes may be made to
  an existing version as errata, listed in that version's changes. That
  is how version 0 was corrected.

## What version 1 changes from version 0

- **Strict rules** (proposal 1): one rule set for Ed25519, base64url,
  integers, JSON (I-JSON), headers and addresses. Version 0 received the
  same rules as corrections; version 1 also refuses `null`.
- **Opaque IDs** (proposal 2): library and version IDs chosen by the
  owning server. Also a version 0 correction.
- **Key rotation and revocation** (proposal 3), in the core.
- **A core plus parts** (proposal 4), MSFP's own labels and headers, and
  the discovery document.
- **Title identity** (proposal 5), in `catalog`: TMDB's numbering, `e0`,
  `with` for several episodes in one copy, `ids` for IMDb and TVDB.
- **The answer's media type is signed** (proposal 6), in the core. MSFP
  keeps its own signing scheme rather than HTTP Message Signatures
  (RFC 9421).
- **HTTPS only** (proposal 7).
- **Address changes** (proposal 8), in the core.
- **The clarifications** (all 34), as in version 0's corrections.
- The seek-bar previews already in version 0, in `playback` and `media`.

The proposals and their decisions are in
[proposals/](../../proposals/README.md). Points the proposals left open
are listed in each document's open questions.

## Test vectors

[vectors/v1/](../../vectors/v1/) holds keys, a code, signed requests and
answers under the MSFP labels and headers, a rotation statement, a
revocation statement, and a `hello` carrying `core`, `parts`,
`certificates` and `address`
([core section 17](core.md#17-test-vectors)). They come from the
generator in [tools/vectors/](../../tools/vectors/), not from an
implementation.
