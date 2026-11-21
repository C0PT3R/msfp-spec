# Proposal 2: Opaque library IDs

Status: Adopted (2026-11-16): migration by choosing again (no `formerId`, open point 1).
Touches: sections 9.3, 9.4, 12 and open question 2 of
[spec/history/test-draft.md](../spec/history/test-draft.md).

## Problem

Section 12 says a peer never learns the owning server's "media server's
item IDs". Section 9.3's version 0 note says Overfin's library IDs are
"its media server's own library IDs, passed through". On Jellyfin, a
library is an item, and its ID is an item ID like any other. So version 0
contradicts itself, and Overfin breaks section 12.

Evidence:

- The plugin's SPEC-GAPS.md, "9.3 and 12: library IDs are the media
  server's item IDs", found the contradiction and chose its own IDs:
  `lib_` plus an HMAC-SHA256 of Jellyfin's ID under a secret kept by the
  plugin, cut to 12 bytes, in base64url (20 characters in all).
- Overfin (`internal/federation/service.go`, `OurLibraries`) sends
  `catalog_libraries.id`, which is Jellyfin's library ID, normalized.
  `titles` answers carry the same ID in `library`, and `titles` requests
  name it.
- Jellyfin computes item IDs as an MD5 of the item type's name and the
  item's path (`LibraryManager.GetNewItemId`, read in Jellyfin's source).
  Libraries are folders under Jellyfin's configuration, named after the
  library. So a library's ID is likely an unkeyed hash of a guessable
  string. This last step (how a library's own path is formed) was not
  verified.

The same leak exists in `play` answers. Overfin's owning side builds a
peer's playback with the code it uses for its own people
(`internal/api/peerplay.go` calls `open`), and the version IDs it sends
are `ver_` followed by the media server's media source ID
(`internal/api/playback.go`). On Jellyfin, a title's main media source
has, as far as known, the item's own ID (not checked on a live server
for this proposal). So section 9.5's `versionId` and `versions[].id`
carry item IDs to peers today. This wasn't noted in the plugin's gaps,
since the plugin builds no `play` yet.

Beyond the leak, passed-through IDs tie a pairing to one media server.
When the operator replaces or rebuilds the media server, every library ID
changes. Each peer's wants then point at IDs that no longer exist. In
Overfin, `titles` silently ignores unknown IDs (section 9.4), so the
peer's titles just disappear.

## Proposal

Replace the `id` row of section 9.3's library table, and add a paragraph:

> | `id` | string | the library's ID: 1 to 64 characters of `A–Z a–z 0–9 _ -` |
>
> A library ID is chosen by the owning server and means nothing outside
> it. It must not be, contain, or be computable by a peer from, any
> identifier of the media server, a file, a path or a name. A keyed MAC of
> such an identifier, under a secret the server keeps, satisfies this; a
> plain hash doesn't.
>
> A library ID is stable: the same library keeps the same ID across
> restarts, renames, upgrades and, where the server can tell it is the
> same library, a change of media server. An ID is never reused for
> another library.
>
> The ID may be the same toward every peer, or differ per peer. A peer
> must not compare library IDs across peers.

Recommended practice, not required: a random value (at least 96 bits,
base64url), stored with the library when the server first offers it, and
kept with the server's other federation state. Unlike a MAC of the media
server's ID, a stored value survives a change of media server: the
operator (or an import) maps the old library to the new one.

State the same rule once more in section 9.5, for the version IDs of a
`play` answer (`versionId`, `versions[].id`): opaque, chosen by the
owning server, not derived from the media server's IDs without a key.
They need to be stable only for the life of a title's copies, since a
viewer's server passes them back only in a later `play` of the same
title. Track IDs (`a<n>`, `s<n>`) are positions, not identifiers, and
are not concerned.

Remove the version 0 note of section 9.3, the last line of section 12's
"never" list that refers to section 9.3, and open question 2.

Also say, in section 9.4, which library a title names when several
requested libraries hold it: the one whose ID comes first in byte order.
The plugin already does this, and Overfin does it on its own IDs
(`min(library_id)` in `internal/store/federation.go`). With opaque IDs
the order is over the opaque IDs.

## Alternatives considered

1. **Keep passing IDs through, and change section 12 to allow it.** No
   cost. Leaks a guessable hash of the media server's layout, and keeps
   pairings tied to one media server.
2. **HMAC of the media server's ID only** (the plugin's choice). Opaque,
   stable across restarts, no storage needed. Doesn't survive a change of
   media server unless the secret and the old IDs are carried over.
   Allowed by the proposal; not the recommended practice.
3. **Per-peer IDs required.** Stops two peers from telling that they see
   the same library. They learn little from it: both already know which
   server they talk to. Allowed, not required.
4. **No library IDs at all**, titles only. Peers then couldn't choose
   what they want from an offer. Rejected.

## Cost

**Specification.** A few lines in sections 9.3, 9.4 and 12; one open
question closes. No new call.

**Overfin.** Moderate, all on the owning side, at the boundary:

- a table mapping Jellyfin library IDs to wire IDs (or a secret, for an
  HMAC), created on first offer;
- `OurLibraries` and `OfferedTo` return wire IDs; `titles` maps requested
  wire IDs back to Jellyfin's, and writes wire IDs in `library`;
- `peer_offers` can keep internal IDs: the panel never shows them to
  peers;
- `play` finds copies by internal ID, unchanged;
- the change log used for `since` readings must treat the switch as a
  change of what is offered (so the next reading is a whole one).

For version IDs: the owning side maps `ver_` IDs through the same kind
of keyed MAC (or a per-playback table) in peer answers only, and maps
them back when a peer's `play` names one. Overfin's own site can keep
its current IDs. About 30 lines in `peerplay.go`.

On the viewer side, nothing changes: Overfin already treats peers' IDs
as opaque strings of up to 64 bytes. Note that Overfin's menu entry IDs
for peer libraries are derived from the pairing and the library ID
(`SetPeerWants`), so the site's URLs for a peer's library change once
with the IDs.

**Plugin.** None: its IDs already satisfy the rule. It should store the
HMAC secret with its other state if the recommended practice is wanted
for media server changes.

## Compatibility

The rule doesn't change the wire format, only what an ID may be. A
version 0 receiver can't tell the difference.

The switch itself breaks existing wants: a peer's stored wants name the
old IDs. Migration, for one release:

- the owning server adds an optional member `formerId` to each library
  in `libraries` answers, holding the version 0 ID, only toward peers
  paired before the switch;
- a caller that has a want for `formerId` renames it to `id`, keeping
  its menu entry and stored titles, then reads the whole list again;
- the owning server also accepts former IDs in `titles` requests for
  that release;
- after one release (or 90 days), `formerId` is no longer sent.

`formerId` shows a peer only what it already received. A caller that
ignores it (version 0) loses its wants for that peer, and its operator
ticks them again. With few pairings in place today, the simpler path is
acceptable too: skip `formerId`, and tell operators to choose their wants
again after the upgrade.

## Open points

1. `formerId`, or "choose again"? The first is about 30 lines on each
   side for a one-time event.
2. Should the specification also cap how often an ID may change (for
   example, "only when the library is removed")? Proposed wording says
   "stable" and "never reused"; a cap would be hard to check.
3. Rather than one rule for libraries and one for versions, the
   specification could state once, in section 12, that every identifier
   an owning server sends is opaque in this sense, and list them.
