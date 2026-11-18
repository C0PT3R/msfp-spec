# MSFP libraries: the application-side API

**Informative, not part of the protocol.** Nothing here changes what a
server sends or accepts. Two servers interoperate if they follow
[spec/v1](../spec/v1/README.md), whatever library they use. This is a
design for review, written 2026-11-18. No code exists for it yet.

## What this is

MSFP has two implementations: Overfin (Go) and the Jellyfin plugin (C#).
Each has a toolkit of protocol pieces (keys, codes, signatures, strict
JSON, pins) and, on top of it, the protocol's behaviour, written against
its own application.

The owner's decision of 2026-11-18: the libraries become **engines**.

- `msfp-go` and `msfp-dotnet` run the protocol: pairing and its states,
  keys and their rotation and revocation, address changes, servers that
  can't be called, nonces, limits, catalog reading, both sides of a
  playback, the media relay's checks, and the HTTP handlers.
- The application, the **host**, plugs in through a small set of
  interfaces: storage, its catalog, its playback, its media, a clock,
  sealing, and notices.
- Both libraries expose the same API, as close as each language allows.
- Overfin is the first host. Its `internal/federation` becomes the Go
  engine behind these interfaces.

## The documents

| Document | What it holds |
|----------|---------------|
| this README | scope, the shape, the notation, the Go and C# forms, open questions |
| [host.md](host.md) | the interfaces the host implements |
| [engine.md](engine.md) | what the host calls: construction, operator and viewer actions, queries, HTTP handlers, background work, events, errors, data objects |
| [overfin.md](overfin.md) | where each piece of Overfin goes, what doesn't fit, and what in the plugin pushes against one API |

## 1. Scope

**The engine does** everything the specification says a server does
between servers:

- the core: keys, the pairing code, signing and checking, nonces,
  pairing and its states, `pair`, `hello`, `rotate`, `revoke`, versions
  and parts, the discovery document, address changes, servers that can't
  be called, limits and overload, connections to peers (refused
  destinations, pins, no redirects, no proxy);
- `catalog`: offers and wants, opaque library IDs, serving `libraries`
  and `titles` (pages and changes), reading peers' catalogs on a
  schedule, and what a caller keeps;
- `playback`: on the owning side, checking `play`, choosing the copy and
  the tracks, the pairing's stream and transcode counts, playback states,
  tickets, expiry, `progress`, `stop`, ending playbacks when a pairing or
  an offer changes; on the viewer's side, coarsening, calling `play`,
  checking and cleaning the answer, `progress` at its pace, `stop`, and
  stopping leftovers after a restart;
- `media`: on the owning side, the stream routes' checks (ticket, no
  query, no browser headers, ranges, methods, fetches at once); on the
  viewer's side, the relay's checks (URLs, ranges, `206`, sizes, time,
  playlists, WebVTT, PGS, sheets);
- `video` and `music`: title keys, what a title carries and what a caller
  keeps, their play members.

**The host keeps:**

- **the user interface**: the operator's panel and the viewers' pages.
  The engine gives it actions, queries and events, never HTML;
