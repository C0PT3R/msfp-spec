# MSFP version 1: the music part, version 1

**Draft.**

The `music` part shares artists, albums and tracks, named by their
MusicBrainz identifiers. It is a content part: it has no calls of its
own, and says what the shared parts carry for music: the title kinds,
keys and descriptions in [catalog](catalog.md), and what
[playback](playback.md)'s `play` takes and answers for a track. It needs
the [core](core.md), `catalog`, `playback` and `media`; if any of them is
off between two servers, `music` is off too
([core section 10](core.md#10-versions-and-parts)). A server lists
`music` in `hello` only when it shares or plays music. It comes from
[proposal 11](../../proposals/0011-music.md).

The words "must", "must not" and "should" carry their usual meaning in
specifications.

## Contents

1. [Terms](#1-terms)
2. [Title keys](#2-title-keys)
3. [What a title carries](#3-what-a-title-carries)
4. [Pictures](#4-pictures)
5. [Playing a track](#5-playing-a-track)
6. [Libraries](#6-libraries)
7. [Security considerations](#7-security-considerations)
8. [Open questions](#8-open-questions)

## 1. Terms

- **MBID**: a MusicBrainz identifier, the lowercase UUID MusicBrainz
  gives an artist, a release group, a release, a recording or a track.
- **Music title**: an artist, an album or a track.
- **Album**: a release group: every edition of one album (a remaster, a
  country's pressing).
- **Track**: a recording: one performance, wherever it appears.
- **Scheme**: `music` 1 has one, `mb` (MusicBrainz).

Tagging tools write the recording MBID in the tag named "MusicBrainz
Track Id", and the release track's in "MusicBrainz Release Track Id":
`track/mb/…` takes the first, `mbtrack` the second. Media servers name
their fields after the tags, so the two are easily confused.

## 2. Title keys

Three kinds of title, named by MBIDs:

| Kind | Key | MBID of |
|------|-----|---------|
| artist | `artist/mb/<mbid>` | the artist |
| album | `album/mb/<mbid>` | the **release group** |
| track | `track/mb/<mbid>` | the **recording** |

- An album is a release group, not a release: two servers holding
  different editions of the same album (a remaster, a country's
  pressing) have the same album. The edition a copy is goes in `ids`
  (section 3.1).
- A track is a recording: the same performance on an album and on a
  compilation is one track, so a viewer's server knows that it already
  has it. A live version or a remix is another recording, so another
  track.
- `<mbid>` is 36 characters, `[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`,
  lowercase. Any other form is a different string, and the receiver
  skips it.
- A track without a recording MBID is not sent, as a film without a
  TMDB ID isn't. An album or an artist without one is not sent either;
  its tracks may be.
- `play` takes only tracks.

A title's `kind` in `titles` is `artist`, `album` or `track`: the kind
its key names. Test cases: `keys` in
[vectors/v1/music.json](../../vectors/v1/music.json).

## 3. What a title carries

Video titles carry keys only: the viewer's server looks names and
pictures up in TMDB. Music can't work that way. At one request a second,
a library of 20,000 tracks would take more than five hours of
MusicBrainz lookups on every peer that reads it, and MusicBrainz would
be asked the same thing by every server of a federation. So **music
titles carry their own description**, from the owning server, beside the
members of [catalog section 3](catalog.md#3-titles):

| Field | Kinds | Content |
|-------|-------|---------|
| `name` | all | the title's name, text, at most 256 characters |
| `artists` | album, track | the artist keys credited, in order, at most 16 |
| `artistNames` | album, track | the credited names as written (`"Simon & Garfunkel"`), at most 512 characters |
| `album` | track | the album key it is on, when the owning server knows it |
| `disc`, `number` | track | its place on the album: 1 to 999 each |
| `year` | album, track | the year of the edition held, 1000 to 9999 |
| `durationMs` | track | its length, 0 to 86,400,000 |
| `ids` | all | other identifiers (section 3.1) |

These are untrusted text, cleaned as
[core section 9.1](core.md#91-pair) cleans a server's name (with the
lengths above instead of 80), and never more than a label: two titles are
the same when their keys are equal, whatever their names
([catalog section 4.1](catalog.md#41-same-title-same-key)). A viewer's
server may replace them with its own data for keys it knows.

Example:

```json
{"key":"track/mb/0c000000-0000-4000-8000-000000000003","kind":"track","library":"m1","name":"The Boxer","artists":["artist/mb/0a000000-0000-4000-8000-000000000001"],"artistNames":"Simon & Garfunkel","album":"album/mb/0b000000-0000-4000-8000-000000000002","disc":1,"number":2,"year":1970,"durationMs":308000}
```

(The MBIDs of this example and of the test vectors are made up.)

### 3.1 Other identifiers

| Scheme | Kinds | Form |
|--------|-------|------|
| `mbrelease` | album, track | the release MBID of the edition the copy comes from |
| `mbtrack` | track | the MBID of the track on that release |
| `isrc` | track | an ISRC, 12 characters `[A-Z]{2}[A-Z0-9]{3}[0-9]{7}` |

As in [video section 4.3](video.md#43-other-identifiers), `ids` never
replaces the key.

### 3.2 What the caller keeps

Besides the rules of [catalog section 3.3](catalog.md#33-what-the-caller-keeps-of-each-title),
title by title:

- `name`, `artistNames`: cleaned as above. A title without a `name`, or
  whose `name` is empty once cleaned, is skipped; an `artistNames` empty
  once cleaned counts as absent.
- `artists`: each entry a valid artist key (section 2), each once; a bad
  or repeated entry is skipped; at most 16 kept, the first.
- `album`: a valid album key; any other counts as absent.
- `disc`, `number`, `year`, `durationMs`: integers in the ranges above;
  any other counts as absent. A `durationMs` of 0 counts as absent too.
- `ids`: values of known schemes in their form, for the kinds the table
  of section 3.1 gives; others are skipped. MBIDs there have the form of
  section 2.
- A member the table gives for other kinds than the title's (an `album`
  on an album) is ignored.

Members of the wrong JSON type ([core section 2.3](core.md#23-json)):
each counts as absent; an entry of `artists` that isn't a string is
skipped alone, as is a value of `ids` that isn't a string.

Test cases: `titles` in
[vectors/v1/music.json](../../vectors/v1/music.json), each with what the
caller keeps.

## 4. Pictures

Album art comes from the **Cover Art Archive**, fetched by the viewer's
server itself, as it fetches TMDB's pictures for films: by the album key's
release group (`/release-group/<mbid>/front`), or by the release in
`mbrelease` when the edition's own cover is wanted. Sizes 250, 500 and
1200 pixels exist. The Archive states no rate limit (checked 2026-11-17)
but may answer `503`; a viewer's server caches each cover. The owning server sends no picture. An album
whose release has no art there shows none.

## 5. Playing a track

- `play` ([playback section 2](playback.md#2-play)) takes a track key.
  Everything else stays: copies, versions, limits, ticket, `progress`,
  `stop`.
- **Audio only.** The answer has no subtitle tracks, no forced tracks,
  no skip markers and no previews; a viewer's server drops any it gets
  for a track. `audioTracks` lists the copy's one audio track (or more,
  rarely).
- **Nothing said** about `containers` or `audioCodecs`, for a track: the
  owning server serves AAC in HLS, audio only, which every viewer's
  server must play. `direct` serves the file as it is, with ranges, when
  the capabilities allow it: FLAC to a player that plays FLAC is never
  transcoded.
- **One playback per track.** A viewer's server that plays an album
  calls `play` for each track as it comes, and `stop` for the one
  before. The `play` limit of [core section 8.3](core.md#83-limits-and-overload)
  (suggested: 30 a minute) is enough for that; skipping through tracks
  faster is refused with `429`, and the viewer's server waits.

### 5.1 Limits

An audio playback counts as a stream, like a video one. The owning
server may count audio separately; it says so with two members of
`limits` ([playback section 5](playback.md#5-limits)):

| Field | Type | Range | Content |
|-------|------|-------|---------|
| `audioStreams` | integer | 0 to 50 | audio playbacks at the same time |
| `audioTranscodes` | integer | 0 to `audioStreams` | of those, how many may be transcoded |

Absent: audio counts in `streams` and `transcodes`.

## 6. Libraries

A `music` library holds artists, albums and tracks. A `mixed` library
may hold them beside films and series. A receiver that speaks `music`
reads them from `titles` ([catalog section 3](catalog.md#3-titles)), in
the same paging and the same changes.

## 7. Security considerations

- **Descriptions are untrusted text** from another server: clean them,
  show them as text, never as markup, and never let a name decide that
  two titles are the same.
- **MusicBrainz and the Cover Art Archive.** A viewer's server fetches
  covers itself, never through a URL a peer sent, and caches them, so a
  peer can't make it fetch anything else, nor learn when a viewer looks.
  It names itself in its User-Agent and keeps to MusicBrainz's rate of
  one request a second when it asks MusicBrainz anything.
- **A large library.** A compromised peer can send many titles; readers
  cap what they keep ([catalog section 6](catalog.md#6-security-considerations)).

## 8. Open questions

The open points of [proposal 11](../../proposals/0011-music.md), left for
later versions of this part:

1. **Untagged libraries.** A library without MBIDs shares nothing. Is
   that acceptable for version 1, with a later scheme for untagged
   music, or should a fallback be in from the start?
2. **Descriptions for video too.** If music titles carry names, should
   films and series be allowed to (as an option), for servers that don't
   want to depend on TMDB?
   ([video open question 4](video.md#8-open-questions),
   [core open question 26](core.md#18-open-questions).)
3. **Album art from the owning server** as a fallback, through `media`,
   when the Cover Art Archive has none. It would need the same checks as
   preview sheets (re-encoded, size bounds).
4. **Lyrics**, synced or not: a later version of the part.
5. **Gapless playback** across tracks: one playback per track leaves a
   gap unless the viewer's server preloads the next one. Should `play`
   allow a second playback to start while the first ends, counted as one
   stream?
6. **Music videos** (Jellyfin's `musicvideos` kind): a track's video, or
   a film? Left out.
7. **Watched state** for music is play counts and ratings, not
   "watched": nothing in this part shares it, as nothing shares it for
   video either.

**Choices this draft made, confirmed by the owner on 2026-11-17** (when proposal 11 was written
into this part on 2026-11-17):

8. **A title without a name is skipped** (section 3.2). The proposal
   lists `name` for every kind but doesn't say it is required; a viewer's
   server has nothing else to show for a key it doesn't know.
9. **What the caller keeps** (section 3.2): a value out of its range or
   form counts as absent rather than skipping the title; `artists`
   entries are kept once each, the first 16; members of the wrong JSON
   type count as absent, as for video titles.
10. **`ids` MBIDs** (`mbrelease`, `mbtrack`) take the lowercase form of
    section 2, which the proposal gives for keys only.
11. **Limits**: `audioTranscodes` ranges from 0 to `audioStreams`, as
    `transcodes` to `streams`; absent, audio counts in `transcodes` too,
    not only in `streams`.
12. **The security considerations** (section 7) are new: the proposal
    had none of its own.
