# MSFP version 1

**Draft.** Version 1 stands alone: a version 1 server speaks version 1
only. [Version 0](../v0.md) was a test draft ([history](#history)).

Version 1 is made of a core and five parts, each with its own version:
three that hold the shared mechanics (`catalog`, `playback`, `media`),
and two content parts (`video`, `music`), each optional, that say what
the titles are and how they play. This lets an implementation build the
parts at different times, and lets the parts change at different speeds:
the trust part (keys, signatures, pairing) rarely and carefully, the
media formats more often.

## The documents

| Document | Version | What it holds |
|----------|---------|---------------|
| [core.md](core.md) | core 1 | encodings and canonical forms, HTTPS, keys and fingerprints, the pairing code, signed requests and answers, pairing and its states, `pair`, `hello`, key rotation and revocation (`rotate`, `revoke`), address changes, versions and parts, the discovery document |
| [catalog.md](catalog.md) | `catalog` 1 | `libraries` and `titles`, opaque library IDs, the general rules of title keys |
| [playback.md](playback.md) | `playback` 1 | `play`, `progress`, `stop`, limits, what the owning server enforces |
| [media.md](media.md) | `media` 1 | what the stream URLs serve: HLS, the file; how long a ticket works |
| [video.md](video.md) | `video` 1 | films and series by TMDB: title keys and their identity rules (TMDB's numbering, several episodes in one copy, other identifiers), subtitles, PGS, WebVTT, skip markers, seek-bar previews |
| [music.md](music.md) | `music` 1 | artists, albums and tracks by MusicBrainz: keys, descriptions, cover art, audio-only playback |

Read the core first. Each part says what it needs from the core, and
refers to it by section.

## Glossary

Each document defines its own terms in full; this list is a summary, in
one place, with where each is defined.

| Term | Meaning | Defined in |
|------|---------|------------|
| Server | one installation of an implementation, with one address and one current key | [core 1](core.md#1-overview-and-terms) |
| Address | where a server's API answers: `https://host[:port]`, no path | [core 5.2](core.md#52-addresses) |
| Base path | the path of the federation calls, `/api/v1/federation/` unless the discovery document says otherwise | [core 11](core.md#11-the-discovery-document) |
| Peer | another server this one knows by its public key | [core 7.3](core.md#73-states) |
| Pairing | two operators making their servers peers, by hand | [core 7](core.md#7-pairing-step-by-step) |
| Pairing code | one line holding the maker's address, key, a one-time secret and an expiry | [core 5](core.md#5-the-pairing-code) |
| Fingerprint | a short form of a public key, which operators compare when pairing | [core 4.2](core.md#42-the-fingerprint) |
| Current key | the key a peer knows a server by now | [core 12](core.md#12-key-rotation-and-revocation) |
| Next key commitment | SHA-256 of a key made for a later rotation | [core 12.5](core.md#125-the-next-key-commitment) |
| A server that can't be called | one that connects out but can't be connected to, and says so with `inbound: false`; its peers never call it | [core 7.5](core.md#75-a-peer-that-cant-be-called) |
| Nonce | 16 random bytes that make each signed request unique | [core 6.5](core.md#65-nonces-replay-and-restarts) |
| Pin | SHA-256 of a certificate's public key, which a server names in `hello` | [core 3.2](core.md#32-https-certificates) |
| *Trusted*, *named* | a certificate a public authority vouches for; one the peer named by its pin | [core 3.2](core.md#32-https-certificates) |
| Part | a separately versioned set of calls and rules: `catalog`, `playback`, `media`, `video`, `music` | [core 10](core.md#10-versions-and-parts) |
| Content part | a part that names one kind of content's titles and says how they play: `video`, `music` | [core 10.1](core.md#101-the-parts) |
| Problem document | the JSON body of a refusal (RFC 9457), with `type`, `title`, `status` | [core 8.2](core.md#82-refusals) |
| Library | a set of titles a server may offer a peer, by an opaque ID | [catalog 2](catalog.md#2-libraries) |
| Offer, want | what one side shares; what the other takes of it | [catalog 1](catalog.md#1-terms) |
| Title key | the identity of a title: a film, series, season or episode from TMDB's IDs; an artist, album or track from MusicBrainz's | [catalog 4](catalog.md#4-title-keys), [video 4](video.md#4-title-keys), [music 2](music.md#2-title-keys) |
| Owning server | the server that holds a copy and streams it | [playback 1](playback.md#1-terms) |
| Viewer's server | the server whose person watches; the only one the person's browser talks to | [playback 1](playback.md#1-terms) |
| Copy, version | one file of a title; the ID the owning server gives it | [playback 1](playback.md#1-terms) |
| Playback | one stream the owning server runs for the viewer's server, with an ID and a ticket | [playback 6.1](playback.md#61-a-playbacks-states) |
| Ticket | the opaque credential in the media URLs, the only one | [media 1](media.md#1-the-urls) |
| Stream root | `<address><prefix>/api/v1/stream/`, under which a server's media is | [media 1](media.md#1-the-urls) |
| Stretch, part | 120 seconds of a subtitle track, fetched on its own | [video 6.2](video.md#62-what-is-fetched) |
| Sheet | a JPEG of seek-bar preview tiles | [video 5.5](video.md#55-seek-bar-previews) |

## Errors

Every status and problem `type` a federation call can answer, in every
part, is listed with its meaning and what the caller does in
[core section 8.2](core.md#82-refusals). The statuses of media fetches are
in [core section 8.4](core.md#84-media-answers). Limits and overload, and
how a caller retries, are in
[core section 8.3](core.md#83-limits-and-overload).

## Dependencies

- `catalog` needs only the core.
- `media` needs only the core.
- `playback` needs `catalog` (it plays title keys from `titles`) and
  `media` (its answers point at media URLs). The `limits` member of
  `libraries` belongs to `playback`.
- `video` and `music` each need `catalog`, `playback` and `media`.
  Every content part is optional: a server lists the ones it handles,
  and two servers share only titles of the content parts both list.

A part whose dependency is off between two servers is off too. For
example, a server that speaks `catalog` but not `media` can list its
libraries, but shares no titles: `video` and `music` are off with
`media`.

## Negotiation in hello

Each server announces, in every `hello` request and answer, the core
versions and the part versions it speaks
([core section 10](core.md#10-versions-and-parts)):

```json
{"state":"paired","core":[1],"parts":{"catalog":[1],"playback":[1],"media":[1],"video":[1],"music":[1]}}
```

- For the core and for each part, two servers use the highest version
  both list. No common version: that part is off between them.
- A `hello` without `core` leaves no common core: the sender doesn't
  speak MSFP 1. Without `parts`, the sender speaks no part.
- Each side keeps what the peer's latest signed `hello` listed.
- A caller makes no call of a part that is off, and shows its people
  nothing that needs it. A receiver answers such a call with a signed
  `404` of type `not-supported`, which doesn't mean "not paired".
- The core's version also shows in every signed message: core 1 uses the
  labels `msfp-1 …` and the headers `MSFP-*`. A later core will have its
  own, so a message signed under one core never verifies under another.

An optional discovery document, `GET /.well-known/msfp`, lets a server
see a peer's versions and base path before pairing. It is unsigned,
proves nothing, and is off by default
([core section 11](core.md#11-the-discovery-document)).

## Versioning

- The core and each part have their own version: a non-negative integer.
  Version 1 of each is the documents above.
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
  an existing version as errata, listed in that version's changes.

## History

Version 0 ([spec/v0.md](../v0.md)) was a test draft. Version 1
supersedes it, and doesn't work with it: no version 1 server speaks
version 0, and version 0 is not to be implemented. It stays in this
repository as history, with its vectors
([vectors/v0.json](../../vectors/v0.json) and
[vectors/v0-strict.json](../../vectors/v0-strict.json)), whose
canonical-form cases hold for core 1 too.

### What version 1 changes from version 0

- **Strict rules** (proposal 1): one rule set for Ed25519, base64url,
  integers, JSON (I-JSON), headers and addresses. Version 0 received the
  same rules as corrections; version 1 also refuses `null`.
- **Opaque IDs** (proposal 2): library and version IDs chosen by the
  owning server. Also a version 0 correction.
- **Key rotation and revocation** (proposal 3), in the core.
- **A core plus parts** (proposal 4), MSFP's own labels and headers, and
  the discovery document.
- **Title identity** (proposal 5), in `video`: TMDB's numbering, `e0`,
  `with` for several episodes in one copy, `ids` for IMDb and TVDB.
- **Every content type optional** (proposal 11): films and series in the
  part `video`, music in the part `music` (artists, albums and tracks by
  MusicBrainz ID, with their own descriptions; cover art from the Cover
  Art Archive; one audio playback per track).
- **The answer's media type is signed** (proposal 6), in the core. MSFP
  keeps its own signing scheme rather than HTTP Message Signatures
  (RFC 9421).
- **HTTPS only** (proposal 7).
- **Address changes** (proposal 8), in the core.
- **Servers that can't be called** (proposal 9, option 1), in the core:
  `inbound: false` in `pair` and `hello`, peers that stop calling, a
  `hello` on a schedule, rotation and revocation pulled in `hello`
  answers, and the address `https://msfp-<26>.invalid`.
- **The clarifications** (all 34), as in version 0's corrections.
- The seek-bar previews already in version 0, in `video`.
- **The review round of 2026-11-16**: which addresses a server connects
  to ([core section 3.3](core.md#33-connecting-to-peers), also a version 0
  correction); required rate limits and overload answers (core section
  8.3); logging (core section 14.1); one error reference (core section
  8.2); exact HLS, WebVTT and PGS rules and bounds on fetches
  ([media](media.md) sections 2 and 3, and [video](video.md) section 6
  for WebVTT and PGS); choosing the copy and tracks, and
  a playback's states ([playback](playback.md) sections 2.6 and 6).
- **The live interop of 2026-11-17**, as in version 0's corrections: no
  content codings (core sections 3, 6.3 and 6.6); answers' members of
  the wrong JSON type ([catalog](catalog.md) sections 2.2 and 3.3);
  `titles` without `libraries` (catalog section 3); a `hello`'s answer
  names the certificate served now (core section 3.2); limits behind a
  reverse proxy (core section 8.3); NAT64 and 6to4 addresses (core
  section 3.3).

The proposals and their decisions are in
[proposals/](../../proposals/README.md). Points the proposals left open
are listed in each document's open questions.

## Test vectors

[vectors/v1/](../../vectors/v1/) holds keys, a code, signed requests and
answers under the MSFP labels and headers, a rotation statement, a
revocation statement, a `hello` carrying `core`, `parts`,
`certificates` and `address`, and the `hello`s of a server that can't be
called, with a rotation and a revocation pulled in an answer
([core section 17](core.md#17-test-vectors)), the addresses of servers
that can't be called (`uncallableAddresses` in `strict.json`), the
destinations a server
refuses to connect to (`destinations` in `strict.json`), and WebVTT,
HLS and PGS cases with their verdicts (`media.json`, media section 3 and
video section 6), music keys and titles with what a caller keeps
(`music.json`, music sections 2 and 3), and video titles with what a
caller keeps (`video.json`, video section 3). They come from the
generator in [tools/vectors/](../../tools/vectors/), not from an
implementation.