- **accounts and people**: who may see a peer's titles, who is playing.
  The engine never sees a person. Nothing it sends names one
  ([playback section 6](../spec/v1/playback.md#6-what-the-owning-server-enforces));
- **what a title is inside the host**: items, files, folders, its
  database. The engine sees libraries by the host's IDs, titles by their
  MSFP keys, and copies by opaque handles;
- **how media is made**: direct play, remuxing, transcoding, HLS
  segments, subtitles, preview sheets. The engine decides what may be
  served and checks it; the host produces the bytes;
- **its own stream routes** for its own people, and the viewer-facing
  route that serves a peer's relayed media to a browser;
- **where data lives**: the host implements storage, so peers, keys and
  catalogs sit in its own database, beside its own data.

## 2. The shape

```
          operator panel, viewer pages (host)
                 |  actions, queries   ^ events
                 v                     |
  +--------------------------- engine ---------------------------+
  |  pairing, keys, addresses, schedules, limits, catalog,      |
  |  playback states, tickets, relay checks, HTTP handlers      |
  +--------------------------------------------------------------+
     |        |          |           |          |        |
  Storage  Catalog   Playback      Media     Sealer    Clock, Dialer,
  (host)   (host)    (host)        (host)    (host)    Notifier (host)

  peers --HTTPS--> host's router --> engine's handlers
  engine --Dialer--> peers
```

The host mounts the engine's handlers on its router, starts its
background work, and calls it from its panel and its viewer pages. The
engine calls the host back through the interfaces.

## 3. Notation

Signatures are written in a neutral form:

```
RedeemCode(text: String) -> PeerView
    errors: CodeInvalid, OwnCode, AlreadyPeer, Unreachable, CodeRefused
```

- Types: `String`, `Int` (64-bit), `Bool`, `Bytes`, `Time` (an instant,
  UTC), `Duration`, `Key` (32 bytes of an Ed25519 public key), `PeerID`,
  `List<T>`, `Map<K, V>`, `T?` (may be absent).
- Every method may block and is cancellable, unless marked **sync**. In
  Go it takes a `context.Context` first; in C# it returns a `Task` and
  takes a `CancellationToken` last (section 5).
- Errors are named from the shared vocabulary of
  [engine.md section 6](engine.md#6-errors). A method may also fail with
  `Internal` or be cancelled; these aren't listed each time.
- "Spec" lines point at the sections a method serves.

## 4. Conventions

- **Peer IDs** are made by the engine: random, stable for the life of the
  pairing, and not the key, since keys rotate
  ([core section 12](../spec/v1/core.md#12-key-rotation-and-revocation)).
- **Library IDs**: the host names its libraries by its own IDs. Peers see
  only the opaque public IDs the engine makes and keeps
  ([catalog section 2.1](../spec/v1/catalog.md#21-library-ids)). The two
  never mix: methods say which they take.
- **Copies** are named by an opaque handle the host gives (a string the
  engine stores and passes back, never sends). Version IDs that peers see
  are the engine's keyed MAC of the handle.
- **Time** comes from the host's clock only. Statements carry Unix
  seconds; everything else is `Time`.
- **No network inside storage transactions.** The engine never calls a
  peer, or the host's media, while a storage transaction is open.
- **Untrusted text.** Every name, label and key from a peer reaches the
  host already cleaned as the specification says, and is still text, never
  markup.
- **Tickets** are never logged, never put in errors, never handed to the
  host's viewer pages ([media section 1](../spec/v1/media.md#1-the-urls)).

## 5. Go and C# forms

| Concept | Go (`msfp-go`) | C# (`msfp-dotnet`) |
|---------|----------------|--------------------|
| Package | module `msfp-go`, package `msfp`; the toolkit as `msfp/wire` | assembly and namespace `Msfp`; toolkit `Msfp.Wire`; ASP.NET Core glue in `Msfp.AspNetCore` |
| Engine | `*msfp.Engine` | `Msfp.MsfpEngine` (sealed class) |
| Host interface | `msfp.Store`, `msfp.Catalog`, `msfp.Playback`, `msfp.Media`, `msfp.Sealer`, `msfp.Clock`, `msfp.Dialer`, `msfp.Notifier` | `IStore`, `ICatalog`, `IPlayback`, `IMedia`, `ISealer`, `TimeProvider` (built in), `IDialer`, `INotifier` |
| Method names | `RedeemCode` | `RedeemCodeAsync` |
| Blocking calls | `func (e *Engine) RedeemCode(ctx context.Context, text string) (PeerView, error)` | `Task<PeerView> RedeemCodeAsync(string text, CancellationToken ct = default)` |
| Host callbacks | plain methods taking `ctx` | `ValueTask` / `ValueTask<T>`, so a host whose data is synchronous (Jellyfin's library) answers without allocating a task |
| **sync** methods | no `ctx`, no error unless listed | plain methods, no `Task` |
| Errors | `error`; `*msfp.Error` with a `Code`, matched by `errors.Is(err, msfp.ErrNotFound)` | `MsfpException` with `MsfpError Code`; see below |
| Cancellation | `ctx.Done()`; `ctx.Err()` returned as is | `OperationCanceledException`, never wrapped |
| Absent values | `*T` or a zero value, as each type says | `T?` (nullable) |
| Lookups that may find nothing | `(T, error)` with `ErrNotFound` | `ValueTask<T?>`, `null` for none |
| Events | one `Notifier.Notify(Event)`; `Event` is an interface, events are structs (`PeerPaired`, …), told apart by a type switch | `INotifier.Notify(MsfpEvent)`; `MsfpEvent` is an abstract record, events derived records, told apart by pattern matching |
| Tagged values (titles, media paths) | interface with concrete structs | abstract record with derived records |
| Bytes | `[]byte` | `byte[]` in records; `ReadOnlyMemory<byte>` in parameters |
| Streams of bytes | `io.Reader`, `io.Writer` | `Stream` |
| Time | `time.Time` (UTC), `time.Duration` | `DateTimeOffset` (UTC), `TimeSpan` |
| Clock | `msfp.Clock` with `Now() time.Time`; default the system clock | `TimeProvider`; default `TimeProvider.System` |
| Randomness | `io.Reader`, default `crypto/rand.Reader` | `RandomNumberGenerator`, default the system one |
| Logging | `*slog.Logger` | `ILogger` (Microsoft.Extensions.Logging) |
| HTTP handlers | `http.Handler` | `Func<HttpContext, Task>` in `Msfp.AspNetCore`; a neutral `MsfpRequest` and `MsfpResponse` in both |
| Background work | `Run(ctx)` blocks until `ctx` ends | `RunAsync(ct)`, for a `BackgroundService` |
| Ed25519 | `crypto/ed25519`, plus the strict checks | BouncyCastle (as the plugin today), plus the same strict checks; both against [vectors/v1](../vectors/v1/) |

**Why exceptions in C#.** The C# engine raises one exception type,
`MsfpException`, whose `Code` is the same vocabulary as Go's error codes.
Result types were the other choice: the plugin's toolkit already returns
records like `CallResult` and `CheckResult`. But on the engine's public
API almost every method is async, and a `Task<Result<T>>` on each would
make every caller unwrap twice. Exceptions also travel through
`await` unchanged, and sit beside .NET's own cancellation. Expected
outcomes are never errors in either language: a rotation waiting for the
operator, a `202`, a page with more to come, are results. Inside the
toolkit (`Msfp.Wire`), result records stay where they are: there they
are hot paths, and callers branch on them.

**Why `ValueTask` for host callbacks and `Task` for the engine.** The
host's catalog and storage are often synchronous (the plugin reads
Jellyfin's library and JSON files under a lock). `ValueTask` costs them
nothing. The engine's own methods are called by a panel or a page, once
each: `Task` is simpler for them.

## 6. Open questions

Each with a recommendation. Numbered for answers. **All 16 were decided
by the owner on 2026-11-18, as recommended, except 12** (see its
decision). Each says so.

1. **Storage shape.** Records with transactions (the engine reads and
   writes typed records inside `Update`; [host.md section 1](host.md#1-storage)),
   or a long list of named atomic operations like Overfin's store today
   (`RedeemPairingCode`, `RotateFederationKey`…)? *Recommended: records
   and transactions.* The host's work is plain reading and writing; the
   protocol's rules stay in the engine; both Overfin's SQLite and the
   plugin's JSON files do it easily (the plugin's `PeerStore.Change` is
   already this).
   *Decided 2026-11-18: as recommended.*
2. **Stores shipped with the libraries.** *Recommended: yes, two:* one in
   memory (tests, and the conformance suite's runs) and one in JSON files
   (small hosts, the plugin). Overfin writes its own on SQLite, because
   its pages join peers' titles with its own.
   *Decided 2026-11-18: as recommended.*
3. **The own catalog's change log.** Host or engine? *Recommended: both
   ways:* a host whose database already notes changes (Overfin) answers
   `Changes`; a host that can't (the plugin, which diffs today) leaves it
   out, and the engine keeps the log from snapshots of `Titles` in
   storage. [host.md section 2](host.md#2-catalog).
   *Decided 2026-11-18: as recommended.*
4. **Choosing the copy and the tracks.** *Recommended: the engine*, from
   the tracks the host lists, by the tables of
   [playback section 2.6](../spec/v1/playback.md#26-choosing-the-copy-and-the-tracks)
   and [video section 5.4](../spec/v1/video.md#54-choosing-the-subtitles).
   Then the host only decides how to serve the chosen tracks. The rules
   are the same everywhere; written once, they are tested once.
   *Decided 2026-11-18: as recommended.*
5. **Tickets.** *Recommended: the engine makes, checks and ends peers'
   tickets.* The host's own people's tickets stay the host's. The
   engine's stream handler takes a fallback for every ticket it doesn't
   know, so one route can serve both (Overfin's does).
   *Decided 2026-11-18: as recommended.*
6. **Stream counts.** *Recommended: the engine counts the pairing's
   streams and transcodes; the host counts its server-wide transcode
   budget*, both in one `Admit` step the host calls once it knows the
   method ([host.md section 3](host.md#3-playback)). The engine can't know
   the method before the host decides; the host can't know the pairing's
   limits without asking.
   *Decided 2026-11-18: as recommended.*
7. **Checking the host's own playlists.** On the owning side, should the
   engine check what the host's media sends against media 1's subset
   before it leaves? *Recommended: yes, playlists only.* It is cheap, and
   a host's rewrite bug then shows as a refused fetch and a warning, not as
   a peer refusing every fetch.
   *Decided 2026-11-18: as recommended.*
8. **Re-encoding relayed preview sheets.** Go has a JPEG encoder; .NET
   has none built in. *Recommended: a `SheetEncoder` hook*, given by
   default in Go, required in C# for previews: a C# host without one
   relays no previews (the viewer plays on without them, as
   [video section 5.5](../spec/v1/video.md#55-seek-bar-previews) allows).
   *Decided 2026-11-18: as recommended.*
9. **C# errors.** *Recommended: exceptions*, as section 5 explains.
   *Decided 2026-11-18: as recommended.*
10. **Events.** One callback, `Notify`, that must not block, or a channel
    or stream the host reads? *Recommended: the callback.* A channel left
    unread holds events or loses them; a callback is the same in both
    languages. The engine calls it outside its locks, in order, from one
    goroutine or task at a time.
    *Decided 2026-11-18: as recommended.*
11. **The discovery document and base paths.** As far as I found,
    Overfin calls fixed paths and stores no base path. *Recommended: the
    engine does both*: it fetches peers' documents where
    [core section 11](../spec/v1/core.md#11-the-discovery-document) says,
    stores the base, and serves its own document when the host turns it
    on (off by default).
    *Decided 2026-11-18: as recommended.*
12. **The next key's exported text.** Overfin exports
    `overfin-next-key-1.<seed>`. *Recommended: the engine exports
    `msfp-next-key-1.<seed>` and accepts both forms*, so keys already kept
    offline by Overfin's operators still work.
    *Decided 2026-11-18: `msfp-next-key-1.<seed>`, now in [core section 12.5](../spec/v1/core.md#125-the-next-key-commitment), is the only form; no `overfin-` form is accepted (nobody exported one).*
13. **Nonces.** *Recommended: in memory only*, refusing requests dated
    before the process started, as
    [core section 6.5](../spec/v1/core.md#65-nonces-replay-and-restarts)
    allows. No storage for them.
    *Decided 2026-11-18: as recommended.*
14. **Content parts.** Built into the engine, or modules a host adds?
    *Recommended: built in.* `video` and `music` are small; the host says
    which it serves (`Config.Parts`), and its catalog only lists those.
    *Decided 2026-11-18: as recommended.*
15. **Versions of the libraries.** *Recommended: one version number for
    both libraries, kept in step*, separate from the protocol's versions,
    and both run against the conformance suite and the vectors before
    each release.
    *Decided 2026-11-18: as recommended.*
16. **An admin API.** Should the engine also give JSON routes for a
    panel? *Recommended: no.* Panels differ; the actions and queries are
    enough, and a route would be a second, unsigned, way in that the host
    must guard anyway.
    *Decided 2026-11-18: as recommended.*
