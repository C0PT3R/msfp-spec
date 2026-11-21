# Proposal 4: A core plus separately versioned parts

Status: Adopted (2026-11-16), with the rename to MSFP labels and headers in core 1 (open point 1); other open points still open.
Touches: sections 3, 9 and 13 of [spec/history/test-draft.md](../spec/history/test-draft.md); adds a
discovery document.

## Problem

Version 0 is one block. Section 13 recommends a single `protocol`
integer in `hello`, the highest version a server speaks. Three things in
the evidence say one number is too coarse:

- **Implementations build parts at different times.** The plugin speaks
  pairing, `hello`, `libraries` and `titles`, but no `play` yet
  (SPEC-GAPS.md, "9.5: play, not built" and "12: limits before play
  exists"). It sends no `limits` "rather than announce caps it doesn't
  enforce". Under version 0 a peer can't tell that the plugin doesn't
  play: it would offer the plugin's titles to its people, and every
  `play` would fail with a signed `404` that reads as "not paired"
  (section 8.2), making Overfin send a `hello` each time (section 9.2).
- **Parts change at different speeds.** The media part is moving now:
  seek-bar previews (`trickplay`, being added to `play` answers), PGS
  stretches, HLS rules. The trust part (keys, signatures, pairing) should
  change rarely and carefully. With one number, adding a media format
  forces a whole-protocol version, and a change to signatures has to wait
  for, or drag along, everything else.
- **Names.** The wire carries `Overfin-*` headers and
  `overfin-federation-1` labels for a protocol named MSFP, meant for
  other servers too. Section 13 says a change to signing must change the
  labels. If the labels ever change, it is cheapest to do it once, with
  the first core version.

Also, version 0 has no discovery: a server hosted under a path "can't
federate in version 0" (section 5.2), since the API's place is fixed at
`/api/v1/federation/`.

## Proposal

### The core and the parts

| Name | What it holds | Calls and sections |
|------|---------------|--------------------|
| core | encodings, transport, keys, the code, signatures, pairing, states, refusals | sections 2 to 8; `pair`, `hello`; `rotate` and `revoke` (proposal 3) |
| `catalog` | libraries, titles, title keys | `libraries`, `titles`; section 11 |
| `playback` | starting, keeping and stopping a playback; limits | `play`, `progress`, `stop`; section 12 |
| `media` | what the stream URLs serve | section 10: HLS, file, subtitles, PGS, previews |

Dependencies: `playback` needs `catalog` (it plays title keys from
`titles`) and `media` (its answers point at media URLs). `catalog` needs
nothing but the core. The `limits` member of `libraries` belongs to
`playback`: a server sends it only when it speaks `playback`.

Each has its own version, a positive integer. Version 0 of everything is
spec/history/test-draft.md as it stands.

### Announcing versions in hello

`hello` requests and answers gain two optional members:

| Field | Type | Content |
|-------|------|---------|
| `core` | array of integer | the core versions the sender speaks, at most 8 |
| `parts` | object | for each part it speaks, the array of versions it speaks, at most 8 each |

Example:

```json
{"state":"paired","core":[1],"parts":{"catalog":[1],"playback":[1],"media":[1,2]}}
```

Rules:

- **Choice.** For the core and for each part, the version used between
  two servers is the highest one both list. No common version: that part
  is off between them (the core: see below).
- **Absent means version 0.** A `hello` without `core` means `[0]`.
  Without `parts`, it means `catalog`, `playback` and `media` at `[0]`.
  So a version 0 peer is understood as speaking all of version 0.
- **Unknown names** in `parts` are ignored. Part names are lowercase
  ASCII letters and `-`, at most 32 characters.
- **Dependencies.** A part whose dependency is off is off too.
- **Memory.** Each side stores, per peer, what the peer's latest signed
  `hello` (request or answer) listed, and recomputes the choices. Before
  any `hello`, it assumes version 0.
- **A part that is off.** The caller must not make that part's calls to
  the peer, and must not show its people anything that needs them (for
  example, it doesn't offer a peer's titles for playing when `playback`
  is off). A receiver answers a call of a part it doesn't speak with a
  signed `404` problem of type `not-supported`. A caller must not take
  that `404` as "gone" or "not paired".

### The core's version

The core's version is visible in every signed message, through the
labels. Core version 1 uses these labels and headers:

| Version 0 | Core version 1 |
|-----------|----------------|
| `overfin-federation-1 request` | `msfp-1 request` |
| `overfin-federation-1 response` | `msfp-1 response` |
| `overfin-federation-1 pairing` | `msfp-1 pairing` |
| `Overfin-Key`, `-Date`, `-Nonce`, `-Signature` | `MSFP-Key`, `MSFP-Date`, `MSFP-Nonce`, `MSFP-Signature` |
| code prefix `overfin-pair-1.` | code prefix `msfp-pair-1.` |

So a request signed under one core version never verifies under another.
A server that speaks cores 0 and 1:

- reads both code prefixes; makes `msfp-pair-1.` codes, unless its
  operator asks for a version 0 code;
- accepts requests in either header set;
- signs toward a peer with the core version chosen for it;
- answers in the core version of the request.

A `hello` is always sent in the highest core the sender believes the
peer speaks; on an unsigned `404`, it tries the next lower one once.

### The discovery document

`GET /.well-known/msfp` (RFC 8615) may return, `application/json`:

```json
{"core":[1],"parts":{"catalog":[1],"playback":[1],"media":[1]},"base":"/srv/media/api/v1/federation/"}
```

- `base`: where the federation calls are, as an absolute path. Absent:
  `/api/v1/federation/`. Media URLs keep coming from `play` answers.
- The document is not signed and proves nothing. Every value in it is
  checked again in the first signed `hello`. It exists to let a server
  find a peer's API and see, before pairing, whether they have a version
  in common.
- It is optional, and **off by default**: a server that serves it tells
  anyone that it federates, which section 14 ("Probing") avoids.
- With discovery, a server hosted under a path can federate: the address
  stays `scheme://host[:port]` (section 5.2), and `base` gives the path.
  Section 6.2's `<target>` is the full path as sent.

Register `msfp` in IANA's Well-Known URIs registry when the
specification reaches a stable version.

### Section 13

Replace the recommendation of section 13 with the rules above, and
state the policy:

- a part's new version is needed when an existing member's meaning
  changes, or a receiver of the older version would misread a message;
- adding an optional member doesn't need a new version, as long as its
  absence keeps the old behaviour;
- a change to keys, signatures, the code or pairing is a new core
  version, with new labels.

## Alternatives considered

1. **One integer** (section 13's recommendation). Simplest. Doesn't let
   the plugin say "no playback", and ties media changes to signature
   changes.
2. **Feature flags instead of versions** (`"features":["trickplay"]`).
   Fine-grained, but flags pile up and combine in ways nobody tests. A
   version per part, with optional members inside, is a middle ground.
3. **Version in the path** (`/api/v2/federation/`). Visible in logs and
   easy to route. But it says nothing per part, and the path is already
   signed, so it adds no safety over labels.
4. **Keep the `Overfin-` names.** No cost now. MSFP then carries one
   product's name forever, and a later rename costs more.
5. **Discovery required, always served.** Simpler for future open
   federation; costs the probing property for everyone. Rejected for
   manual pairing.

## Cost

**Specification.** Section 13 rewritten; section 9.2 gains two members;
the contents split into a core document and three part sections (they
can stay in one file); a short section for the discovery document; test
vectors for core 1's labels.

**Overfin.**

- `hello`: send and store `core` and `parts`; compute choices per peer.
  About 100 lines, plus one column or table in `internal/store`.
- Gating: `TheirLibraries`, `SyncTitles` and `peerplay.go` check the
  peer's parts before calling; the site hides playing for peers without
  `playback`.
- Core 1: `sign.go` takes the label and header set as a parameter;
  `code.go` reads both prefixes. About 60 lines.
- `not-supported`: one more problem type, and `forgotUs` must ignore it.
- Discovery: one handler behind a setting, off by default; `base` used
  when building federation URLs. Overfin itself always serves at the
  root.

**Plugin.** Announce `parts` without `playback` (and without `media`)
until `play` is built: this fixes its current position at once. Core 1
labels and headers. Discovery is natural for it: on Jellyfin, plugin
routes may live under a base URL.

## Compatibility

- A version 0 peer sends no `core` or `parts`: it is treated as
  speaking version 0 of everything, as today. Nothing changes for it.
- A version 0 peer ignores the new members (Overfin's decoder ignores
  unknown fields; the plugin's too).
- Core 1 is opt-in per peer, through `hello`. A pairing starts in the
  core of the code used. Existing pairings move to core 1 when both
  sides list it.
- A server keeps core 0 support until its operator has no core 0 peer
  left; the panel can show which peers are still on it.

## Open points

1. Whether to rename the labels and headers at all (the table above).
   It is the one breaking piece; everything else is additive. If it is
   not wanted, core version 1 could keep the version 0 names and change
   only the label's number.
2. Whether `media` should be a separate part, or a sub-version of
   `playback`. Separate is proposed, because the media formats are where
   most change is expected.
3. Whether `hello` is the only place versions travel, or whether `pair`
   requests and answers should carry them too, so that a new pairing
   knows them before the first `hello`.
4. The 8-entry caps are arbitrary limits against abuse.
