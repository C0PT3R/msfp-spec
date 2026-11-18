# MSFP: Media Server Federation Protocol

MSFP lets media servers share their libraries with each other: one
server's people browse and play titles another server holds, through
their own server.

Version 1 covers manual pairing only: two operators pair their servers
by hand, and each trusts only the servers it paired with. Larger
federations are planned, not specified.

## Version 1: a draft

[spec/v1/](spec/v1/README.md) is a core plus five parts, each with its
own version, agreed per peer in `hello`:

- [core](spec/v1/core.md): the strict rules, HTTPS only, MSFP's own labels
  and headers, signed answers that cover their media type, key rotation
  and revocation, address changes, versions and parts, and an optional
  discovery document (`/.well-known/msfp`, off by default);
- [catalog](spec/v1/catalog.md): libraries and titles, opaque library
  IDs, the general rules of title keys;
- [playback](spec/v1/playback.md): starting, keeping and stopping a
  playback, limits;
- [media](spec/v1/media.md): what the stream URLs serve;
- two content parts, each optional:
  [video](spec/v1/video.md), films and series by TMDB (TMDB's
  numbering, several episodes in one copy, IMDb and TVDB identifiers,
  subtitles, skip markers, seek-bar previews), and
  [music](spec/v1/music.md), artists, albums and tracks by MusicBrainz.

It comes from proposals 1 to 8 and the clarifications in
[proposals/](proposals/README.md), all adopted on 2026-11-16, proposal 9
(option 1, servers that can't be called), and proposal 11 (music, every
content type optional), adopted on 2026-11-17.

## Version 0: a test draft

[spec/v0.md](spec/v0.md) was a test draft. Version 1 supersedes it and
doesn't work with it. Version 0 is not to be implemented; it stays here
as history, with its corrections of 2026-11-16 and 2026-11-17
([section 17](spec/v0.md#17-changes)).

## Test vectors

[vectors/](vectors/README.md): signed sample requests and answers, and
valid and invalid cases, for an implementation's tests.

- [vectors/v0.json](vectors/v0.json), version 0's vectors from Overfin's
  code, stays as history and never changes.
- [vectors/v0-strict.json](vectors/v0-strict.json) and
  [vectors/v1/](vectors/v1/) come from the generator in
  [tools/vectors/](tools/vectors/), which also checks every file. No
  implementation produced them. v0-strict.json is history too, but its
  canonical-form cases hold for core 1.

## Conformance suite

[conformance/](conformance/README.md): a program that pairs with a server
you run, as a peer, and checks it against version 1, over HTTPS both
ways: pairing, `hello`, versions and parts, signatures, the strict
rules, replay, the catalog, playback and media, rotation and revocation,
address changes, servers that can't be called, and on request rate
limits and ending. Python 3, standard library only, with a self-test
against a fake server. Its code is under the MIT license. The version 0
suite is in git history.

## Implementations

- [Overfin](https://github.com/Overfin/server), the first one.
- [jellyfin-plugin-msfp](https://github.com/C0PT3R/jellyfin-plugin-msfp),
  a Jellyfin plugin in C#.

Questions and gaps in the specification are welcome as issues.

## License

- The specification and this README: [CC BY 4.0](LICENSE). Copy, translate
  or adapt them, with credit. Implementing the protocol needs no permission
  and carries no condition.
- The test vectors (`vectors/`): [CC0 1.0](vectors/LICENSE), no conditions.
  Copy them into any test suite.
- The conformance suite (`conformance/`): [MIT](conformance/LICENSE), and
  its bundled Ed25519 reference code the IETF Trust's Simplified BSD
  License.
