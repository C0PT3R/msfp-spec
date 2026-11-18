# MSFP version 1: the video part, version 1

**Draft.**

The `video` part shares films and series, named by their TMDB IDs. It is
a content part: it has no calls of its own, and says what the shared
parts carry for films and series: the title kinds and keys in
[catalog](catalog.md), what [playback](playback.md)'s `play` takes and
answers, and the subtitles and preview sheets [media](media.md) serves.
It needs the [core](core.md), `catalog`, `playback` and `media`; if any
of them is off between two servers, `video` is off too
([core section 10](core.md#10-versions-and-parts)). A server lists
`video` in `hello` only when it shares or plays films and series.

The words "must", "must not" and "should" carry their usual meaning in
specifications.

## Contents

1. [Terms](#1-terms)
2. [Libraries](#2-libraries)
3. [Titles](#3-titles)
4. [Title keys](#4-title-keys)
5. [Playing a film or an episode](#5-playing-a-film-or-an-episode)
6. [Media](#6-media)
7. [Security considerations](#7-security-considerations)
8. [Open questions](#8-open-questions)

## 1. Terms

- **Video title**: a film, a series, a season or an episode.
- **Title key**: here, the text that names a video title (section 4).
  The general rules of title keys are in
  [catalog section 4](catalog.md#4-title-keys).
- **Scheme**: the source of the identifier in a title key. `video` 1 has
  one, `tmdb` (The Movie Database).

## 2. Libraries

A `movies` library holds films; a `tvshows` library holds series, their
seasons and episodes. A `mixed` library may hold them beside titles of
other content parts. A receiver that speaks `video` reads them from
`titles` ([catalog section 3](catalog.md#3-titles)), in the same paging
and the same changes.

## 3. Titles

A video title in `titles` carries the members of
[catalog section 3](catalog.md#3-titles), and these:

| Field | Type | Content |
|-------|------|---------|
| `kind` | string | `movie`, `series`, `season` or `episode`: the kind its key names |
| `audio` | array of string, optional | films and episodes only: its copies' audio languages, as language tags ([catalog section 3](catalog.md#3-titles)) |
| `subtitles` | array of string, optional | films and episodes only: its copies' subtitle languages, as tags |
| `video` | object, optional | films and episodes only: what its best copy offers for playing (section 3.2) |
| `with` | array of string, optional | episodes only: the keys of the other episodes the same copy holds (section 4.2) |
| `ids` | object, optional | films, series and episodes: other identifiers of the same title, by scheme (section 4.3) |

Series and seasons carry no `audio`, `subtitles` or `video`.

A change of any of these members (a new `ids` value, or another `video`,
say) is a change of the title: a changes reading sends it again
([catalog section 3.2](catalog.md#32-whole-list-or-changes)).

### 3.1 What the caller keeps

Besides the rules of [catalog section 3.3](catalog.md#33-what-the-caller-keeps-of-each-title):

- the key's scheme is one the caller knows (`tmdb` in `video` 1);
- at most 12 language tags in each list, each 2 to 12 characters of
  `A–Z a–z 0–9 -`, each once (compared without case); a bad tag is
  skipped, not the whole title;
- at most 16 keys in `with`, each a valid episode key of the same series;
  a bad key is skipped;
- in `ids`, values of known schemes in their form (section 4.3); others
  are skipped.

Members of the wrong JSON type ([core section 2.3](core.md#23-json)): an
`audio`, `subtitles` or `with` member that isn't an array, or an `ids`
member that isn't an object, counts as absent; an entry of one of those
lists that isn't a string is skipped alone, as is a value of `ids` that
isn't in its scheme's form.

Of `video` (section 3.2), for films and episodes only:

- a `video` that isn't an object counts as absent, as does one whose
  `height` is missing or isn't one of the six values of section 3.2 as an
  integer ([core section 2.3](core.md#23-json): `1080.0` and `"1080"`
  aren't), or whose `hdr` is present and isn't an array;
- in `hdr`, an entry that isn't a string, or isn't one of `hdr10`, `hlg`
  and `dv`, is skipped alone, as is a repeat; the caller keeps the rest
  in that order (`hdr10`, `hlg`, `dv`), and an `hdr` left empty means
  standard range;
- other members of `video` are ignored;
- the caller keeps `video` with the title, and shows it as it likes (it
  describes the title, not a copy: no version is named).

Test cases: `titles` in
[vectors/v1/video.json](../../vectors/v1/video.json), each with what the
caller keeps.

### 3.2 The picture

`video` says what a film's or an episode's picture looks like when it is
played, so that a viewer's server can tell its people before they play
it:

| Field | Type | Content |
|-------|------|---------|
| `height` | integer | the picture's height, stepped: 480, 720, 1080, 1440, 2160 or 4320 |
| `hdr` | array of string, optional | its high dynamic range formats: `hdr10`, `hlg`, `dv` (Dolby Vision); absent for standard range |

Example: `"video": {"height": 2160, "hdr": ["hdr10", "dv"]}`.

- **`height`** is the picture's height in pixels or, for a picture wider
  than 16:9, the height of a 16:9 picture as wide (a 3840 × 1600 film
  counts as 2160, a 1920 × 800 one as 1080). It is stepped down as
  `maxHeight` is (section 5.1): to the greatest of the six values not
  above it, and 480 below 480.
- **`hdr`** lists each format the copy offers, each once, in that order:
  `hdr10` for HDR10 and HDR10+, `hlg` for HLG, `dv` for Dolby Vision,
  with its base layer's format besides (Dolby Vision on an HDR10 base is
  `["hdr10", "dv"]`; on a standard-range base, `["dv"]`). A format
  outside the list isn't sent; a copy whose only formats are outside it
  is sent as standard range.
- **The best copy.** With several copies, `video` describes the best:
  the one `play` without `versionId` would choose for the most capable
  device, one that plays every size and format. The best copy is the
  one of the greatest height, then the one with HDR before one without,
  then the one with more formats. The owning server lists the title's
  copies in that order, best first, so that `play` without `versionId`
  and without an `audioLanguage` that another copy matches plays it
  ([playback section 2.6](playback.md#26-choosing-the-copy-and-the-tracks)).
  A viewer whose language only a lesser copy has gets that copy.
- A copy whose picture size the owning server doesn't know doesn't
  count; when it knows none, it leaves `video` out.

`video` says what the copy is, not how it reaches a viewer: a device
that can't play it gets it converted
([playback section 2.6](playback.md#26-choosing-the-copy-and-the-tracks)).

**Overfin.** As an owning server, Overfin takes each copy's size and
range from its file's video stream, as the media server reports it
(`HDR10` and `HDR10Plus` are `hdr10`, `HLG` is `hlg`, the `DOVI` kinds
`dv` with their base layer's format; a stream said only to be HDR,
without its kind, is `hdr10`, which is what Overfin's index knows of its
files today), and lists a title's copies best first. As a viewer's server, it keeps `video` with the peer's title and
shows it on the title's page, with the languages the peer sent, when
that peer is where the title would play from.

## 4. Title keys

Films and series are named by their TMDB IDs, never by files, paths or
the media server's item IDs. A video title key has three parts, joined by
`/`: the kind (`movie` or `series`), the scheme, and the identifier,
followed for seasons and episodes by their place in the series:

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
- `play` takes only films and episodes (section 5).

The only scheme of `video` 1 is `tmdb`. A receiver skips keys of a
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

### 4.2 Several episodes in one copy

A copy that holds several episodes is listed once per episode, each under
its own key. Each of those titles carries `with`: the keys of the other
episodes the same copy holds, in byte order, at most 16. `play` of any of
them plays that copy (section 5.2).

A receiver may use `with` to show "episodes 1–2" as one entry, and to
mark all of them watched together.

### 4.3 Other identifiers

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
  are equal ([catalog section 4.1](catalog.md#41-same-title-same-key)).
  `ids` only helps a receiver find a title it holds under another
  identifier.
- A film's or series' `imdb` names it; an episode's names the episode.

## 5. Playing a film or an episode

`play` ([playback section 2](playback.md#2-play)) takes the key of a
film or an episode. Everything [playback](playback.md) says holds; this
section adds the members and rules that only films and episodes have.

### 5.1 The request

Members added to the request of
[playback section 2.1](playback.md#21-the-request):

| Field | Type | Required | Content |
|-------|------|----------|---------|
| `subtitleLanguage` | string | no | the viewer's subtitle language, a tag; at most 12 characters of `A–Z a–z 0–9 -` |
| `subtitleTrack` | string | no | a subtitle track ID, `s` and a number from 0 to 999 without leading zeros (`s01` is invalid), or `off` |

Capabilities added to the capabilities object (all optional; unknown
values are ignored):

| Field | Type | Values |
|-------|------|--------|
| `videoCodecs` | array of string | `h264`, `hevc`, `av1`, `vp8`, `vp9` |
| `hdr` | array of string | `hdr10`, `hlg` |
| `maxHeight` | integer | pixels, 0 to 100,000; 0 means not said; a negative or larger value is refused (`400`) |
| `subtitles` | array of string | no values are defined yet; send `[]` or leave it out |

**Coarsening**, besides playback section 2.1's: `maxHeight` stepped down
to 480, 720, 1080, 1440, 2160 or 4320 (below 480 becomes 480).

**Nothing said.** Nothing said about `containers` or `videoCodecs`: no
file is played as it is (`direct`); the owning server remuxes or
transcodes to H.264 and AAC in HLS, which every viewer's server must be
able to play. Nothing said about `audioCodecs`: AAC only. Nothing said
about `hdr`: standard range only.

The owning server refuses (`400`) a malformed `subtitleTrack`, at the
step where it refuses a malformed `audioTrack`
([playback section 2.2](playback.md#22-what-the-owning-server-does),
step 4).

### 5.2 Several episodes in one copy

(Section 4.2.) `play` of any of the episodes a copy holds plays that
copy. Without `startPositionMs` (or with 0), the owning server starts at
the episode's beginning when it knows where that is, else at the copy's
beginning. A non-zero `startPositionMs` is a position in the copy, as for
any other title. The answer's `positionMs` says where it started, in the
copy, and the viewer's server must start there.

Progress is per episode key. The playback is of the episode whose key
`play` named; its `progress` and `stop` give `positionMs` as a position
in the copy, not in that episode, and the viewer's server keeps the
viewer's progress under that episode's key, with that position in the
copy.

### 5.3 The answer

Members added to the playback object of
[playback section 2.3](playback.md#23-the-answer). The viewer's server
checks and cleans every field, as listed.

| Field | Type | Content | What the viewer's server requires or does |
|-------|------|---------|-------------------------------------------|
| `subtitleTracks` | array of track, optional | the subtitle tracks | `url` checked (section 6.1) |
| `subtitleTrack` | string, optional | the one to show, `s<n>` | |
| `forcedTracks` | array of track, optional | forced subtitles | `url` checked |
| `forcedTrack` | string, optional | the forced one matching the audio | |
| `subtitleStretchSeconds` | integer, optional | 120 when there are subtitles | replaced by its own value, 120 |
| `segments` | array, optional | skip markers `{kind, startMs, endMs}` | kinds `intro`, `outro`, `recap`, `preview`, `commercial`; within 100 days; at most 32 kept |
| `trickplay` | trickplay object, optional | the seek-bar previews of the copy playing (section 5.5) | sheet URLs checked (section 6.1); out of bounds: dropped |

A subtitle track is a track of playback section 2.3, with the ID
`s<n>`, and these members besides:

| Field | Type | Content |
|-------|------|---------|
| `pictures` | boolean, optional | the subtitles are pictures (PGS) |
| `url` | string, optional | where to fetch them (section 6.1) |

### 5.4 Choosing the subtitles

The owning server chooses the subtitles after the copy and the audio
([playback section 2.6](playback.md#26-choosing-the-copy-and-the-tracks)),
before how to serve it.

**The subtitles.** Subtitles are never burned into the video: they never
make a playback transcode, and the choice only says which track to show.

| `subtitleTrack` | `subtitleLanguage` | `subtitleTrack` in the answer |
|-----------------|--------------------|-------------------------------|
| `off` | any (ignored) | absent: none shown |
| a track of the copy | any (ignored) | that track |
| not a track of the copy | any | as if `subtitleTrack` were absent |
| absent | a track matches | that track |
| absent | absent, or no track matches | absent: none shown |

When `subtitleLanguage` matches both a regular track and a forced one,
the regular track is the one chosen; the forced one is still
`forcedTrack`, as below. Whatever is chosen, `forcedTrack` is the forced
track in the language of the audio played, when the copy has one. Every text and PGS subtitle
track is listed, whichever is shown; picture formats other than PGS are
not listed.

### 5.5 Seek-bar previews

Trickplay: thumbnails of the video every `intervalMs`, laid out in a grid
on JPEG images called sheets. Each sheet holds `columns` × `rows` tiles,
each `tileWidth` × `tileHeight` pixels, read left to right, then top to
bottom. Tile *t* (from 0) shows the video at *t* × `intervalMs`, and is
tile *t* mod (`columns` × `rows`) of sheet ⌊*t* / (`columns` × `rows`)⌋.
The last sheet may hold fewer tiles, and may be shorter or narrower than
a full sheet.

| Field | Type | Content | Bounds |
|-------|------|---------|--------|
| `tileWidth` | integer | a tile's width, pixels | 1 to 2,048 |
| `tileHeight` | integer | a tile's height, pixels | 1 to 2,048 |
| `columns` | integer | tiles across a sheet | 1 to 100 |
| `rows` | integer | tiles down a sheet | 1 to 100 |
| `intervalMs` | integer | milliseconds between two tiles | 100 to 3,600,000 |
| `tileCount` | integer | tiles in all | 1 or more |
| `sheets` | array of string | sheet *n*'s URL at index *n* (section 6.1) | exactly ⌈`tileCount` / (`columns` × `rows`)⌉ entries, at most 1,000 |

Besides those bounds, a full sheet is at most 4,096 pixels each way:
`columns` × `tileWidth` ≤ 4,096 and `rows` × `tileHeight` ≤ 4,096.

- The owning server sends `trickplay` only when it has previews for the
  copy playing, within these bounds. It sends one set, not one per width;
  a set near 320 pixels wide is a good choice. Without previews, it leaves
  the field out.
- The viewer's server drops `trickplay`, and plays on without previews,
  when a number is missing or out of bounds, or when `sheets` has another
  number of entries. It refuses the whole answer (it sends `stop` and
  gives up, as [playback section 2.3](playback.md#23-the-answer) says)
  when a sheet URL isn't the one section 6.1 gives for its index, or when
  a field has another JSON type than this table says.
- Both sides may leave previews out: an owning server need not send
  `trickplay`, and a viewer's server that offers no previews ignores it.
- The viewer's server never hands the owning server's URLs to the viewer:
  it serves each sheet at an address of its own, fetched as section 6.2
  says.

## 6. Media

What [media](media.md) says holds. This section adds the URLs and the
answers of subtitles and preview sheets.

### 6.1 The URLs

Under the owning server's stream root
([media section 1](media.md#1-the-urls)):

- Subtitle and forced tracks carry a `url` of the form
  `<stream root><ticket>/subtitles/<track>` for text, or
  `<stream root><ticket>/pictures/<track>` for PGS, where `<track>` is the
  track ID.
- `trickplay.sheets[n]` is exactly `<stream root><ticket>/trickplay/<n>`,
  with the stream's own `<ticket>` and `<n>` the entry's index in
  decimal, without leading zeros: `sheets[0]` ends in `/trickplay/0`,
  `sheets[1]` in `/trickplay/1`, and so on.

The viewer's server checks these URLs as media section 1 says: `<track>`
matches the same pattern as `<name>`.

### 6.2 What is fetched

- **Text subtitles.** Fetch `<track url>/<part>`, where `<part>` is a
  decimal integer from 0 to 9,999 without leading zeros. Part *n* covers
  the video from *n* × 120 to (*n* + 1) × 120 seconds, and starts 10
  seconds early, so a line already on screen comes along; drop the
  doubles. The answer is WebVTT, at most 5 MiB, in the form of
  section 6.3.
- **PGS subtitles.** Fetch `<track url>/<part>` the same way. The answer
  is the stretch's PGS data, `application/octet-stream`, at most 64 MiB,
  checked as section 6.4 says. A stretch with no subtitles is a `200`
  with an empty body (no segments), and the viewer's server relays it as
  such: a `200` with an empty body.
- **Preview sheets.** Fetch `trickplay.sheets[n]` (section 5.5), the same
  plain `GET` with the playback's ticket, no `Range`. The owning server
  answers `404` for a sheet number at or past the sheet count, one with
  leading zeros, a query string, or a ticket not live
  ([media section 4](media.md#4-how-long-a-ticket-works)). The answer is
  `200`, `Content-Type: image/jpeg`, a JPEG of at most 8 MiB, no wider
  than `columns` × `tileWidth` and no taller than `rows` × `tileHeight`
  pixels. The owning server should re-encode every sheet before sending
  it. A viewer's server may fetch the sheets when the playback starts or
  when the viewer needs them; the fetches count as media requests for
  media section 4.

The viewer's server checks again everything it relays, as
[media section 3](media.md#3-what-is-fetched) says, and besides:

- WebVTT rebuilt as section 6.3 says, PGS checked whole as section 6.4
  says; whatever fails is a failed fetch
  ([media section 2.3](media.md#23-statuses)), answered `404` to the
  viewer;
- a preview sheet is read whole, refused past 8 MiB, then checked from its
  header, before decoding, to be a JPEG (by its content, whatever its
  `Content-Type`) within the size above; any other is refused. It is
  re-encoded as JPEG, so that only its pixels reach the viewer, and
  served at the viewer's server's own playback route, to the viewer
  playing it only. A viewer's server should bound how many sheets it
  reads at once (for example 4).

The viewer's server sets the `Content-Type` of what it relays itself:
`text/vtt; charset=utf-8` for WebVTT, `application/octet-stream` for PGS,
`image/jpeg` for sheets.

Test cases for sections 6.3 and 6.4 are in
[vectors/v1/media.json](../../vectors/v1/media.json).

### 6.3 WebVTT

A WebVTT part is rebuilt, not filtered: only cue timings and plain cue
text survive. The owning server applies these rules to what it serves,
and the viewer's server applies them again to what it relays.

**Reading.**

1. A part over 5 MiB (5,242,880 bytes) is refused.
2. Each carriage return and line feed pair becomes a line feed, then each
   remaining carriage return becomes a line feed. One byte order mark
   (U+FEFF) at the start is removed.
3. The text must start with `WEBVTT`; otherwise the part is refused.
4. The text is cut into blocks at each pair of line feeds (an empty line).
   A line of spaces is not empty. Line feeds at the start and end of a
   block are removed.
5. In each block, the first line that is a timing line, once white
   space (Unicode's `White_Space`) at both ends is removed, starts a cue. The lines before it (the
   header, a cue identifier) are dropped. A block without a timing line
   is dropped whole: the header, `NOTE`, `STYLE`, `REGION`, or anything
   malformed.
6. A timing line is: a timestamp, one or more spaces, tabs or form
   feeds, `-->`, one or more of them again, a timestamp, then optionally
   one of them and anything. A timestamp is
   `[<hours>:]<minutes>:<seconds>.<milliseconds>`: 1 to 3 digits of
   hours, exactly 2 of minutes, 2 of seconds, 3 of milliseconds. What
   follows the second timestamp (the cue settings) is dropped.
7. Every line after the timing line, up to the end of the block, is a cue
   text line, even one shaped like a timing line. Each is cleaned (below).
   A line empty after cleaning is dropped. A cue with no line left is
   dropped.
8. More than 50,000 cues left refuses the part.

**Cleaning a cue text line.**

1. Remove invalid UTF-8, U+FFFD, and the direction controls U+061C,
   U+200E, U+200F, U+202A to U+202E and U+2066 to U+2069.
2. Remove tags. A tag starts at a `<` followed by a letter (any script),
   `/`, `!` or `?`, and ends at the next `>`; the tag becomes one space.
   A tag with no `>` removes the rest of the line. A `<` followed by
   anything else stays (`a < b`, `<3`).
3. Decode character references as HTML does in text: named (`&amp;`,
   `&nbsp;`…), decimal (`&#60;`) and hexadecimal (`&#x3c;`).
4. Do steps 1 and 2 again, so that `&lt;b&gt;` can't come back as a tag.
5. Turn each control character and each white space character
   (Unicode's `White_Space`) into a space. Collapse runs of spaces into
   one, and remove spaces at both ends.
6. Cut the line to at most 500 bytes without splitting a character, then
   remove spaces at its end.
7. Escape `&` as `&amp;`, `<` as `&lt;` and `>` as `&gt;`.

So no markup survives: not `<b>`, `<i>`, `<u>`, `<c>`, `<v>`, `<lang>`,
`<ruby>` or `<rt>`, nor their classes and annotations (a voice's name, a
language); their text does. Unknown tags go the same way. There is no
CSS, since `STYLE` blocks are dropped and nothing else can hold any. A
URL in cue text stays as text, and nothing is ever fetched for a part.
A timestamp tag (`<00:00:01.000>`) starts with a digit: it isn't a tag
under step 2, and stays as escaped text.

**Writing.** The part is `WEBVTT` and a line feed, then for each cue, in
the order read: a line feed, the two timestamps as they were written,
joined by ` --> `, a line feed, and the cleaned lines, each followed by a
line feed. UTF-8, line feeds only, no byte order mark. A part with no cue
left is `WEBVTT` and a line feed: it is valid. The answer's
`Content-Type` is `text/vtt; charset=utf-8`.

Not checked: that minutes and seconds are below 60, that a cue ends after
it starts, that cues are in order, and how many lines a cue has. Players
handle those.

**Overfin.** These are Overfin's rules, as both owning and viewer's
server.

### 6.4 PGS

A PGS part is checked whole, then served unchanged: a player decodes and
draws it. Checking means reading every segment, and decoding every
object's run-length data to count it, not to draw it.

**The track.** A part is at most 64 MiB (67,108,864 bytes), made of
segments one after another, up to its exact end. An empty part, of no
bytes and no segments, is valid: it is the answer for a stretch with no
subtitles, the smallest there is (no display set). A segment is a
13-byte header and a payload:

| Bytes | Content |
|-------|---------|
| 0–1 | `PG` |
| 2–9 | presentation and decoding times (not checked) |
| 10 | the segment's type |
| 11–12 | the payload's size, big-endian |

A header cut short, another magic, or a payload past the end refuses the
part. So does any type but these five:

| Type | Segment | Checks on its payload |
|------|---------|-----------------------|
| `0x16` | presentation (PCS) | at least 11 bytes; the screen's width (bytes 0–1) and height (2–3) are each 1 to 4,096; byte 10 counts composition objects, each 8 bytes, or 16 when its byte 3 has bit `0x80` (cropped); all of them within the payload |
| `0x17` | window (WDS) | at least 1 byte; exactly 1 + 9 × byte 0 bytes |
| `0x14` | palette (PDS) | at least 2 bytes; 2 + 5 × *n* bytes |
| `0x15` | object (ODS) | below |
| `0x80` | end | empty |

**Objects.** An object segment is at least 4 bytes: the object's ID
(bytes 0–1), a version (byte 2, not checked), flags (byte 3).

- Bit `0x80` of the flags marks the object's first fragment. It is at
  least 11 bytes; bytes 7–8 are the width and 9–10 the height, each 1 to
  4,096; bytes 11 on are run-length data. Bytes 4–6 (the data's length)
  are not checked. A part holds at most 20,000 first fragments. A first
  fragment with an ID already open starts that object again.
- Without bit `0x80`, the segment continues an open object of the same ID;
  bytes 4 on are more data. No open object of that ID refuses the part.
- Bit `0x40` marks the last fragment (it may be the first too). The
  object's data, all its fragments together, must then fit its size, and
  the object is closed.

An object left open at the end of the part doesn't refuse it.

**Run-length data fits** when, read from the start:

- a byte other than 0 is one pixel;
- `0x00 0x00` ends a line: the next pixel is at the start of the next
  line; more than *height* line ends refuses it;
- `0x00` then a flag byte *F* is a run: its length is *F* & `0x3F`, or,
  when *F* has bit `0x40`, (*F* & `0x3F`) × 256 plus the next byte; when
  *F* has bit `0x80`, a color byte follows;
- a run cut short by the end of the data refuses it;
- after each pixel or run, more than *width* pixels on the line refuses
  it.

Not checked: segments' times and order, that each display set ends with
an end segment, IDs across segments, positions against the screen,
palette entries and colors, lines shorter than *width* or fewer than
*height*. A player must be robust to those itself.

**Memory.** Nothing here makes a picture: the check keeps only the open
objects' data, which the part's 64 MiB bounds. A player that draws a
picture needs at most 4,096 × 4,096 pixels for it, and the screen as big.

**Overfin.** These are Overfin's rules, as both owning and viewer's
server, an empty part included. It accepts only PGS as picture subtitles; other picture formats
(DVD, DVB) are left out of the track list.

## 7. Security considerations

- **TMDB.** A video title carries a key only: a viewer's server looks its
  names and pictures up at TMDB. A compromised peer can make it look up
  a long title list; readers cap what they keep
  ([catalog section 6](catalog.md#6-security-considerations)).
- **Preview sheets are images from another server**, the only ones a peer
  sends. Check a sheet's byte size first, then its dimensions from its
  header against the layout, and only then decode it. Re-encode it, so
  nothing but pixels (no metadata, no trailing bytes, no second image)
  reaches a browser. The layout's bounds keep the number of fetches, and
  the memory a sheet takes, small: at most 1,000 sheets of 4,096 × 4,096
  pixels. Never give the browser the peer's sheet URLs: they carry the
  ticket, and would let the peer see the viewer.
- **Hostile subtitles.** Rebuild WebVTT and check PGS before relaying
  them (sections 6.3 and 6.4).

## 8. Open questions

Points 1 to 3 were settled by the owner on 2026-11-17; point 4 is open.
Where a proposal of 2026-11-16 left a point open, the text above follows
the proposal's own default.

1. **Series TMDB numbers differently** (proposal 5, open point 1). Series
   that exist in TMDB only as one long season while files use real
   seasons (or the reverse), common for anime: section 4.1 says "map, or
   leave out". Is leaving out acceptable, or should the numbers form be
   allowed with the owning server's numbering, marked as such?
   **Settled:** map, or leave out; to look at again if implementations
   show it leaves out too much (anime).
2. **IMDb episode IDs** (proposal 5, open point 2). Section 4.3 lets an
   episode carry its own `imdb` ID. Should `ids` stay at film and series
   level instead?
   **Settled:** episodes keep their own `imdb` ID.
3. **The cap of 16 for `with`** (proposal 5, open point 3).
   **Settled:** 16, kept.
4. **Descriptions for video too**
   ([proposal 11](../../proposals/0011-music.md), open point 2;
   [music open question 2](music.md#8-open-questions)). Video titles
   carry keys only; optional names would let a viewer's server list a
   peer's titles without TMDB
   ([core open question 26](core.md#18-open-questions)).

Choices confirmed by the owner on 2026-11-17, moved here from
[playback](playback.md#8-open-questions) and [media](media.md#6-open-questions)
(they may still change as implementations show):

5. **`startPositionMs` with several episodes in one copy** (section 5.2).
   Proposal 5 says where a playback of a later episode starts, but not how
   `startPositionMs` combines with it. This draft reads a non-zero
   `startPositionMs` as a position in the copy.
6. **Timestamp tags in WebVTT** stay as escaped text (section 6.3), as
   Overfin does. Removing them would suit karaoke-style subtitles better.
7. **Checks left to the player**: WebVTT timings out of range or order,
   and PGS fields beyond sizes (sections 6.3 and 6.4). An open PGS object
   at the end of a part isn't refused.

**Choices this draft made, confirmed by the owner on 2026-11-17** (when the video rules were moved
out of `catalog`, `playback` and `media` on 2026-11-17):

8. **The WebVTT and PGS vectors stay in
   [vectors/v1/media.json](../../vectors/v1/media.json)**, a file named
   for the part that held these rules before, rather than in a new file
   for `video`.

**Decided by the owner on 2026-11-18.**

9. **What the picture looks like** (section 3.2). Films and episodes
   carry an optional `video`, the stepped height and HDR formats of the
   best copy, so that a viewer's server can describe a peer's title
   before it is played. A change of it is a change of the title
   ([catalog section 3.2](catalog.md#32-whole-list-or-changes)).
   Its test cases, with the rest of what a caller keeps of a video title
   (section 3.1), are in a file of their own,
   [vectors/v1/video.json](../../vectors/v1/video.json); the WebVTT and
   PGS cases stay where point 8 says.
