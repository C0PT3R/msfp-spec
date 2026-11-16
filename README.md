# MSFP: Media Server Federation Protocol

MSFP lets media servers share their libraries with each other: one
server's people browse and play titles another server holds, through
their own server.

Both versions cover manual pairing only: two operators pair their servers
by hand, and each trusts only the servers it paired with. Larger
federations are planned, not specified.

## Version 0: what is spoken today

[spec/v0.md](spec/v0.md) is what Overfin and the Jellyfin plugin speak
today. It is a draft, and it stays the compatibility baseline: a version 1
server speaks version 0 to a peer that speaks only version 0.

It holds the encodings, HTTPS certificates and pins, keys and
fingerprints, the pairing code, signed requests and answers, pairing and
its states, and the calls `pair`, `hello`, `libraries`, `titles`, `play`
(with seek-bar previews), `progress` and `stop`, and how media is fetched.

On 2026-11-16 it was corrected, without a new version: one strict rule set
for Ed25519, encodings, JSON and addresses; library and version IDs that
the owning server chooses; and 34 clarifications.
[Section 17](spec/v0.md#17-changes) lists the corrections. Overfin's code
doesn't follow all of them yet; the specification says where.

## Version 1: a draft, not implemented yet

[spec/v1/](spec/v1/README.md) is a core plus three parts, each with its
own version, agreed per peer in `hello`:

- [core](spec/v1/core.md): the strict rules, HTTPS only, MSFP's own labels
  and headers, signed answers that cover their media type, key rotation
  and revocation, address changes, versions and parts, an optional
  discovery document (`/.well-known/msfp`, off by default), and how
  version 1 coexists with version 0;
- [catalog](spec/v1/catalog.md): libraries and titles, opaque library
  IDs, title identity (TMDB's numbering, several episodes in one copy,
  IMDb and TVDB identifiers);
- [playback](spec/v1/playback.md): starting, keeping and stopping a
  playback, limits, seek-bar previews;
- [media](spec/v1/media.md): what the stream URLs serve.

Nothing implements version 1 yet. It comes from the eight proposals and
the clarifications in [proposals/](proposals/README.md), all adopted on
2026-11-16.

## Test vectors

[vectors/](vectors/README.md): signed sample requests and answers, and
valid and invalid cases, for an implementation's tests.

- [vectors/v0.json](vectors/v0.json) comes from Overfin's code, and never
  changes.
- [vectors/v0-strict.json](vectors/v0-strict.json) and
  [vectors/v1/](vectors/v1/) come from the generator in
  [tools/vectors/](tools/vectors/), which also checks every file. No
  implementation produced them yet.

## Implementations

- [Overfin](https://github.com/Overfin/server), the first one. It speaks
  version 0.

Questions and gaps in the specification are welcome as issues.

## License

- The specification and this README: [CC BY 4.0](LICENSE). Copy, translate
  or adapt them, with credit. Implementing the protocol needs no permission
  and carries no condition.
- The test vectors (`vectors/`): [CC0 1.0](vectors/LICENSE), no conditions.
  Copy them into any test suite.
