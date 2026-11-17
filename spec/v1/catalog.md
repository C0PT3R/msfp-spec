# MSFP version 1: the catalog part, version 1

**Draft.** Nothing implements version 1 yet. [Version 0](../v0.md) is what
Overfin and the Jellyfin plugin speak today.

The `catalog` part says which libraries a server offers a peer, which
titles they hold, and how titles are named. It needs only the
[core](core.md). Its calls follow the core's rules for every call
([core section 8](core.md#8-common-rules-for-every-call)): signed `POST`s
under the peer's base path, answered only to peers in state `paired`,
and only when `catalog` is on between the two servers
([core section 10](core.md#10-versions-and-parts)). A server that doesn't
speak `catalog` with the caller answers its calls with a signed `404`
`not-supported`.

The words "must", "must not" and "should" carry their usual meaning in
specifications.

## Contents

1. [Terms](#1-terms)
2. [Libraries](#2-libraries)
3. [Titles](#3-titles)
4. [Title keys](#4-title-keys)
5. [What is shared](#5-what-is-shared)
6. [Security considerations](#6-security-considerations)
7. [Open questions](#7-open-questions)

## 1. Terms

- **Library**: a collection of titles on a server, with an ID, a name and
  a kind.
- **Offer**: the libraries a server lets one peer see. Each server sets
  its own offers, per peer.
- **Want**: the libraries of a peer's offer that this server reads. Only
  titles in a library one side offers and the other wants are shared.
- **Owning server**: the server that holds a title's copy.
- **Title key**: the text that names a film, series, season or episode
  (section 4).
- **Scheme**: the source of the identifier in a title key. Version 1 has
  one, `tmdb` (The Movie Database).

## 2. Libraries

`libraries`, under the peer's base path. A paired peer asks which
libraries the receiver offers it.

Request: `{}`. No fields.

Answer `200`:

| Field | Type | Content |
|-------|------|---------|
| `name` | string, optional | the receiver's name now, for the caller's menu |
| `libraries` | array of library | the libraries offered to the caller, possibly empty |
| `limits` | limits object, optional | sent only when `playback` is on between the two servers: what the caller may use of the receiver at once ([playback section 5](playback.md#5-limits)) |

Library:

| Field | Type | Content |
|-------|------|---------|
| `id` | string | the library's ID: 1 to 64 characters of `A–Z a–z 0–9 _ -` |
| `name` | string | its name, text |
| `kind` | string | one of `movies`, `tvshows`, `music`, `musicvideos`, `homevideos`, `boxsets`, `books`, `photos`, `mixed`, or `""` |

`mixed` is for a library that holds several kinds; `""` is for kinds
outside the list.

### 2.1 Library IDs

A library ID is chosen by the owning server and means nothing outside
it. It must not be, contain, or be computable by a peer from, any
identifier of the media server, a file, a path or a name. A keyed MAC of
such an identifier, under a secret the server keeps, satisfies this; a
plain hash doesn't.

A library ID is stable: the same library keeps the same ID across
restarts, renames, upgrades and, where the server can tell it is the same
library, a change of media server. An ID is never reused for another
library.

The ID may be the same toward every peer, or differ per peer. A peer must
not compare library IDs across peers.

Recommended practice, not required: a random value (at least 96 bits,
base64url), stored with the library when the server first offers it, and
kept with the server's other federation state. Unlike a MAC of the media
server's ID, a stored value survives a change of media server: the
operator (or an import) maps the old library to the new one.

A server whose former IDs broke this rule changes them once; its peers'
operators then choose their libraries again
([core section 16.7](core.md#167-choosing-libraries-again)).

### 2.2 What the caller keeps

- at most 200 libraries;
- entries whose `id` breaks the form above are skipped; of two libraries
  with the same `id`, the first;
- names cleaned as in [core section 9.1](core.md#91-pair) (`?` when
  empty). Names are text, never markup: a receiver treats them as text
  wherever it shows them, and may clean further;
- an unknown `kind` becomes `""`;
- members of the wrong JSON type ([core section 2.3](core.md#23-json)): a
  `libraries` that isn't an array, or a top-level `name` that isn't a
  string, fails the answer (the caller treats the peer as unreachable and
  keeps what it had); an entry of `libraries` that isn't an object, or
  whose `id` isn't a string, is skipped; a library's `name` or `kind`
  that isn't a string counts as absent (`?`, `""`); a `limits` that isn't
  an object, or whose members aren't integers, is ignored, as are limits
  out of range.

Refusals: signed `404` when the caller isn't `paired`, or when the body
isn't a JSON object; signed `404` `not-supported` when `catalog` is off;
`500`.

## 3. Titles

`titles`, under the peer's base path. A paired peer reads which titles
the libraries it wants hold, a page at a time. It can ask only for what
changed since its last reading.

Request:

| Field | Type | Required | Content |
|-------|------|----------|---------|
| `libraries` | array of string | yes | library IDs; those not offered to the caller are ignored |
| `after` | string | no | the page starts after this title key; `""` for the first page; at most 512 bytes |
| `since` | integer | no | the `seq` of a former reading, to get only what changed; 0 or absent for the whole list; a negative one is answered like 0 |

Answer `200`:

| Field | Type | Content |
|-------|------|---------|
| `titles` | array of title | the page; absent counts as empty |
| `next` | string, optional | where the next page starts (pass it as `after`); absent after the last page |
| `changes` | boolean, optional | `true`: the answer holds only changes since `since` |
| `gone` | array of string, optional | with `changes`: title keys no longer held |
| `seq` | integer, optional | the receiver's catalog change number now; ask `since` it next time |

Title:

| Field | Type | Content |
|-------|------|---------|
| `key` | string | the title key (section 4) |
| `kind` | string | `movie`, `series`, `season` or `episode`: the kind its key names |
| `library` | string | one of the requested libraries that holds it: when several do, the one whose ID comes first in byte order |
| `audio` | array of string, optional | films and episodes only: its copies' audio languages, as language tags |
| `subtitles` | array of string, optional | films and episodes only: its copies' subtitle languages, as tags |
| `with` | array of string, optional | episodes only: the keys of the other episodes the same copy holds (section 4.3) |
| `ids` | object, optional | films, series and episodes: other identifiers of the same title, by scheme (section 4.4) |

**Language tags.** A tag uses the shortest code BCP 47 allows: the
ISO 639-1 code where one exists (`en`, `fr`), else ISO 639-2/T or 639-3
(`yue`), with a region when known (`fr-CA`), in the case conventions of
[core section 2.5](core.md#25-case). `und`, `mul`, `zxx` and `mis` are not
sent. Series and seasons carry no `audio` or `subtitles`.

### 3.1 Paging and ordering

- Titles come in ascending byte order of `key`. A page holds the titles
  with keys strictly greater than `after`.
- A page holds at most 5,000 titles. In a changes answer, `titles` and
  `gone` together hold at most 5,000 keys, taken in one byte order.
- In a whole-list answer, `next` is the last key of the page, and is set
  only when the page is full (5,000 titles).
- In a changes answer, `next` is set when there may be more changes after
  the page. A changes page may hold fewer than 5,000 titles and still
  have a `next`.
- The caller stops when `next` is absent, empty, or not greater than its
  `after`.

### 3.2 Whole list or changes

- The receiver answers with changes only when `since` is above 0, it
  still keeps its change log back to `since`, `since` isn't above its
  current `seq`, and what it offers the caller hasn't changed since
  `since`. Otherwise it answers with the whole list, whatever `since` was.
- A caller asks with `since` only when `libraries` is exactly the set of
  the reading that gave that `seq`; otherwise it asks for the whole list.
- The first page decides which kind of reading it is, and its `seq` is
  the one the caller keeps. Every later page of the same reading must
  have the same `changes` value. The caller treats a mix as a failure.
- After a whole-list reading, the caller drops every title of that peer
  it didn't see in the reading's pages. After a changes reading, it keeps
  `titles` (new or changed) and drops `gone`.
- A receiver that sends no `seq` gets asked for the whole list every
  time.
- `seq` is an opaque positive counter. Only the receiver gives it a
  meaning.
- A receiver should keep its change log at least 30 days. A caller should
  read every paired peer's titles at most every 30 minutes, and at once
  when what it wants of one changes; it should give a reading 5 minutes.

### 3.3 What the caller keeps of each title

Anything else is skipped, title by title:

- the key parses as a title key, is in canonical form (section 4), and its
  scheme is one the caller knows (`tmdb` in version 1);
- `kind` matches the kind the key names;
- `library` is one of the libraries it asked for;
- at most 12 language tags in each list, each 2 to 12 characters of
  `A–Z a–z 0–9 -`, each once (compared without case); a bad tag is
  skipped, not the whole title;
- at most 16 keys in `with`, each a valid episode key of the same series;
  a bad key is skipped;
- in `ids`, values of known schemes in their form (section 4.4); others
  are skipped;
- `gone` keys over 128 bytes are skipped.

Members of the wrong JSON type ([core section 2.3](core.md#23-json)):

- `titles` or `gone` that isn't an array, `next` that isn't a string,
  `changes` that isn't a boolean, or `seq` that isn't an integer fails
  the answer: the caller treats the peer as unreachable and keeps what it
  had. Skipping one of them could end a reading early or mix the kinds of
  reading, and the caller would then drop titles the peer still holds.
- An entry of `titles` that isn't an object, or whose `key`, `kind` or
  `library` isn't a string, is skipped.
- An `audio`, `subtitles` or `with` member that isn't an array, or an
  `ids` member that isn't an object, counts as absent; an entry of one
  of those lists that isn't a string is skipped alone, as is a value of
  `ids` that isn't in its scheme's form.
- An entry of `gone` that isn't a string is skipped.

Refusals: signed `404` when the caller isn't `paired`, or the body isn't
valid JSON, or `libraries` is missing or isn't an array of strings, or
`after` is over 512 bytes, or `since` isn't an integer;
signed `404` `not-supported` when `catalog` is off; `500`.

## 4. Title keys

Titles are named by their TMDB IDs, never by files, paths or the media
server's item IDs. A title key has three parts, joined by `/`: the kind
(`movie` or `series`), the scheme, and the identifier, followed for
seasons and episodes by their place in the series:

| Kind | Key | Example |
|------|-----|---------|
| film | `movie/tmdb/<id>` | `movie/tmdb/949` |
| series | `series/tmdb/<id>` | `series/tmdb/1399` |
| season | `series/tmdb/<id>/s<season>` | `series/tmdb/1399/s1` |
| episode, by TMDB episode ID | `series/tmdb/<id>/e<episode id>` | `series/tmdb/1399/e63056` |
| episode, by numbers | `series/tmdb/<id>/s<season>/e<episode>` | `series/tmdb/1399/s1/e2` |

- `<id>` is the TMDB ID of the film or the series, in decimal, without
  leading zeros: 1 to 9,999,999,999.
- `<season>` is `0` or 1 to 4 digits without a leading zero; season 0
  holds specials.
- `<episode>` is `0` or `[1-9][0-9]{0,4}`. Episode 0 is valid wherever
  TMDB numbers one (some seasons have a pilot or prologue as 0).
- `<episode id>` is TMDB's ID of the episode, 1 to 10 digits, above 0,
  without a leading zero.
- Keys are canonical: no leading zeros anywhere (`s1`, not `s01`). A key
  in another form is a different string, and the receiver skips it.
- A season is named by its series' ID and its number, never by TMDB's
  season ID.
- `play` takes only films and episodes ([playback](playback.md#2-play)).

The only scheme of version 1 is `tmdb`. A receiver skips keys of a
scheme it doesn't know. A later version of this part may admit keys of
other schemes, for titles TMDB lacks; its rules would say which scheme
wins when a title has several, so that every server picks the same key.

A title TMDB doesn't know is not sent.

### 4.1 Episode order

Season and episode numbers in keys are TMDB's: the `season_number` and
`episode_number` TMDB gives the episode in the series' own season list,
not in an episode group. An owning server whose files are numbered
another way (DVD, absolute, a broadcaster's order) maps them to TMDB's
numbering before it sends keys. When it can't, it leaves the episode out.

An episode TMDB lists is sent with the `e<episode id>` form. The
`s<season>/e<episode>` form is only for an episode TMDB doesn't list
(yet), in a season TMDB numbers; its numbers continue TMDB's numbering of
that season. A receiver matches it only against the same form.

The order a server shows its people is its own business and never
appears in keys.

### 4.2 Same title, same key

Two titles are the same when their keys are equal, byte for byte. A
viewer's server uses this to tell that a peer's title is one it already
has, or to carry watched state across.

### 4.3 Several episodes in one copy

A copy that holds several episodes is listed once per episode, each under
its own key. Each of those titles carries `with`: the keys of the other
episodes the same copy holds, in byte order, at most 16. `play` of any of
them plays that copy ([playback section 2.2](playback.md#22-what-the-owning-server-does)).

A receiver may use `with` to show "episodes 1–2" as one entry, and to
mark all of them watched together.

### 4.4 Other identifiers

Titles of kind `movie`, `series` and `episode` may carry `ids`: other
identifiers of the same title, by scheme.

| Scheme | Form | Example |
|--------|------|---------|
| `imdb` | `tt` and 7 to 10 digits | `tt0133093` |
| `tvdb` | 1 to 10 digits, no leading zero | `81189` |

Example: `"ids":{"imdb":"tt0133093"}`.

- Each value is a string. Unknown schemes are ignored. A value that
  breaks its form is ignored.
- `ids` never replaces the key: two titles are the same when their keys
  are equal. `ids` only helps a receiver find a title it holds under
  another identifier.
- An `imdb` value names the film or series; an episode's `ids` carry its
  own IMDb or TVDB ID when known.

## 5. What is shared

The owning server decides alone. The viewer's server can't widen
anything.

- Only titles in libraries it offers that peer, and only those the peer
  asked for. `titles` ignores other library IDs.
- A server offers only its own libraries, never what it got from another
  peer.
- Of the owning server, a peer never learns files, paths or its media
  server's item IDs, not even inside library IDs (section 2.1) or version
  IDs ([playback section 2.3](playback.md#23-the-answer)).

## 6. Security considerations

- **A compromised peer** can make the other store a long title list, and
  look those titles up at TMDB. Readers cap what they keep (section 3.3)
  and should cap the total per peer.
- **Hostile answers.** Treat every name and key as untrusted input: clean
  names, parse keys strictly, never show text as markup.
- **Library IDs** give a peer nothing about the owning server's layout
  (section 2.1). The same holds of every ID the parts define.

## 7. Open questions

None of these is decided. Where a proposal of 2026-11-16 left a point
open, the text above follows the proposal's own default.

1. **Paging.** A whole-list reading whose size is a multiple of 5,000 ends
   with one empty page.
2. **How often a library ID may change** (proposal 2, open point 2).
   Section 2.1 says "stable" and "never reused"; a cap (for example "only
   when the library is removed") would be hard to check.
3. **One rule for every identifier** (proposal 2, open point 3). Rather
   than one rule for library IDs here and one for version IDs in
   [playback](playback.md#23-the-answer), the specification could state
   once that every identifier an owning server sends is opaque, and list
   them.
4. **Series TMDB numbers differently** (proposal 5, open point 1). Series
   that exist in TMDB only as one long season while files use real
   seasons (or the reverse), common for anime: section 4.1 says "map, or
   leave out". Is leaving out acceptable, or should the numbers form be
   allowed with the owning server's numbering, marked as such?
5. **IMDb episode IDs** (proposal 5, open point 2). Section 4.4 lets an
   episode carry its own `imdb` ID. Should `ids` stay at film and series
   level instead?
6. **The cap of 16 for `with`** (proposal 5, open point 3).
