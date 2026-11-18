# The host interfaces

**Informative, not part of the protocol.** What the application
implements for the engine. Notation and conventions:
[README sections 3 and 4](README.md#3-notation). The data objects named
here are in [engine.md section 7](engine.md#7-data-objects).

| Interface | Required | What it is |
|-----------|----------|------------|
| [Storage](#1-storage) | yes | the engine's records: server keys and settings, peers, codes, forgotten keys, library IDs, peers' catalogs |
| [Catalog](#2-catalog) | yes, to share | the host's own libraries and titles |
| [Playback](#3-playback) | yes, to let peers play | describe, start, keep and stop a copy's stream |
| [Media](#4-media) | yes, to let peers play | the bytes of a playback |
| [Sealer](#5-sealer) | yes | seals key seeds and secrets |
| [Clock](#6-clock-and-randomness) | no | the time; the system's by default |
| [Dialer](#7-dialer) | no | connections out; the engine's checked one by default |
| [Notifier](#8-notifier) | no | events for the panel and the viewer pages |
| [SheetEncoder](#9-sheet-encoder) | no in Go, yes in C# for previews | re-encodes a relayed preview sheet |

A host that only watches its peers (a server that can't be called, say)
can leave out Catalog, Playback and Media: it then offers no library,
and answers every `play` with `404`.

## 1. Storage

Spec: [core 7.2](../spec/v1/core.md#72-what-each-side-stores),
[core 7.4](../spec/v1/core.md#74-ending-a-pairing),
[core 12.5](../spec/v1/core.md#125-the-next-key-commitment),
[core 13](../spec/v1/core.md#13-changing-a-servers-address),
[catalog 2.1](../spec/v1/catalog.md#21-library-ids),
[catalog 3.2](../spec/v1/catalog.md#32-whole-list-or-changes).

The engine owns the meaning of every field. The host stores and returns
them as they are. It may keep them in columns of its own database, as
long as a record read back is the record written.

```
Read(fn: (Tx) -> T) -> T
Update(fn: (Tx) -> T) -> T
```

- `Read` gives a consistent view. `Update` is atomic: everything `fn`
  wrote is kept, or nothing (when `fn` fails, or the commit does).
- The engine never calls a peer or the host's media inside `fn`, and
  keeps `fn` short.
- Two `Update`s never interleave their effects (serializable, or one at
  a time). SQLite's one writer, or a lock around a JSON file, does it.
- C#: `ValueTask<T> ReadAsync<T>(Func<IStoreTx, CancellationToken, ValueTask<T>> fn, CancellationToken ct)`,
  the same for `UpdateAsync`.

**`Tx`**, inside a transaction:

| Method | Content |
|--------|---------|
| `Server() -> ServerRecord?` | the one server record; absent on the first start |
| `PutServer(r: ServerRecord)` | |
| `Peers() -> List<PeerRecord>` | every peer, any state |
| `Peer(id: PeerID) -> PeerRecord?` | |
| `PeerByKey(key: Key) -> PeerRecord?` | by current key only |
| `PutPeer(r: PeerRecord)` | adds or replaces |
| `DeletePeer(id: PeerID)` | and its catalog, its sent keys and its leftovers |
| `Codes() -> List<CodeRecord>` | |
| `CodeByHash(secretHash: Bytes) -> CodeRecord?` | |
| `PutCode(r: CodeRecord)`, `DeleteCode(id: String)` | |
| `Forgotten(keyHash: Bytes) -> Time?` | when it was forgotten |
| `Forget(keyHash: Bytes, at: Time)`, `Unforget(keyHash: Bytes)` | |
| `TrimForgotten(before: Time)` | entries older than a year may go |
| `LibraryIDs() -> Map<String, String>` | host library ID to public ID, gone libraries included: an ID is never reused |
| `PutLibraryID(hostID: String, publicID: String)` | |
| `Sent(peer: PeerID, keys: List<String>) -> List<String>` | which of these title keys the peer was ever sent (below) |
| `MarkSent(peer: PeerID, keys: List<String>)` | |
| `Leftovers() -> List<Leftover>`, `PutLeftover(l: Leftover)`, `DeleteLeftover(l: Leftover)` | playbacks this server started on peers, to stop after a restart |
| `OwnLog…` | only when the engine keeps the own catalog's change log (section 2): `OwnSnapshot`, `PutOwnSnapshot`, `OwnChanges(since, after, limit)`, `AppendOwnChanges`, `TrimOwnChanges(before)` |

**Sent keys.** A changes answer names in `gone` only titles that the
peer was told of before. Otherwise a `gone` would tell a peer of titles
it never could see. Overfin keeps this (its `peer_sent` table); the
engine keeps it through `Sent` and `MarkSent`.

**The records** (fields; the engine fills them):

`ServerRecord`:

| Field | Content |
|-------|---------|
| `current` | the current key's seed, sealed (`Sealer`, context `msfp current key`) |
| `next` | the next key's seed, sealed; absent once exported and deleted |
| `nextCommitment` | SHA-256 of the next key, public |
| `old`, `oldSince`, `oldRevoked` | the key before the current one while peers move from it, since when, and whether it was revoked first ([core 12.4](../spec/v1/core.md#124-what-each-side-does-during-the-change), [12.7](../spec/v1/core.md#127-what-to-do-on-compromise)) |
| `idsSecret` | the secret of opaque IDs, sealed; never changes |
| `address`, `former`, `movedAt` | the address noted last, the one before it and when it changed, while a move lasts |
| `uncallable`, `uncallableAddress` | the operator's setting, and the `https://msfp-<26>.invalid` address made for it, kept |

`PeerRecord`:

| Group | Fields |
|-------|--------|
| identity | `id`, `key`, `previousKey`, `previousUntil`, `name`, `created` |
| state | `state` (`ours`, `theirs`, `paired`, `gone`), `wasPaired`, `paired`, `seen`, `suspended` |
| address | `address`, `base`, `move` (`address`, `since`, `failingSince`), `ourAddress` (the host of ours its requests are signed for), `inbound` (`yes`, `no`, `confirming`), `callsFailed` |
| versions and pins | `core`, `parts` (as its latest signed `hello` listed them), `pins` |
| its keys | `commitment`, `commitmentFrom` (`pair`, `rotation`, `hello`), `pending` (a rotation statement), `rotations` (statements kept, with their signatures), `refused` (`key`, `at`) |
| our keys toward it | `ourKey` (`current`, `old`, `lost`), `rotationAnswer` (`pending`, `refused`), `rotateSent`, `commitmentTold` |
| sharing | `offers` (host library IDs), `offersSeq`, `wants` (`WantedLibrary`: public ID, name, kind, gone), `limits` (ours to it), `theirLimits`, `catalogRead` (`seq`, the wants it was read with) |

`CodeRecord`: `id`, `secret` (sealed), `secretHash`, `note`, `created`,
`expires`.

`Leftover`: `peer`, `playbackID` (the peer's).

**Peers' catalogs.** Bulk, and read by the host's own pages (Overfin
joins them with its own titles), so outside the records:

| Method | Content |
|--------|---------|
| `PutPeerTitles(peer: PeerID, reading: Int, titles: List<Title>)` | adds or replaces, marked with the reading |
| `EndReading(peer: PeerID, reading: Int)` | after a whole-list reading: drops that peer's titles not marked with it |
| `DropPeerTitles(peer: PeerID, keys: List<String>)` | a changes reading's `gone` |
| `PeerTitles(peer: PeerID, after: String, limit: Int) -> List<Title>` | in key order |
| `PeerTitle(peer: PeerID, key: String) -> Title?` | |

The host reads them as it likes (counts, joins, search). The engine
writes them only.

**Errors.** Any error the host returns fails the engine's action, which
fails toward the peer as `500` `internal-error`. Lookups that find
nothing return absent, not an error.

## 2. Catalog

Spec: [catalog 2](../spec/v1/catalog.md#2-libraries),
[catalog 3](../spec/v1/catalog.md#3-titles),
[video 3](../spec/v1/video.md#3-titles),
[music 3](../spec/v1/music.md#3-what-a-title-carries),
[playback 2.2](../spec/v1/playback.md#22-what-the-owning-server-does).

The host's own libraries and titles, by the host's library IDs. The
engine maps them to public IDs, filters them by offers, pages them,
and checks every key before it leaves.

```
Libraries() -> List<Library>
```

Each `Library`: the host's `id`, `name`, `kind` (`movies`, `tvshows`,
`music`, `mixed`…, [catalog 2](../spec/v1/catalog.md#2-libraries)). The
operator chooses offers among these.

```
Titles(libraries: List<String>, after: String, limit: Int) -> TitlePage
```

- The titles held in any of these host libraries, keys strictly greater
  than `after`, in ascending byte order of key, at most `limit`, each
  once.
- Each `Title` carries its key, its kind, the host libraries that hold
  it, and the members of its content part: for video `audio`,
  `subtitles`, `with`, `ids`; for music `name`, `artists`,
  `artistNames`, `album`, `disc`, `number`, `year`, `durationMs`, `ids`
  ([engine.md section 7](engine.md#7-data-objects)).
- `TitlePage`: `titles`, and `more` (whether titles remain after the
  last).
- A title its content part can't name (no TMDB ID, no recording MBID) is
  not listed.
- The engine picks the `library` sent to the peer (the requested one
  whose public ID comes first in byte order) and drops keys that aren't
  canonical, with a warning in its log.

```
Seq() -> Int                                           optional
Changes(libraries: List<String>, since: Int, after: String, limit: Int)
    -> ChangePage                                      optional
```

- Implemented together, or neither. `Seq` is the change number now;
  `Changes` gives what changed in these libraries after `since`:
  `present` (titles new or changed), `gone` (keys), `last` (the last key
  of the page), `more`.
- `Changes` fails with `TooOld` when the host no longer keeps its log
  back to `since`. The engine then answers the whole list.
- Without them, the engine keeps the log itself: at each `Refresh`
  (below) it reads every title, compares with its snapshot in storage,
  and notes the changes. That costs a full read at each refresh; fine for
  a few tens of thousands of titles.

```
Copies(key: String, libraries: List<String>) -> List<Copy>
```

- The host's copies of exactly this film, episode or track, in these
  host libraries (those offered to the caller). None: the engine answers
  `404`.
- Each `Copy`: `handle` (opaque to the engine; the version ID a peer
  sees is a MAC of it), `name` (for `versions`), `audio` (its languages,
  as tags, for choosing the copy).
- For an episode inside a copy holding several (`with`), the copy that
  holds it.

**Telling the engine.** The host calls `engine.CatalogChanged()` when its
titles change (a hint: the engine refreshes its own log, if it keeps one)
and `engine.LibraryRemoved(id)` when a library is gone (offers of it end,
and so do playbacks from it,
[playback 6.3](../spec/v1/playback.md#63-how-a-playback-ends)).

C#: `ValueTask<IReadOnlyList<Library>> LibrariesAsync(CancellationToken)`,
and so on. The plugin's synchronous `ILibraryManager` calls answer with
`ValueTask.FromResult`.

## 3. Playback

Spec: [playback 2](../spec/v1/playback.md#2-play),
[playback 6](../spec/v1/playback.md#6-what-the-owning-server-enforces),
[video 5](../spec/v1/video.md#5-playing-a-film-or-an-episode),
[music 5](../spec/v1/music.md#5-playing-a-track).

The owning side. The engine has already checked the request, found the
copies, picked the copy, and refused what the pairing's limits refuse
early. It then asks the host in two steps.

```
Describe(copy: String) -> CopyInfo
```

- The copy's tracks, for the engine to choose from: `audioTracks` and
  `subtitleTracks` (positions `a<n>`, `s<n>`, with language, label,
  channels, role, flags; subtitles with `pictures` for PGS), `durationMs`,
  the episode's start inside a copy holding several (when known), and
  whether it has previews (`trickplay` layout and sheet count).
- Picture subtitles other than PGS are left out: they're not listed
  ([video 5.4](../spec/v1/video.md#54-choosing-the-subtitles)).

The engine chooses the audio and the subtitles by the specification's
tables, then:

```
Start(req: StartRequest) -> Started
    errors: NotPlayable, ServerBusy, StreamLimitReached
```

`StartRequest`:

| Field | Content |
|-------|---------|
| `copy` | the handle |
| `peer` | `PeerRef`: the peer's ID and name, for the host's live view (never a person) |
| `audioTrack`, `subtitleTrack` | the engine's choice (`subtitleTrack` absent: none shown) |
| `startMs` | where to start, in the copy |
| `capabilities` | what the viewer's device plays, coarsened, only values MSFP lists, compared exactly |
| `maxBitrateKbps` | the cap in effect: the lowest of the request's, the capabilities', the server's own (`Config`) and the pairing's; 120,000 when none |
| `admit` | `Admit`, below |

The host decides how to serve (`direct`, `remux`, `transcode`, the
cheapest first, [playback 2.6](../spec/v1/playback.md#26-choosing-the-copy-and-the-tracks)),
then, **before starting any work**, calls:

```
admit(method: String) -> Slot                    sync
    errors: StreamLimitReached, ServerBusy
```

- The engine counts the pairing's streams and, for `transcode`, its
  transcodes, in one atomic step
  ([playback 6.2](../spec/v1/playback.md#62-limits-at-once)). Over them:
  `StreamLimitReached` (streams) or `ServerBusy` (transcodes).
- The host checks its own server-wide transcode budget (less what it
  keeps for its own people) at the same moment, under its own lock, and
  releases the slot it got if its budget refuses.
- `Slot.Release()` frees what was counted (the host calls it when its
  start fails). `Slot.Transcoding() -> Bool` moves a remux that turned
  out to re-encode the video into the transcode count; `false` when the
  pairing has no transcode left, and the host then stops it.

`Started`:

| Field | Content |
|-------|---------|
| `handle` | the host's handle for this playback (not the copy's) |
| `method` | as admitted |
| `protocol` | `hls` or `file`; for `file`, `mimeType` |
| `positionMs` | where it starts, in the copy |
| `info` | `reasons`, `container`, `bitrateKbps`, `video`, `audio`, short text |
| `segments` | skip markers, when the host has them |

The engine makes the playback ID and the ticket, builds the stream URLs
under its stream root, fills `versions`, `versionId`, the tracks and the
previews, and answers the peer.

```
Progress(handle: String, positionMs: Int, paused: Bool)
Stop(handle: String, reason: EndReason)
```

- `Progress`: a peer's `progress`, passed on (for the host's live view,
  its media server's reports). Throttling and expiry are the engine's.
- `Stop`: the playback ended, for any reason of
  [playback 6.3](../spec/v1/playback.md#63-how-a-playback-ends)
  (`stopped`, `expired`, `tooLong`, `pairingEnded`, `notOffered`,
  `operator`). The host stops the transcode. Open media responses are
  cut by the engine.
- `Stop` comes once for each `Start` that succeeded. When `Start` fails
  after `admit`, the host releases the slot itself, and no `Stop` comes.

Errors: `NotPlayable` (the host has no way to play the copy),
`ServerBusy` (its budget, or its media server busy). Anything else
becomes `500`.

## 4. Media

Spec: [media](../spec/v1/media.md),
[video 6](../spec/v1/video.md#6-media).

The bytes of a live playback. The engine has checked the ticket, the
method, the query, the browser headers, the `Range` header's form, and
the fetches at once; it counts the request as use, and cuts the
response when the playback ends.

```
Serve(handle: String, path: MediaPath, rng: Range?, out: ResponseSink)
    errors: NotFound, RangeNotSatisfiable, ServerBusy
```

- `MediaPath` is one of: `Master`, `Playlist(name)`, `Segment(name)`,
  `File`, `Subtitles(track, part)`, `Pictures(track, part)`,
  `Sheet(n)`. Names are already checked against
  `^[A-Za-z0-9._-]{1,64}$`, never `.` or `..`.
- `rng` only for `File` and `Segment`, already parsed (one range, one of
  the three forms). The host answers `206` with the range, `200` with the
  whole, or `RangeNotSatisfiable` past the end.
- `ResponseSink`: `Start(status, contentType, length?, contentRange?)`,
  then the body (Go `io.Writer`, C# `Stream`). The engine sets no other
  header than these, and no content coding.
- The host sends playlists in media 1's subset
  ([media 3.1](../spec/v1/media.md#31-hls-playlists)), WebVTT in
  [video 6.3](../spec/v1/video.md#63-webvtt)'s form, PGS stretches, and
  sheets re-encoded as JPEG. The engine checks playlists before they
  leave (README, question 7).
- `NotFound`: no such name, track, part or sheet.

## 5. Sealer

Spec: [core 12.5](../spec/v1/core.md#125-the-next-key-commitment)
(keep the next key's seed apart).

```
Seal(plain: Bytes, context: String) -> Bytes          sync
Open(sealed: Bytes, context: String) -> Bytes          sync
    errors: Sealed (wrong context, tampered, or another key)
```

- The engine seals every seed and secret it stores: `msfp current key`,
  `msfp next key`, `msfp old key`, `msfp ids secret`, `msfp code secret`.
  One context's box never opens as another's.
- The host chooses how: a key in its configuration, a file apart from
  the data, a secret store. Overfin's `seal.Box` is one.
- The libraries ship `PlainSealer` for tests, which seals nothing. Its
  name says so.

## 6. Clock and randomness

```
Now() -> Time                                          sync
```

- Go: `msfp.Clock`; C#: `TimeProvider`. Default: the system's.
- A host's tests set it to a fake clock, then call `RunOnce`
  ([engine.md section 5](engine.md#5-background-work)) to make time's
  work happen.
- Randomness (keys, nonces, codes, tickets, IDs) comes from
  `Config.Random`, the system's cryptographic source by default. Tests
  may fix it; a server never does.

## 7. Dialer

Spec: [core 3.3](../spec/v1/core.md#33-connecting-to-peers).

```
Dial(host: String, port: Int) -> Connection
    errors: RefusedDestination, Unreachable
```

- **Default: the engine's own.** It looks the name up once, checks
  every address against the refused ranges (loopback only when
  `Config.AllowLoopback`), and connects to a checked address. No proxy
  from the environment.
- **A host may replace it**, when its connections go out elsewhere (an
  Overfin backend, through its gateway). A replacement must apply the
  same check where the connection is made. The engine still does TLS,
  SNI, pins (*trusted*, *named* or *any*), no redirects, no content
  coding, and the time bounds, on top of the connection.
- C#: `ValueTask<Stream> ConnectAsync(string host, int port, CancellationToken ct)`;
  the engine puts it in a `SocketsHttpHandler.ConnectCallback`.

## 8. Notifier

```
Notify(event: Event)                                   sync
```

- The events of [engine.md section 4](engine.md#4-events).
- Called in order, one at a time, outside the engine's locks. It must
  return quickly: a host that needs to do slow work queues it.
- Absent: events are only logged.

## 9. Sheet encoder

Spec: [video 6.2](../spec/v1/video.md#62-what-is-fetched).

```
Reencode(jpeg: Bytes, maxWidth: Int, maxHeight: Int) -> Bytes
    errors: NotAnImage
```

The viewer's side. The engine has read the sheet whole (at most 8 MiB)
and checked its header: a JPEG within the size. The encoder decodes it
and encodes the pixels again as JPEG, so only pixels reach the viewer.
Go's default uses `image/jpeg`. In C#, without an encoder, previews are
not relayed: `trickplay` is dropped from the answer the host sees.
