# The engine API

**Informative, not part of the protocol.** What the host calls. Notation
and conventions: [README sections 3 and 4](README.md#3-notation). The
host's side: [host.md](host.md).

## Contents

1. [Construction, configuration and mounting](#1-construction-configuration-and-mounting)
2. [The operator](#2-the-operator)
3. [Viewers](#3-viewers)
4. [Events](#4-events)
5. [Background work](#5-background-work)
6. [Errors](#6-errors)
7. [Data objects](#7-data-objects)
8. [An example](#8-an-example)

## 1. Construction, configuration and mounting

### 1.1 Opening the engine

```
Open(config: Config) -> Engine
    errors: InvalidAddress, PlainHTTP, Sealed
```

- Reads the server record; on the very first start, makes the key, the
  next key, the IDs secret and (when needed) the address of a server
  that can't be called, and stores them.
- Compares `config.address` with the address noted last: a different
  one starts a move ([core 13.1](../spec/v1/core.md#131-the-server-that-moves)).
- Go: `msfp.Open(ctx, cfg) (*Engine, error)`. C#:
  `static Task<MsfpEngine> MsfpEngine.OpenAsync(MsfpOptions options, CancellationToken ct)`.
- One engine per server, for the life of the process. It is safe to use
  from many goroutines or tasks at once.

### 1.2 Config

| Field | Default | Content |
|-------|---------|---------|
| `address` | required | this server's address, `https://host[:port]` ([core 5.2](../spec/v1/core.md#52-addresses)); ignored while the server can't be called |
| `name` | required | `() -> String`, read at each `pair` and `hello`: the name peers show. A callback, since a host's branding may change it |
| `prefix` | `""` | where the host mounts the routes, before `/api/v1/federation/` and `/api/v1/stream/` ([core 11](../spec/v1/core.md#11-the-discovery-document)) |
| `parts` | what the hooks allow | the content parts served: `video`, `music`. A part the catalog never lists may still be read from peers |
| `discovery` | off | serve `/.well-known/msfp` |
| `pins` | read from the own address | this server's certificate pins; when set, nothing is read ([core 3.2](../spec/v1/core.md#32-https-certificates)) |
| `allowLoopback` | off | allow peers on this machine ([core 3.3](../spec/v1/core.md#33-connecting-to-peers)) |
| `plainHTTPForTests` | off | accept and make `http` pairings; for a host's own tests only ([core 3.1](../spec/v1/core.md#31-local-testing)). The engine logs a warning at each start with it on |
| `limits` | spec's suggested numbers | `CallLimits`, [section 7](#7-data-objects) |
| `newPairing` | 2 streams, 1 transcode, no bitrate cap | the limits a new pairing starts with |
| `maxBitrateKbps` | 0 (none) | this server's own cap on what peers play |
| `longestPlayback` | 24 hours | a playback longer than this ends |
| `syncEvery` | 30 minutes | how often peers' catalogs are read |
| `store`, `sealer` | required | [host.md](host.md) |
| `catalog`, `playback`, `media` | absent | absent: nothing is offered, nothing plays here |
| `clock`, `random`, `dialer`, `notifier`, `sheetEncoder`, `logger` | the system's, the engine's own | [host.md](host.md) |

### 1.3 Changing settings

The engine lives as long as the process. Settings that an operator
changes go through it, never by building a new one (Overfin rebuilds its
service today, and shares its state across rebuilds by hand):

| Method | Content | Spec |
|--------|---------|------|
| `SetAddress(address: String)` | this server's address changed: peers are told, the former one is still heard for 30 days | [core 13.1](../spec/v1/core.md#131-the-server-that-moves) |
| `SetUncallable(on: Bool)` | "this server can't be called", on or off; stored; the address switches to or from `https://msfp-<26>.invalid` | [core 7.5](../spec/v1/core.md#75-a-peer-that-cant-be-called) |
| `SetDiscovery(on: Bool)`, `SetPins(pins: List<String>?)` | | [core 11](../spec/v1/core.md#11-the-discovery-document), [core 3.2](../spec/v1/core.md#32-https-certificates) |

### 1.4 HTTP handlers

Spec: [core 6](../spec/v1/core.md#6-signing-requests-and-answers),
[core 8](../spec/v1/core.md#8-common-rules-for-every-call),
[media 2](../spec/v1/media.md#2-requests).

| Handler | Mounted at | Serves |
|---------|------------|--------|
| `FederationHandler()` | `<prefix>/api/v1/federation/` | `pair`, `hello`, `rotate`, `revoke`, `libraries`, `titles`, `play`, `progress`, `stop`; anything else under it is the plain `404` |
| `StreamHandler(fallback)` | `<prefix>/api/v1/stream/` | peers' tickets; any ticket the engine doesn't know goes to `fallback` (the host's own people's tickets), or the plain `404` when there is none |
| `DiscoveryHandler()` | `/.well-known/msfp` | the document when on; otherwise exactly what the host answers for a path that doesn't exist (it passes the host's not-found handler) |

The handlers do everything: limits by network address before the
signature, the signature, nonces, limits per peer and in all, the body
cap, the call, a signed answer or refusal, crashes as signed `500`s.

**What the host must do around them:**

- Pass the **client address**, as its trusted proxies give it
  ([core 8.3](../spec/v1/core.md#83-limits-and-overload), "behind a
  reverse proxy"). Go: `msfp.WithClient(r, addr)` on the request, or a
  `Config.clientAddress(r) -> IP` callback; C#: the neutral request's
  `Client`.
- Pass the **raw target** (path and query exactly as sent) and the
  **Host** header.
- Send the answer's bytes **unchanged**: no compression, no added
  content coding, no rewriting. The plugin fights Jellyfin's
  compression for this today.
- Put no authentication in front of these routes: the caller is a
  server, proven by its signature.

**The neutral form**, for hosts whose router isn't Go's `net/http` or
ASP.NET Core:

```
HandleFederation(req: MsfpRequest) -> MsfpResponse
HandleStream(req: MsfpRequest, out: ResponseSink) -> Bool     (false: not a peer's ticket)
```

`MsfpRequest`: `method`, `rawTarget`, `host`, `headers` (as received),
`body` (read at most 64 KiB plus one byte, so the engine sees it's
over), `client` (an IP). `MsfpResponse`: `status`, `headers`, `body`.

C#: `Msfp.AspNetCore` maps them to endpoints
(`app.MapMsfp(engine)`), and gives `MsfpRequest.FromAsync(HttpContext)`
for a host that must use controllers (Jellyfin's plugins). Go: the
handlers are `http.Handler`s; the neutral form is there for tests.

## 2. The operator

### 2.1 Actions

Each action is the operator's, and goes at once: a call it makes to a
peer isn't held by the back-off of background calls, only by a peer's
signed `retryAfter` ([core 8.3](../spec/v1/core.md#83-limits-and-overload)).

**Pairing.** Spec: [core 5](../spec/v1/core.md#5-the-pairing-code),
[core 7](../spec/v1/core.md#7-pairing-step-by-step).

| Method | Result | Errors |
|--------|--------|--------|
| `MakeCode(note: String)` | `(code: String, view: CodeView)`: the code's text, shown once | `NoCodes` (this server can't be called) |
| `Codes()` | `List<CodeView>`: live codes, without their text | |
| `DeleteCode(id: String)` | | `NotFound` |
| `ReadCode(text: String)` | `CodePreview`: address, fingerprint, expiry, to show before redeeming | `CodeInvalid`, `CodeExpired`, `OwnCode`, `AlreadyPeer`, `PlainHTTP` |
| `RedeemCode(text: String)` | `PeerView`, in state `theirs` | `CodeInvalid`, `CodeExpired`, `OwnCode`, `AlreadyPeer`, `PlainHTTP`, `RefusedDestination`, `Unreachable`, `CodeRefused` |
| `Accept(peer: PeerID)` | `PeerView`, `paired` | `NotFound`, `NotWaiting` |
| `Check(peer: PeerID)` | `PeerView`: a `hello` now, its answer applied | `NotFound`, `Uncallable`, `Unreachable`, `Unknown` |
| `End(peer: PeerID)` | ends the pairing, or refuses a waiting one; in any state, suspended included | `NotFound` |
| `PanelOpen()` | **sync**: the panel is listing peers now; each peer in `theirs` gets a `hello`, at most one every 20 seconds (Overfin's `CheckSoon`, called each time its panel lists peers) | |

**Sharing.** Spec: [catalog 1](../spec/v1/catalog.md#1-terms),
[catalog 2](../spec/v1/catalog.md#2-libraries),
[playback 5](../spec/v1/playback.md#5-limits).

| Method | Result | Errors |
|--------|--------|--------|
| `SetOffers(peer: PeerID, libraries: List<String>)` | the host libraries offered; playbacks from libraries no longer offered end at once | `NotFound`, `NotPaired` |
| `TheirLibraries(peer: PeerID)` | `List<WantedLibrary>`: a `libraries` call now, with what is wanted marked | `NotPaired`, `Uncallable`, `Suspended`, `NotSupported`, `Unreachable` |
| `SetWants(peer: PeerID, libraries: List<String>)` | public IDs of the peer's libraries; a reading starts at once | `NotFound`, `NotPaired` |
| `SetLimits(peer: PeerID, limits: Limits)` | what the peer may use here at once | `NotFound`, `InvalidLimits` |
| `ReadNow(peer: PeerID)` | a catalog reading now, waited for: how many titles kept | `NotPaired`, `Uncallable`, `NotSupported`, `Unreachable`, `BackingOff` |

**Keys.** Spec: [core 12](../spec/v1/core.md#12-key-rotation-and-revocation).

| Method | Result | Errors |
|--------|--------|--------|
| `NextKey()` | `(fingerprint: String, onServer: Bool)`: the committed key's fingerprint, and whether its seed is still here | |
| `ExportNextKey()` | `(text: String, fingerprint: String)`, to keep offline | `NoNextKey` |
| `DeleteNextKey()` | the seed leaves the server; its commitment stays | `NoNextKey` |
| `Rotate(nextKey: String?)` | moves to the next key (the text given, or the seed on the server); peers are told | `NoNextKey`, `NotNextKey`, `RotationUnderWay` |
| `KeyStolen(nextKey: String?, withoutNext: Bool)` | `rotated: Bool`: revokes the current key and, unless `withoutNext`, rotates to the next one in the same action ([core 12.7](../spec/v1/core.md#127-what-to-do-on-compromise)) | `NoNextKey`, `NotNextKey` |
| `ConfirmRotation(peer: PeerID)` | `PeerView`: the peer's pending new key becomes its key, after the operators compared fingerprints | `NotFound`, `NoPending`, `KeyTaken` |
| `DismissRefused(peer: PeerID)` | clears the warning of a refused rotation | `NotFound` |

**Playbacks here.**

| Method | Result | Errors |
|--------|--------|--------|
| `StopPlayback(id: String, reason: EndReason)` | the host ends a peer's playback from its side, and says why ([playback 6.3](../spec/v1/playback.md#63-how-a-playback-ends)): `operator` when its operator stops it, `expired` or `tooLong` when its own idle or time rules end it, `notOffered` when the copy is no longer shared; none is `operator` | `NotFound`, `InvalidReason` |

### 2.2 Queries

Each returns a copy the host may keep. They read storage, so they are
async, but never call a peer.

| Method | Result |
|--------|--------|
| `Server()` | `ServerView`: this server's fingerprint, address, former address and move (peers moved, total), uncallable, the next key (fingerprint, on server), a rotation under way (since, peers not moved), parts served |
| `Peers()` | `List<PeerView>`, every state |
| `Peer(id: PeerID)` | `PeerView` (`NotFound`) |
| `Offers(peer: PeerID)` | `List<Library>`: the host's libraries, offered ones marked |
| `Wants(peer: PeerID)` | `List<WantedLibrary>`, from the last reading, `gone` marked |
| `Playbacks()` | `List<PlaybackView>`: peers' playbacks here, live: peer, title key, method, since, state |

The host reads peers' titles from its own storage (host.md section 1),
for counts, its menus and its title pages.

## 3. Viewers

The viewer's side: this server's people play a peer's title. The host
decides who may (accounts, profiles) and serves its own browser route;
the engine talks to the peer and checks everything it relays.

### 3.1 Playing

Spec: [playback 2](../spec/v1/playback.md#2-play),
[video 5](../spec/v1/video.md#5-playing-a-film-or-an-episode),
[core 8.2](../spec/v1/core.md#82-refusals).

```
Play(peer: PeerID, req: PlayRequest) -> RemotePlayback
    errors: NotPaired, Uncallable, Suspended, NotSupported,
            StreamLimitReached, ServerBusy, BackingOff, NotPlayable, Unreachable
```

`PlayRequest`:

| Field | Content |
|-------|---------|
| `title` | the key, as the peer listed it |
| `capabilities` | what the viewer's device plays, as the host knows it; the engine coarsens it ([playback 2.1](../spec/v1/playback.md#21-the-request)) |
| `startMs`, `maxBitrateKbps` | the engine rounds the bitrate as the spec says |
| `audioLanguage`, `audioTrack`, `subtitleLanguage`, `subtitleTrack`, `versionId` | the viewer's wishes; IDs only from a former answer |
| `replaces` | a `RemotePlayback` ID of the same viewer to stop first; the engine waits up to 5 seconds for its `stop` ([playback 2.3](../spec/v1/playback.md#23-the-answer)) |

- The engine refuses before calling when the part is off, the peer isn't
  usable, or the peer's last `limits` say 0 streams.
- `RemotePlayback`: the engine's own `id` for it (not the peer's), and
  the answer cleaned: `method`, `positionMs`, `durationMs`, `versions`,
  `versionId`, `audioTracks`, `audioTrack`, `subtitleTracks`,
  `subtitleTrack`, `forcedTracks`, `forcedTrack`, `segments`, `info`,
  `protocol`, and `trickplay` (layout and sheet count; dropped when out
  of bounds, or without a sheet encoder in C#).
- URLs are never in it. The host builds its own (its route, its ticket
  for the browser) and asks the engine for each piece by `MediaPath`
  (below).
- Refusals, as the viewer is told them
  ([playback 2.5](../spec/v1/playback.md#25-refusals)):
  `StreamLimitReached`, `ServerBusy` and `BackingOff` mean "busy now";
  `NotPlayable` and every other refusal mean "not playable".
- When the answer breaks a "must", the engine sends `stop` for its ID and
  fails with `NotPlayable`.
- The engine keeps the playback as a leftover until it is stopped, so
  that after a restart it tells the peer it's over.

```
Progress(id: String, positionMs: Int, paused: Bool)              sync
Stop(id: String, positionMs: Int)
```

- `Progress` notes where the viewer is. The engine sends `progress` at
  the first report after the start, at once on a pause or a resume, and
  otherwise every 45 seconds, never more often, while the host reports
  ([playback 3](../spec/v1/playback.md#3-progress)): `Run` sends the
  latest position when 45 seconds have passed since the last one and the
  host reported since. Once the host stops reporting, nothing more is
  sent. It returns at once.
- A `410` from the peer, or the pairing ending, ends the playback: the
  event `RemotePlaybackEnded`, and further fetches fail `NotFound`.
- `Stop` sends `stop`, retried a few times when there's no answer, and
  forgets the playback.

### 3.2 Relaying media

Spec: [media 2](../spec/v1/media.md#2-requests),
[media 3](../spec/v1/media.md#3-what-is-fetched),
[video 6](../spec/v1/video.md#6-media).

```
Fetch(id: String, path: MediaPath, rng: String?, out: ResponseSink)
    errors: NotFound, RangeNotSatisfiable, ServerBusy
```

- `path`: the same `MediaPath` as on the owning side. The host's browser
  route maps its own URL to it: a playlist's bare name stays the same
  name, so playlists are served without rewriting.
- `rng`: the viewer's `Range` header as received. Malformed:
  `RangeNotSatisfiable`, and nothing is fetched.
- The engine fetches from the peer's stream root, with the playback's
  ticket, over a connection that needs a *trusted* or *named*
  certificate, a `hello` and one retry when the certificate is refused,
  and checks: the status, `Content-Range` against the range asked for,
  `Content-Length`, the size bounds, the time bounds, playlists (steps 1
  to 8, tags outside the subset dropped), WebVTT rebuilt, PGS checked
  whole, sheets checked and re-encoded. It sets `Content-Type` itself.
- What fails is `NotFound` to the viewer; the peer's `503` is
  `ServerBusy`. The peer's body or headers never pass with a failure.
- The fetches at once per playback and per peer, and the small reads
  across the server, are bounded; over them, `ServerBusy` after a
  bounded wait.
- A fetch is cut when its playback ends.

### 3.3 Seeing what peers hold

Spec: [catalog 3.3](../spec/v1/catalog.md#33-what-the-caller-keeps-of-each-title).

The engine reads each wanted peer's titles on its schedule and stores
them (host.md section 1). The host reads them there. Before offering a
viewer a peer's title, it asks:

```
Playable(peer: PeerID, kind: String) -> Bool                     sync
```

`true` when the peer is paired, not suspended, can be called, and
`playback`, `media` and the title's content part are on with it.

## 4. Events

One callback, `Notify(Event)` (host.md section 8). Each event names a
peer by ID where it concerns one. "Panel" says the operator should be
shown it; "viewer" that viewer pages should react.

| Event | When | For | Spec |
|-------|------|-----|------|
| `PeerWaiting` | a peer redeemed our code: state `ours`, the operator must compare fingerprints and accept | panel | [core 7.1](../spec/v1/core.md#71-the-steps) step 4 |
| `PeerPaired` | a pairing became `paired`, on either side | panel | core 7.1 step 6 |
| `PeerGone` | a peer answered, signed, that it doesn't know us; or 30 days suspended | panel | [core 7.3](../spec/v1/core.md#73-states), [12.6](../spec/v1/core.md#126-revocation) |
| `PeerEnded` | a pairing ended, by us or by them (`ended`) | panel, viewer | [core 7.4](../spec/v1/core.md#74-ending-a-pairing) |
| `PeerSuspended` | a peer revoked its key | panel (warning), viewer | core 12.6 |
| `RotationPending` | a peer moved to a key without a commitment: the operator must confirm its fingerprint | panel | [core 12.3](../spec/v1/core.md#123-receiving-a-rotation) case 4 |
| `RotationRefused` | a peer's rotation didn't match its commitment | panel (warning) | core 12.3 case 3 |
| `PeerRotated` | a peer's new key is current | panel | core 12.3 |
| `CommitmentOnFirstUse` | a peer's commitment came from a `hello` | panel (weaker, say so) | [core 12.5](../spec/v1/core.md#125-the-next-key-commitment) |
| `OurKeyLost` | after 30 days, peers that never moved to our new key: they must pair again | panel (warning) | [core 12.4](../spec/v1/core.md#124-what-each-side-does-during-the-change) |
| `RotationAnswered` | a peer answered our `rotate` (`rotated`, `pending`, `refused`) | panel | core 12.4 |
| `PeerMoved` | a peer's new address was confirmed and stored | panel | [core 13.2](../spec/v1/core.md#132-a-peer-that-learns-of-a-move) |
| `PeerMoveFailing` | a peer's new address has failed for a day | panel (warning) | core 13.2 step 3 |
| `NotMovedLate` | a peer still calls our former address some days after our move | panel (warning) | [core 13.1](../spec/v1/core.md#131-the-server-that-moves) |
| `MoveEnded` | our move is over: all peers moved, or 30 days | panel | core 13.1 |
| `CallsFailed` | a peer's answer said our last calls to it couldn't connect: suggest "this server can't be called" | panel | [core 7.5](../spec/v1/core.md#75-a-peer-that-cant-be-called) |
| `InboundChanged` | a peer says it can, or can't, be called now | panel, viewer | core 7.5 |
| `VersionsChanged` | a peer's versions changed; parts on with it may have changed | panel, viewer | [core 10](../spec/v1/core.md#10-versions-and-parts) |
| `CatalogRead` | a reading of a peer's titles ended: kept, dropped, or failed and why | panel, viewer | [catalog 3.2](../spec/v1/catalog.md#32-whole-list-or-changes) |
| `WantsGone` | libraries we want of a peer weren't in its last `libraries` answer | panel | [catalog 2.2](../spec/v1/catalog.md#22-what-the-caller-keeps) |
| `PlaybackStarted`, `PlaybackEnded` | a peer's playback here started, or ended and why | panel (live view) | [playback 6.1](../spec/v1/playback.md#61-a-playbacks-states) |
| `RemotePlaybackEnded` | a playback on a peer ended without our `Stop`: `410`, the pairing ended, the peer suspended | viewer | playback 6.3 |
| `CertificateRead` | our own pins changed, or reading them failed | panel | [core 3.2](../spec/v1/core.md#32-https-certificates) |

Events are notices. The state they speak of is always in the queries
too, so a host that missed one (a restart) loses nothing.

## 5. Background work

```
Run()                 blocks until cancelled
RunOnce()             one pass of everything due now, then returns
```

`Run` does, each on its own schedule (each wait varies, as the spec
says):

| Work | When | Spec |
|------|------|------|
| scheduled `hello`s of a server that can't be called | each second, sending those due | [core 7.5](../spec/v1/core.md#75-a-peer-that-cant-be-called) |
| `hello` to peers in `theirs`, at most every 20 seconds | each time the host calls `PanelOpen()`; on its own schedule for a server that can't be called (above) | [core 7.1](../spec/v1/core.md#71-the-steps) step 7 |
| reading peers' catalogs | a minute after start, then every `syncEvery`; at once when wants change | [catalog 3.2](../spec/v1/catalog.md#32-whole-list-or-changes) |
| playback expiry | every 30 seconds | [playback 6.3](../spec/v1/playback.md#63-how-a-playback-ends) |
| `progress` of the viewer's side, 45 seconds after the last one, when the host reported since | each second | [playback 3](../spec/v1/playback.md#3-progress) |
| stopping leftovers | once, at start; never one of a playback started since | playback 6.3 |
| keys: `rotate` again daily, the 30-day end of a rotation, 30 days suspended, previous keys no longer heard | every hour | [core 12](../spec/v1/core.md#12-key-rotation-and-revocation) |
| addresses: confirming a peer's move (at most hourly), telling peers ours, ending our move | every hour, and at each contact | [core 13](../spec/v1/core.md#13-changing-a-servers-address) |
| own certificate pins | as core 3.2 says | [core 3.2](../spec/v1/core.md#32-https-certificates) |
| expired codes, old forgotten keys, old change log, nonces | every hour | [core 7.4](../spec/v1/core.md#74-ending-a-pairing), [6.5](../spec/v1/core.md#65-nonces-replay-and-restarts) |

- `RunOnce` exists for tests with a fake clock, and for hosts that
  schedule work themselves (a Jellyfin `IScheduledTask`, say). A host
  calls one or the other, never both.
- Go: `func (e *Engine) Run(ctx context.Context) error`. C#:
  `Task RunAsync(CancellationToken ct)`, for a `BackgroundService`.
- Without `Run`, the engine still answers peers and the operator, but
  nothing happens with time: no expiry, no schedule, no reading.

## 6. Errors

One vocabulary for both libraries. Go: `msfp.ErrNotFound` and so on,
each a `*msfp.Error` with its `Code`, wrapped with detail where useful
and matched by `errors.Is`. C#: `MsfpException` with
`MsfpError Code` (an enum of the same names), and `Problem` when a peer's
signed refusal gave one.

**A peer's refusals**, as the engine reports them for calls it makes
([core 8.2](../spec/v1/core.md#82-refusals)):

| Code | From | Means |
|------|------|-------|
| `NotFound` | a signed `404` `not-found` (but on `hello`) | no such title for us, or not paired yet (the engine sends a `hello` at once) |
| `Unknown` | a signed `404` to `hello` | the peer doesn't know us: marked `gone` |
| `NotSupported` | a signed `404` `not-supported` | the part is off with it until its next `hello` |
| `InvalidRequest` | `400` `invalid-request` | a bug on our side; logged |
| `AlreadyPeer` | `409` to `pair` | we are already its peer |
| `RotationRefused` | `409` `rotation-refused` | |
| `StreamLimitReached` | `409` `stream-limit-reached`, or a `409` of another type | busy now |
| `NotPlayable` | `409` `not-playable`, and any other refusal of `play` | not playable |
| `PlaybackStopped` | `410` `playback-stopped` | the playback is over |
| `RateLimited` | `429` `rate-limited` with `retryAfter` | the engine holds calls until then |
| `ServerBusy` | `503` `server-busy` | busy now |
| `PeerFailed` | `500` `internal-error` | tries again later |
| `Unreachable` | no answer, an unsigned answer, a refused certificate, a refused destination | as no answer |

**The engine's own refusals**, before or instead of a call:

| Code | Means |
|------|-------|
| `BackingOff` | the peer asked to wait, or didn't answer lately; background calls hold off |
| `Uncallable` | the peer can't be called: no connection at all |
| `Suspended` | the peer's key was revoked |
| `KeyLost` | the peer never moved to our new key |
| `NotPaired`, `NotWaiting` | the peer isn't in the state the action needs |
| `CodeInvalid`, `CodeExpired`, `OwnCode`, `CodeRefused`, `NoCodes` | pairing codes |
| `NoNextKey`, `NotNextKey`, `NoPending`, `KeyTaken`, `RotationUnderWay` | keys |
| `InvalidAddress`, `PlainHTTP`, `RefusedDestination`, `CertificateRefused`, `MoveFailed` | addresses and connections |
| `InvalidLimits` | streams 0 to 50, transcodes 0 to streams, bitrate 0 to 1,000,000 |
| `InvalidReason` | `StopPlayback` with an ending that isn't the host's (`stopped`, `pairingEnded`) |
| `RangeNotSatisfiable` | the viewer's `Range` is malformed or out of the file |
| `Sealed` | a sealed value didn't open |
| `Internal` | anything else; logged with detail, never shown to a peer |

**The host's errors**, from its callbacks, and what the peer gets:

| The host returns | The peer gets |
|------------------|---------------|
| `NotPlayable` | `409` `not-playable` |
| `StreamLimitReached` (from `admit`) | `409` `stream-limit-reached` |
| `ServerBusy` | `503` `server-busy` |
| `NotFound` (Media) | `404` on the stream route |
| `RangeNotSatisfiable` (Media) | `416` |
| anything else | `500` `internal-error`, signed; logged |

## 7. Data objects

Fields only; each language spells them its way (Go `PeerView.State`, C#
`PeerView.State`, an enum in both).

**`PeerView`**: what the panel shows of a peer.

| Field | Content |
|-------|---------|
| `id`, `name`, `address`, `fingerprint` | the fingerprint of its current key ([core 4.2](../spec/v1/core.md#42-the-fingerprint)) |
| `state` | `PeerState`: `ours`, `theirs`, `paired`, `gone` |
| `created`, `paired`, `seen` | times |
| `suspended` | when it revoked its key |
| `core`, `parts` | the versions on with it; `otherCore` when there's none in common |
| `inbound`, `callsFailed` | `yes`, `no`, `confirming` |
| `commitmentFrom` | `pair`, `rotation`, `hello`, or none |
| `pending` | `{fingerprint, date}` of a key waiting for the operator |
| `refused` | `{fingerprint, at}` of a refused rotation |
| `ourKey`, `rotationAnswer` | what it knows of our key |
| `notMoved`, `moveLate`, `moving` | our move as it sees it; its own move being checked (`address`, `failingSince`, `warn`) |
| `limits`, `theirLimits` | ours to it, and its to us |
| `offers`, `wants`, `wantsGone` | counts |
| `unusableKey` | its stored key isn't one MSFP accepts |

**`Limits`**: `streams` (0 to 50), `transcodes` (0 to streams),
`bitrateKbps` (0 to 1,000,000), and music's `audioStreams`,
`audioTranscodes` ([music 5.1](../spec/v1/music.md#51-limits)).

**`CallLimits`**: per address before the signature (rate, burst), per
peer, all peers, `play` per peer, requests at once (per peer, in all,
queue length, wait), nonces remembered (per peer, strangers), body
size, fetches at once (per playback, per peer, small reads across the
server). Defaults: the suggested numbers of
[core 8.3](../spec/v1/core.md#83-limits-and-overload).

**`Library`**: `id` (the host's), `name`, `kind`; with `offered` in
`Offers`. **`WantedLibrary`**: `id` (the peer's public ID), `name`,
`kind`, `wanted`, `gone`.

**`Title`**: a tagged value.

| Kind | Fields |
|------|--------|
| common | `key`, `kind`, `library` (a public ID toward peers; the host's IDs from `Catalog`) |
| `VideoTitle` | `audio`, `subtitles` (tags), `with` (episode keys), `ids` (`imdb`, `tvdb`…) |
| `MusicTitle` | `name`, `artists`, `artistNames`, `album`, `disc`, `number`, `year`, `durationMs`, `ids` (`mbrelease`, `mbtrack`, `isrc`) |

The toolkit parses keys: `wire.ParseKey(s) -> TitleKey` (kind, scheme,
ID, season, episode), refusing any form but the canonical one.

**`Track`**: `id` (`a<n>`, `s<n>`), `label`, `language`, `channels`,
`role`, `default`, `forced`, `hearingImpaired`; for subtitles,
`pictures`.

**`PlayRequest`**, **`RemotePlayback`**: section 3.1.
**`StartRequest`**, **`Started`**, **`CopyInfo`**, **`Copy`**: host.md
section 3.

**`MediaPath`**: `Master`, `Playlist(name)`, `Segment(name)`, `File`,
`Subtitles(track, part)`, `Pictures(track, part)`, `Sheet(n)`.

**`CodeView`**: `id`, `note`, `created`, `expires`. **`CodePreview`**:
`address`, `fingerprint`, `expires`.

**`ServerView`**, **`PlaybackView`**: section 2.2.

## 8. An example

A host's start, in Go:

```go
eng, err := msfp.Open(ctx, msfp.Config{
    Address:  "https://media.example.org",
    Name:     func() string { return branding.Name() },
    Store:    myStore,     // msfp.Store, on the host's database
    Sealer:   myBox,       // msfp.Sealer
    Catalog:  myCatalog,   // msfp.Catalog
    Playback: myPlayback,  // msfp.Playback
    Media:    myMedia,     // msfp.Media
    Notifier: panelEvents, // msfp.Notifier
})
if err != nil { return err }
mux.Handle("/api/v1/federation/", eng.FederationHandler())
mux.Handle("/api/v1/stream/", eng.StreamHandler(myOwnStreams))
go eng.Run(ctx)

// The panel's "Use a code" button:
peer, err := eng.RedeemCode(ctx, pasted)
switch {
case errors.Is(err, msfp.ErrCodeExpired):
    show("This code has expired; ask for a new one.")
case err != nil:
    show(explain(err))
default:
    show("Waiting for " + peer.Name + "'s operator. Fingerprint: " + peer.Fingerprint)
}
```

The same in C#:

```csharp
var engine = await MsfpEngine.OpenAsync(new MsfpOptions {
    Address = "https://media.example.org",
    Name = () => branding.Name,
    Store = myStore, Sealer = myBox, Catalog = myCatalog,
    Playback = myPlayback, Media = myMedia, Notifier = panelEvents,
}, ct);
app.MapMsfp(engine, ownStreams: myOwnStreams);
// in a BackgroundService: await engine.RunAsync(stoppingToken);

try {
    var peer = await engine.RedeemCodeAsync(pasted, ct);
    Show($"Waiting for {peer.Name}'s operator. Fingerprint: {peer.Fingerprint}");
} catch (MsfpException e) when (e.Code == MsfpError.CodeExpired) {
    Show("This code has expired; ask for a new one.");
}
```

A peer's playback here, step by step:

1. The peer's `play` reaches `FederationHandler`. The engine checks the
   signature, the pairing, the part, the body, the limits.
2. It asks `Catalog.Copies(key, offered libraries)`, picks the copy,
   asks `Playback.Describe(copy)`, chooses the tracks.
3. It calls `Playback.Start(...)`. The host decides `transcode`, calls
   `admit("transcode")`, which passes; checks its own budget; starts its
   transcode; returns `Started`.
4. The engine makes the ID and the ticket, answers the peer, and tells
   `PlaybackStarted`.
5. The peer fetches `…/stream/<ticket>/master.m3u8`. `StreamHandler`
   checks the ticket and the request, calls `Media.Serve(handle, Master,
   …)`, checks the playlist, sends it.
6. No `progress` and no fetch for 2 minutes: `Run` ends it, cuts its
   responses, calls `Playback.Stop(handle, expired)`, tells
   `PlaybackEnded`.
