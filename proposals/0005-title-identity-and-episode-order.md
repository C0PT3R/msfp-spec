# Proposal 5: Title identity beyond TMDB, and episode order

Status: Adopted (2026-11-16); open points still open.
Touches: sections 9.4, 9.5 and 11, and open question 8 of
[spec/v0.md](../spec/v0.md).

## Problem

Two servers must name the same film or episode with the same key, or a
viewer's server can't tell that a peer's title is one it already has,
or carry watched state across. Version 0 has three weak spots.

### 1. "The owning server's order"

Section 11 says "season and episode numbers follow the owning server's
order of the series", and open question 8 notes that two servers that
number a series differently disagree on `s<n>/e<m>` keys. The plugin
(SPEC-GAPS.md, "11: episode 0, and which order is the owning server's
order") found that the phrase doesn't say which order: Jellyfin keeps the
numbers from the files and metadata, and lets users pick a display order
(DVD, absolute…) without renumbering items. The plugin assumed the
numbers stored on the items.

What Overfin does (`internal/store/migrations/081_own_episode_order.sql`,
`RefreshTitleKeys` in `internal/store/personal.go`): a file's numbers are
read as TMDB's own order of the series. Overfin looks the numbers up in
that order to find TMDB's episode ID, and sends `e<episode id>` when it
finds one. An order its operator picks only changes what Overfin shows.
So Overfin's keys depend on TMDB's default numbering, not on the server's
display order. The specification says something else.

### 2. Double episodes and episode 0

The plugin (SPEC-GAPS.md, "11: a file holding several episodes") sends
one key per episode of a multi-episode file, all pointing to the same
copy. Overfin does the same: `internal/store/catalog.go` adds a row per
extra episode, pointing to the file (`range_of`). Neither side says what
`play` of the second episode starts, and the specification doesn't
mention double episodes. Also, `<episode>` is "1 to 5 digits", which
includes `0`; the plugin assumed `s1/e0` is valid.

### 3. TMDB only

Every key is a TMDB key; an owning server "must not send" others, and a
receiver keeps only titles "identified by TMDB" (section 9.4). The plugin
checked this live: a film without a TMDB ID isn't sent (SPEC-GAPS.md,
"11 and 9.4: items without a TMDB ID"). Overfin's own keys already have
`imdb` and `tvdb` sources internally (section 11's version 0 note,
`ParseTitleKey`). Requiring TMDB is right for now. But a peer can't send
the IMDb or TVDB IDs it has, which would let a receiver match a title it
holds under another ID, and there is no planned way to admit other
schemes later.

## Proposal

### Episode order (replaces the last bullet of section 11)

