# Overfin onto the engine, and the plugin

**Informative, not part of the protocol.** Where each piece of Overfin's
federation goes when `internal/federation` becomes `msfp-go`, what the
design can't express yet, and what in Overfin or the Jellyfin plugin
pushes against one API for both languages. From reading Overfin's code
and the plugin's on 2026-11-18; nothing was run.

## 1. The refactor, piece by piece

"Engine" means the piece moves into `msfp-go`. "Host" means it stays in
Overfin, behind or beside an interface. "Toolkit" means `msfp-go/wire`.

### 1.1 `internal/msfp` (the toolkit)

| File | Goes to |
|------|---------|
| `key.go`, `ed25519.go`, `sign.go`, `json.go`, `code.go`, `hello.go`, `versions.go`, `rotation.go`, `pins.go`, `address.go`, `uncallable.go`, `retry.go` | toolkit, as they are |
| `playback.go`, `media.go`, `video.go`, `webvtt.go`, `pgs.go` | toolkit; the engine's relay and play checks call them |
| `doc.go` | the toolkit's package comment |
| `*_test.go`, `vectors_test.go`, fuzz tests | toolkit, with the vectors |

### 1.2 `internal/federation` (the behaviour)

| File, piece | Goes to | Notes |
|-------------|---------|-------|
| `service.go`: `Service` struct, `Plugin.Register` | engine: `Engine`, `FederationHandler` | Overfin mounts the handler instead of registering six routes |
| `service.go`: `SignRefusals`, `refusalWriter`, `verified`, `admit`, `answer` | engine, inside the handlers | |
| `service.go`: `pair`, `hello`, `keepHello`, `theyPaired`, `viewOf`, `cleanName` | engine | |
| `service.go`: `call`, `callOnce`, `exchange`, `Reply`, `forgotUs` | engine | `Call`, `CallReply`, `PeerRequest`, `Answer` (used by `api/peerplay.go` today) leave the public API: play, progress and stop move into the engine |
| `service.go`: `UseCode`, `NewCode`, `Accept`, `End`, `Check`, `CheckSoon` | engine: `RedeemCode`, `MakeCode`, `Accept`, `End`, `Check`, `PanelOpen` | |
| `service.go`: `OurLibraries`, `OfferedTo`, `SetOffers`, `SetWants`, `TheirLibraries`, `libraries` | engine, over `Catalog.Libraries` and storage | |
| `service.go`: `titles`, `SyncTitles`, `SyncAll`, `SyncSoon`, `SyncEvery` | engine, over `Catalog.Titles`/`Changes` and the peer catalog methods | |
| `service.go`: `Speaks`, `SpeaksCore`, `refusedPart`, `notSupported`, `OurVersions` | engine; `Playable` for the host's pages | |
| `service.go`: `ValidLimits`, `ErrLimits` | engine: `SetLimits`, `InvalidLimits` | |
| `service.go`: `NewHTTPClient` | engine, over the `Dialer` | |
| `keys.go`: `Keys`, `LoadKeys`, `Opaque`, `NextKeyText` | engine | the shared `Keys` across rebuilds goes: one engine for the process |
| `rotation.go` (all) | engine | `Rotate`, `Revoke` become `Rotate`, `KeyStolen`; `ConfirmRotation`, `DismissRefused`, `NextKey`, `ExportNextKey`, `DeleteNextKey` stay as they are |
| `rotation.go`: `Maintain` | engine, inside `Run` | |
| `address.go` (all) | engine | `NoteAddress` becomes part of `Open` and `SetAddress`; `AddressFor`, `NotMoved`, `Moving` become `PeerView` and `ServerView` fields |
| `uncallable.go` (all) | engine | `Hellos` goes inside `Run` |
| `limits.go` (all) | engine | `Background(ctx)` goes: the engine knows which calls it makes by itself |
| `tls.go`: `peerConns`, `TLSConfig`, `Repin`, `keepCertificates` | engine | `TLSConfig` and `Repin`, used by `api/relay.go`, leave the public API: the relay moves into the engine |
| `tls.go`: `Certificates`, `probe` | engine | over the `Dialer`, or `Config.pins` |

