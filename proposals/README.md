# Change proposals for MSFP

Proposals to change [MSFP version 0](../spec/v0.md) while it is still a
draft. Each one stands alone and is decided on its own. Each has the same
sections: Problem (with evidence), Proposal, Alternatives considered,
Cost (specification, Overfin, the plugin), Compatibility, Open points.

The evidence comes from the specification, from the second, independent
implementation (the Jellyfin plugin's SPEC-GAPS.md and DESIGN-NOTES.md),
and from reading Overfin's federation code. Where a proposal says
something was run or checked, it was, on 2026-11-16; where it was only
read or assumed, it says so.

| # | Proposal | Status |
|---|----------|--------|
| 1 | [Strict canonical rules](0001-strict-canonical-rules.md): one Ed25519 rule set (canonical points in the prime-order subgroup), I-JSON, one text per value, refuse the rest | Adopted, R check required |
| 2 | [Opaque library IDs](0002-opaque-library-ids.md): library and version IDs chosen by the owning server, never the media server's | Adopted, choose again |
| 3 | [Key rotation and revocation](0003-key-rotation-and-revocation.md): a rotation signed by the old and new keys, a committed next key, revocation | Adopted whole |
| 4 | [A core plus separately versioned parts](0004-core-and-parts.md): core, `catalog`, `playback`, `media`, announced in `hello`; MSFP names; optional `/.well-known/msfp` | Adopted, MSFP names |
| 5 | [Title identity beyond TMDB, and episode order](0005-title-identity-and-episode-order.md): TMDB's numbering in keys, `with` for double episodes, `e0`, `ids` for IMDb and TVDB | Adopted |
| 6 | [Request signatures vs RFC 9421](0006-request-signatures-vs-rfc9421.md): a comparison; recommends keeping MSFP's scheme | Adopted: own scheme, plus Content-Type |
| 7 | [HTTPS only](0007-https-only.md): drop plain `http`, now that pins allow self-signed certificates | Adopted |
| 8 | [Changing a server's address](0008-address-changes.md): a signed, confirmed address change in `hello` | Adopted |
| 9 | [Private servers](0009-private-servers.md): a server that can't be called says so in `hello` and pulls rotation and revocation (option 1); a reverse connection, the optional part `transport` (option 2) | Option 1 adopted, its open points settled 2026-11-17 (address `msfp-<26>.invalid` required); option 2 set aside |
| 10 | [The mesh](0010-mesh.md): servers learn that others exist (signed, expiring announcements: key, name, address or "can't be called", versions), never catalogs; knowing is not trusting; spread through pairings (option a), open gossip (b) or a DHT (c); asks that end in an ordinary pairing; optional vouching; the optional part `mesh` | Deferred 2026-11-17: manual pairing only for now |
| 11 | [Music](0011-music.md): the part `music`; artists, albums (release groups) and tracks (recordings) by MusicBrainz ID; titles carry their own names; art from the Cover Art Archive; one audio playback per track | Adopted; every type optional (`video`, `music`); open points still open |
| – | [Clarifications](clarifications.md): 34 small fixes that need only a "yes" | Accepted, all 34 |

Some proposals lean on others; each says how it reads without them:

- 3 uses 1's Ed25519 rules for the statements, and 4 to learn which peers
  support rotation.
- 6's recommendation assumes 1, and 4's core version 1 for its small
  changes.
- 7's migration of existing pairings uses 8.
- 9's option 2 uses option 1's `inbound` member, codes and address rule,
  and 4's parts; its pulled rotation and revocation use 3.
- 10 uses 4's parts and 1's Ed25519 rules for its statements, carries 3's
  rotation and revocation statements, applies 8's address confirmation to
  addresses learnt from the mesh, and 9's `inbound` member when 9 is
  adopted.