> Season and episode numbers in keys are TMDB's: the `season_number` and
> `episode_number` TMDB gives the episode in the series' own season
> list, not in an episode group. An owning server whose files are
> numbered another way (DVD, absolute, a broadcaster's order) maps them
> to TMDB's numbering before it sends keys. When it can't, it leaves the
> episode out.
>
> An episode TMDB lists is sent with the `e<episode id>` form. The
> `s<season>/e<episode>` form is only for an episode TMDB doesn't list
> (yet), in a season TMDB numbers; its numbers continue TMDB's numbering
> of that season. A receiver matches it only against the same form.
>
> The order a server shows its people is its own business and never
> appears in keys.

This is what Overfin does already. For the plugin, it means reading the
item's TMDB episode ID when Jellyfin has one, which it already does, and
otherwise trusting Jellyfin's numbers only when the library's metadata
order is TMDB's default. Jellyfin's display-order setting does not
renumber items, per the plugin's finding, so it doesn't matter.

### Episode 0

`<episode>` is `0` or `[1-9][0-9]{0,4}`. Episode 0 is valid wherever TMDB
numbers one (some seasons have a pilot or prologue as 0). Season 0 holds
specials, as today.

### Several episodes in one copy

Add to section 11:

> A copy that holds several episodes is listed once per episode, each
> under its own key. Each of those titles carries `with`: the keys of
> the other episodes the same copy holds, in byte order (at most 16).
> `play` of any of them plays that copy. The owning server starts at
> the episode's beginning when it knows where that is, else at the
> copy's beginning; the `play` answer's `positionMs` says where it
> started, and the viewer's server must start there.

Add to section 9.4's title table:

| Field | Type | Content |
|-------|------|---------|
| `with` | array of string, optional | the other keys the same copy holds |

A receiver may use `with` to show "episodes 1–2" as one entry, and to
mark all of them watched together.

### Other identifier schemes

1. Keep the key grammar of section 11, and name its middle part the
   **scheme**. Version 1 has one scheme, `tmdb`. The rule that a
   receiver skips keys of a scheme it doesn't know stays.
2. Add an optional member to titles of kind `movie`, `series` and
   `episode`:

   | Field | Type | Content |
   |-------|------|---------|
   | `ids` | object, optional | other identifiers of the same title, by scheme |

   Schemes and forms for version 1:

   | Scheme | Form | Example |
   |--------|------|---------|
   | `imdb` | `tt` and 7 to 10 digits | `tt0133093` |
   | `tvdb` | 1 to 10 digits, no leading zero | `81189` |

   Unknown schemes in `ids` are ignored. A value that breaks its form is
   ignored. `ids` never replaces the key: two titles are the same when
   their keys are equal. `ids` only helps a receiver find a title it
   holds under another identifier.
3. A later version of the `catalog` part (proposal 4) may admit keys of
   other schemes, for titles TMDB lacks. Its rules would say which scheme
   wins when a title has several, so that every server picks the same
   key. That is not proposed now.

## Alternatives considered

1. **Keep "the owning server's order".** Matches nothing either
   implementation does exactly; keeps open question 8 open.
2. **TMDB episode IDs only, no numbers form.** Cleanest identity, but
   loses episodes TMDB doesn't list yet (new episodes appear on servers
   before TMDB has them).
3. **TMDB episode groups in keys** (`series/tmdb/<id>/g<group>/…`), so a
   server could send its display order. Lets two servers agree on DVD
   order, but they would still disagree with servers on the default
   order; the episode ID already does this job.
4. **One key for a multi-episode copy** (for example
   `series/tmdb/1399/s1/e1-e2`). Hides episode 2 from a receiver that
   matches keys one by one. Rejected.
5. **Allow other schemes in keys now.** A title would then have several
   possible keys, and two servers could pick different ones. Needs a
   precedence rule that is better written once a second scheme is truly
   needed.

## Cost

**Specification.** Section 11's last bullet rewritten, two short
paragraphs, two optional members in section 9.4, open question 8 closed.
Test vectors: a key list with verdicts (`e0`, leading zeros, an episode
ID of 0).

**Overfin.**

- Order: none; it already keys this way.
- `with`: the owning side already knows which rows share a file
  (`range_of`); about 20 lines in the titles query. On the viewer side,
  showing ranges is optional.
- `play` of a later episode: as far as read (`peerplay.go` passes the
  request's `startPositionMs` on), Overfin plays the shared file from the
  requested position, not from the episode's own start. Starting at the episode's own
  beginning would need chapter data; not required.
- `ids`: the catalog already holds `imdb` and `tvdb` for each item; about
  20 lines to send them, and a lookup on the viewer side if wanted.

**Plugin.** `with`: from `IndexNumber` and `IndexNumberEnd`, which it
already reads. `ids`: from Jellyfin's provider IDs. Order: a note in its
documentation that libraries should use TMDB's default numbering.

## Compatibility

- Order: no wire change. Both implementations already behave this way
  (Overfin by design, the plugin by Jellyfin's stored numbers), as long
  as files follow TMDB's numbering.
- `with` and `ids` are optional members. A version 0 receiver ignores
  them.
- `e0`: version 0 already allows it by its grammar; the text now says so.

## Open points

1. Series that exist in TMDB only as one long season while files use
   real seasons (or the reverse), common for anime: the rule says "map,
   or leave out". Is leaving out acceptable, or should the numbers form
   be allowed with the owning server's numbering, marked as such?
2. Whether `ids` should also carry IMDb episode IDs (they exist), or
   stay at film and series level.
3. The cap of 16 for `with`.