### 1.3 `internal/api`

| File, piece | Goes to | Notes |
|-------------|---------|-------|
| `playback.go`: the three `HandlePublic` routes for `play`, `progress`, `stop` | engine (`FederationHandler` serves them) | |
| `peerplay.go`: `peerPlay` (checks, `pickCopy`, bitrate, early limit check) | engine | |
| `peerplay.go`: `peerPlay` (Jellyfin's `PlaybackRequest`, device profile, `open`, `previews`, `ReportStart`, `Describe`) | host: `Playback.Describe` and `Playback.Start` | `open` today also chooses the tracks with Jellyfin; that choice moves into the engine (README, question 4) |
| `peerplay.go`: `peerProgress`, `peerStop` | engine, then `Playback.Progress` and `Playback.Stop` | |
| `peerplay.go`: `PeerChanged`, `peerMayPlay` | engine | the engine ends peers' playbacks itself, and tells `Playback.Stop` |
| `peerplay.go`: `startRemote` (account limits, profiles, `Tickets.Admit`, title summaries, next episode, browser URLs) | host | it calls `engine.Play` where it calls `fed.CallReply` today |
| `peerplay.go`: `startRemote` (rounding, refusal reading, `readPlayAnswer`, `keepPeerURLs`, `cleanPeerText`, `peerLayoutOK`, `stopRemote` on a broken answer) | engine: `Play` | |
| `peerplay.go`: `tellRemote`, `stopRemote`, `StopLeftovers`, `pendingStops` | engine: `Progress`, `Stop`, `Run`, `PlayRequest.replaces` | |
| `peerplay.go`: `sourceOf`, `peerSources`, `speaks`, `chooseRemoteTracks` | host | they read peers' titles from storage, and the viewer's wishes |
| `relay.go`: `relay`, `relayGet`, `relaySlots`, `parseRange`, `checkPartial`, `relaySheet`, `relayClient` | engine: `Fetch` | |
| `relay.go`: the browser route around them | host | it maps its own URL to a `MediaPath` |
| `stream.go`: the four `GET /api/v1/stream/…` routes | shared | they become `engine.StreamHandler(fallback)`, with today's handlers as the fallback for Overfin's own people's tickets |
| `stream.go`: serving a peer's ticket (Jellyfin's HLS rewritten to media 1's subset, subtitles in stretches, PGS, sheets) | host: `Media.Serve` | the ticket and request checks before it move into the engine |

### 1.4 `internal/admin`

| File | Goes to |
|------|---------|
| `federation.go`, `federation_keys.go` | host. The handlers stay; each calls the engine's action instead of the service's. `peerOf` maps `PeerView` to its JSON. `pairingProblem` and `nextKeyProblem` map the error codes to the panel's words |

### 1.5 `internal/store`

| File, piece | Goes to |
|-------------|---------|
| `federation.go`, `federation_keys.go`, `federation_address.go`, `federation_uncallable.go`: the tables | host: Overfin's `msfp.Store` on SQLite. The schema can stay; the methods change |
| the named operations (`RedeemPairingCode`, `RotateFederationKey`, `FinishFederationRotation`, `RotatePeer`, `SuspendPeer`, `PeerMovedTo`, `MovePeer`, `SetPeerState`…) | engine. Their rules (what changes together) move into the engine's `Update`s; the store only reads and writes records |
| sealing inside the store (`s.box.Seal`, `sealedPublic`) | host: `Sealer`, given the same `seal.Box`. The store no longer seals federation values itself |
| `PeerOffers`, `PeerWants`, `PeerLimits`, `PeerTitles` and the catalog tables | host storage, read by the engine |
| `TitlesInLibraries`, `ChangedTitles`, `TitleChanges`, `TrimTitleChanges`, `PeerCopies`, `ItemOfferedTo`, `addWith`, `addOtherIDs` | host: `Catalog.Titles`, `Catalog.Changes`, `Catalog.Seq`, `Catalog.Copies`. The offer filter moves out of the SQL: the engine passes the offered host libraries |
| `PeerTold`, `peer_sent` | host storage, behind `Sent` and `MarkSent`; the rule of using it moves into the engine |
| `PublicLibraryIDs` | host storage, behind `LibraryIDs`; making the ID moves into the engine |
| `AddRemotePlayback`, `ForgetRemotePlayback`, `TakeRemotePlaybacks` | host storage, behind `Leftovers` |
| `PeerSources`, `TitlePeers`, `MenuLibraries`, `LabelPeerWant`, `RenamePeerWants`, `PeerTitleCounts`, `ItemAudio` | host, unchanged: Overfin's own pages over peers' titles |
| `DeleteExpiredPairingCodes` (in `purgeExpired`) | engine, inside `Run` |

### 1.6 `overfin/` and `internal/outbound`

| Piece | Goes to |
|-------|---------|
| `gateway.go`: `fedShared`, `federationService` (a service per rebuild) | host: one `msfp.Open` at start; settings changes call `SetAddress`, `SetUncallable` |
| `gateway.go`: `fed.PeerChanged = pb.PeerChanged` | gone: the engine ends playbacks itself |
| `overfin.go`: `syncPeers`, `maintainKeys`, `helloSchedule`, the leftovers' `Do` | engine: one `go eng.Run(ctx)` |
| `internal/outbound` (`Through`, `DialContext`, the gateway's egress) | host: Overfin's `Dialer`. Direct, it is the engine's default; on the backend, the gateway's egress, which checks addresses the same way |

## 2. What the design can't express yet, in Overfin

1. **One stream route for two kinds of ticket.** Overfin serves its own
   people's browsers and peers on the same `/api/v1/stream/` routes, with
   other rules (its people's tickets accept `HEAD`, and pass on any
   single range). The fallback of `StreamHandler` keeps this, but
   Overfin's `playback.Tickets` registry must stop holding peers'
   playbacks: the engine holds them, and the host's live view reads
   `Playbacks()` and the `PlaybackStarted`/`Ended` events.
2. **One transcode budget for both.** Today a peer is an "account"
   (`playback.PeerPrefix + peer.ID`) inside the same `Tickets.Admit` as
   Overfin's people, and the budget less `PeerTranscodeReserve` is
   counted there. With `admit`, the pairing's counts are the engine's and
   the server's budget stays Overfin's: two locks, taken in order
   (the engine's, then the host's, released in reverse on refusal).
   Atomic enough for [playback 6.2](../spec/v1/playback.md#62-limits-at-once)
   (no `play` ever passes over a limit), but a `play` may be refused by
   one count while the other would have let a later one through.
3. **Sealing contexts.** Overfin seals a pairing code's secret under the
   code's ID as context, and its keys under contexts of its own
   (`federation next key`…). The engine's contexts differ. Overfin's
   `Sealer` maps the engine's to its existing names, or the first start
   reseals: either way, keys already stored must open. To decide when the
   refactor is planned.
4. **The opaque ID construction.** Overfin's version IDs are
   `ver_` + HMAC(IDs secret, `"version\n" + peerID + "\n" + Jellyfin's
   source ID`), first 16 bytes. Peers keep version IDs only for the life
   of a copy, but changing the construction would still break a viewer's
   saved choice. The engine should use the same construction, with the
   copy handle in place of the source ID; Overfin's handle is then
   Jellyfin's source ID, as now.
5. **Peer IDs.** Overfin's peer IDs are made by its `ids` package. The
   engine makes its own; Overfin's storage keeps the IDs it has (they're
   opaque to the engine), so existing ones stay.
6. **No base path, no discovery.** Overfin calls
   `/api/v1/federation/...` on every peer and stores no base; I found no
   fetch of `/.well-known/msfp`. The engine does both (README, question
   11). Not a conflict: a capability Overfin gains.
7. **The name.** Overfin's name comes from its branding, read at each
   call. `Config.name` is a callback for this.
8. **Client addresses behind the gateway.** Overfin's limit by address
   reads `identity.ClientIP` (its trusted proxies, or the address its
   gateway passes on). The host passes it to the handlers; the engine
   never reads `X-Forwarded-For` itself.

## 3. What pushes against one API for Go and C#

From Overfin, the plugin (jellyfin-plugin-msfp, still on the
v0 draft, read for shape only), and the two languages.

**The plugin.**

1. **Synchronous host data.** Jellyfin's `ILibraryManager` is
   synchronous, and its events fire on any thread. The plugin's
   `ICatalogSource` is synchronous today. The C# host interfaces use
   `ValueTask` so it costs nothing (README section 5); the plugin answers
   with `ValueTask.FromResult`.
2. **No change log.** The plugin diffs full reads of its library into its
   own log (`OwnCatalog.Refresh`). That is the engine-kept log of
   `Catalog` without `Changes` (README, question 3).
3. **No playback at all.** The plugin has no `play`, no streams, no
   transcoding (no `IMediaSourceManager`, no streaming helpers). Its
   `Playback` and `Media` would be new work against Jellyfin's
   transcoding, the biggest piece of a C# host; until then it leaves them
   out, and only shares and reads catalogs.
4. **Controllers, not endpoints.** Jellyfin plugins add MVC controllers.
   The plugin's `FederationController` would build an `MsfpRequest`
   (`FromAsync(HttpContext)`) and write the `MsfpResponse`, and keep
   turning off Jellyfin's response compression, which would otherwise
   change signed bytes.
5. **Storage is files.** Jellyfin's plugin configuration is XML and flat;
   the plugin keeps its state in JSON files with copy-on-write
   (`PeerStore.Change`). The shipped JSON file store (README, question 2)
   is that, generalised.
6. **The seed in plain.** The plugin keeps its seed unsealed (mode 0600).
   A `Sealer` is required by the engine; the plugin needs one (a key file
   apart from its data folder, say) or chooses `PlainSealer` knowingly.
7. **Peer ID = key.** The plugin identifies peers by their key. That
   breaks with rotation; it moves to the engine's IDs.
8. **Background work.** The plugin runs a `BackgroundService` with a
   one-minute timer. `RunAsync` fits it as is.
9. **Lazy construction.** The plugin's services are singletons built by
   factory lambdas, forced at start by an `IHostedService`.
   `OpenAsync` is async; the plugin opens the engine in that hosted
   service, and its controllers wait for it.
10. **JPEG.** .NET has no JPEG encoder built in. Jellyfin has its own
    image encoder (`IImageEncoder`), but as far as I know it works on
    files, not bytes; not checked. Hence the `SheetEncoder` hook (README,
    question 8).

**The languages.**

11. **HTTP.** Go's `http.Handler` and ASP.NET Core differ in how a raw
    target, the client address and an unbuffered body are reached. The
    neutral `MsfpRequest`/`MsfpResponse` is the one shape both share;
    each library adds its own adapter.
12. **Errors.** Go returns values and C# throws. Same codes, different
    mechanism (README section 5). Expected outcomes are results in both.
13. **Events.** A Go interface with structs, a C# abstract record with
    derived records: the same names and fields, matched differently.
14. **Ed25519.** Go's standard library and BouncyCastle accept different
    keys and signatures at the edges. Both libraries apply the strict
    rules of [core 2.1](../spec/v1/core.md#21-ed25519) themselves, and
    both run [vectors/v1](../vectors/v1/) in their tests.
15. **Time.** `time.Time` and `DateTimeOffset` both hold an instant; the
    engine uses UTC only, and Unix seconds only inside statements. Go's
    fake clocks are a small interface; C# uses `TimeProvider`, which tests
    replace with `FakeTimeProvider`.
16. **Byte streams.** Media goes through `io.Reader`/`io.Writer` and
    `Stream`. The `ResponseSink` hides the difference for the host's
    `Media.Serve` and the engine's `Fetch`.
