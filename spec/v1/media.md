# MSFP version 1: the media part, version 1

**Draft.** Nothing implements version 1 yet. [Version 0](../v0.md) is what
Overfin and the Jellyfin plugin speak today.

The `media` part says what the stream URLs of a playback serve, and how
a viewer's server fetches them: HLS, the file itself, text and picture
subtitles, and seek-bar preview sheets. It needs only the
[core](core.md); [playback](playback.md) gives the URLs. Media is fetched
with plain `GET` requests that carry the ticket only: they are not
signed.

The words "must", "must not" and "should" carry their usual meaning in
specifications.

## Contents

1. [The URLs](#1-the-urls)
2. [Requests](#2-requests)
3. [What is fetched](#3-what-is-fetched)
4. [How long a ticket works](#4-how-long-a-ticket-works)
5. [Security considerations](#5-security-considerations)
6. [Open questions](#6-open-questions)

## 1. The URLs

Media is fetched over `https` only, and every fetch needs a *trusted* or
*named* certificate ([core section 3.2](core.md#32-https-certificates)),
never just any: the ticket and the media have only TLS to protect them.

The **stream root** of a server is `<address><prefix>/api/v1/stream/`,
where `<address>` is its address exactly as its peer stores it, and
`<prefix>` is the part of its base path before `/api/v1/federation/`
([core section 11](core.md#11-the-discovery-document)); without a
discovery document, `<prefix>` is empty. Example:
`https://a.example.org/api/v1/stream/`.

The stream URL in a `play` answer is absolute, under the owning server's
stream root:

```
<stream root><ticket>/<name>
```

- `<ticket>` matches `^[A-Za-z0-9_-]{1,64}$`. It is the only credential:
  a bearer capability. The owning server makes each ticket from at least
  128 bits of a cryptographically secure random source, never from a
  counter, a time or any other value a peer could predict. A ticket is
  never reused, for another playback or after its own has ended. The
  owning server compares tickets in a way whose time doesn't depend on
  how much of a ticket matches (a lookup by a hash of the ticket is
  enough), and neither side writes tickets into logs, diagnostics or
  error messages.
- `stream.protocol` is `hls`, with `<name>` `master.m3u8` and
  `stream.mimeType` `application/vnd.apple.mpegurl`; or `file`, with
  `<name>` `file` (the file as it is, served with byte ranges).
- Subtitle and forced tracks carry a `url` of the form
  `<stream root><ticket>/subtitles/<track>` for text, or
  `<stream root><ticket>/pictures/<track>` for PGS, where `<track>` is the
  track ID.
- `trickplay.sheets[n]` is exactly `<stream root><ticket>/trickplay/<n>`,
  with the stream's own `<ticket>` and `<n>` the entry's index in
  decimal, without leading zeros: `sheets[0]` ends in `/trickplay/0`,
  `sheets[1]` in `/trickplay/1`, and so on.

The viewer's server refuses any URL that doesn't start with the owning
server's stream root, or that names another ticket, or another file
shape. `<name>` and `<track>` match `^[A-Za-z0-9._-]{1,64}$` and are
never `.` or `..`, which a URL resolves as folders, not files. These
checks apply to the URL's path split at `/` into its parts, compared
exactly as sent: no part is decoded, normalized or resolved before the
check, and a URL with an empty part, a `.` or `..` part, a `%`, a query or
a fragment is refused. Test cases: `mediaNames` in
[vectors/v1/strict.json](../../vectors/v1/strict.json).

## 2. Requests

The viewer's server fetches with plain `GET`:

- No signature headers. No cookies. No query string: the owning server
  answers `404` to any query.
- No `Origin`, `Sec-Fetch-Site` or `Sec-Fetch-Mode` header. The owning
  server answers `404` to a peer's ticket when any of them is present,
  because only a browser sends them, and a browser must never use a
  peer's ticket.
- `Range` only on the file and on segments (section 2.1).
- Redirects must not be followed. The connection is checked as
  [core section 3.3](core.md#33-connecting-to-peers) says, like every
  connection to a peer.

A fetch refused for its certificate makes the viewer's server send a
`hello` and try again once, as
[core section 3.2](core.md#32-https-certificates) says ("Renewals").

### 2.1 Ranges

A request carries at most one `Range` header, in one of three forms, and
no other:

| Form | Meaning |
|------|---------|
| `bytes=<first>-<last>` | bytes *first* to *last*, both included; *first* ≤ *last* |
| `bytes=<first>-` | from *first* to the end |
| `bytes=-<count>` | the last *count* bytes; *count* ≥ 1 |

- Each number is 1 to 15 decimal digits. Leading zeros are accepted. No
  spaces, no other unit.
- **Several ranges** (`bytes=0-1,5-9`) are refused, so ranges can't
  overlap. `bytes=-` is refused.
- The owning server answers a malformed `Range` with `416`, without
  reading the file. It answers a well-formed one that starts past the end
  with `416` too.
- `Range` is meant for the file and for segments. On a playlist, a
  subtitle part, a PGS part or a sheet, the viewer's server sends none,
  and the owning server ignores one and sends the whole.
- The viewer's server sends the viewer's `Range` on only when it is
  well-formed; otherwise it answers the viewer `416` itself, and fetches
  nothing.

**Checking a `206`.** The viewer's server relays a `206` only when it
answers the range asked for:

- `Content-Range` is `bytes <start>-<end>/<total>`, three decimal numbers
  (or `*` for *total*, when the owning server doesn't know it), with
  *start* ≤ *end* < *total*;
- *start* is *first* for the first two forms, and *total* − *count* (or
  0) for the third; *end* is at most *last* for the first form;
- `Content-Length`, when present, is *end* − *start* + 1.

A `200` to a request with `Range` is the whole file, and is accepted. A
`206` to a request without one, or a `206` that fails these checks, is a
failed fetch. A server never trusts the body to stop at `Content-Length`:
it stops reading there.

### 2.2 Methods

The viewer's server sends `GET` only, never `HEAD`. An owning server may
answer `HEAD` as `GET` without the body, or refuse it with `404`. Any
other method is refused (`404` or `405`).

### 2.3 Statuses

[Core section 8.4](core.md#84-media-answers) lists what each status
means. The viewer's server accepts `200` and, under section 2.1, `206`;
anything else is a failed fetch. It never passes on the owning server's
body or headers with a failure, and it doesn't retry a failed fetch by
itself, except once after a renewed certificate (section 2).

### 2.4 Bounds

Both sides bound what one fetch, one playback and one peer may hold.
The numbers are each implementation's; the bounds are required.

- **Time to the answer.** The viewer's server gives a fetch a bounded
  time to its status line and headers (Overfin: 60 seconds), and to
  connect and finish TLS (Overfin: 10 seconds each).
- **Length of a fetch.** A fetch of the file or a segment never outlives
  its playback: when the playback ends (section 4), every fetch of it is
  cut. A playlist, a subtitle part, a PGS part or a sheet is read whole
  within a bounded time.
- **Size.** Playlists at most 2 MiB, WebVTT parts at most 5 MiB, PGS parts
  at most 64 MiB, sheets at most 8 MiB: anything longer is refused. The
  file and segments are as long as `Content-Length` says, and no longer.
- **Fetches at once.** The viewer's server bounds how many fetches it
  runs at once for one playback and for one peer, and the owning server
  how many it serves at once for one ticket and for one peer. Over the
  bound, a new fetch waits in a bounded queue, or is refused with `503`.
  Reads that are held whole in memory (playlists, subtitles, PGS, sheets)
  have a bound of their own across the server; Overfin's is 4 for
  playlists and subtitles together, and 4 for sheets.

**Overfin.** Overfin follows sections 2.1 to 2.4 on a peer's ticket. Its
numbers: 8 fetches at once per playback and 64 per peer, on both sides,
each with a queue as long, waited in for 10 seconds at most, then `503`;
a playlist, a subtitle part, a PGS part or a sheet is read whole within
2 minutes. The same stream route serves its own people's browsers, on
tickets of their own: there it answers `HEAD` as `GET`, and passes on any
single range its media server answers.

## 3. What is fetched

- **HLS.** Fetch `master.m3u8`, then the playlists it names, then their
  files: every URI in them is a bare file name of the same stream (it
  matches `^[A-Za-z0-9._-]{1,64}$`, and is not `.` or `..`), relative to
  `<stream root><ticket>/`. Fetch each the same way. Section 3.1 says
  what a playlist may hold.
- **File.** Fetch `file`, with ranges.
- **Text subtitles.** Fetch `<track url>/<part>`, where `<part>` is a
  decimal integer from 0 to 9,999 without leading zeros. Part *n* covers
  the video from *n* × 120 to (*n* + 1) × 120 seconds, and starts 10
  seconds early, so a line already on screen comes along; drop the
  doubles. The answer is WebVTT, at most 5 MiB, in the form of
  section 3.2.
- **PGS subtitles.** Fetch `<track url>/<part>` the same way. The answer
  is the stretch's PGS data, `application/octet-stream`, at most 64 MiB,
  checked as section 3.3 says.
- **Preview sheets.** Fetch `trickplay.sheets[n]`
  ([playback section 2.4](playback.md#24-seek-bar-previews)), the same
  plain `GET` with the playback's ticket, no `Range`. The owning server
  answers `404` for a sheet number at or past the sheet count, one with
  leading zeros, a query string, or a ticket not live (section 4). The
  answer is `200`, `Content-Type: image/jpeg`, a JPEG of at most 8 MiB, no
  wider than `columns` × `tileWidth` and no taller than `rows` ×
  `tileHeight` pixels. The owning server should re-encode every sheet
  before sending it. A viewer's server may fetch the sheets when the
  playback starts or when the viewer needs them; the fetches count as
  media requests for section 4.

The owning server serves only what these rules allow. The viewer's server
checks again everything it relays, whatever the owning server says it
did:

- playlists as section 3.1 says, WebVTT rebuilt as section 3.2 says, PGS
  checked whole as section 3.3 says; whatever fails is a failed fetch
  (section 2.3), answered `404` to the viewer;
- a preview sheet is read whole, refused past 8 MiB, then checked from its
  header, before decoding, to be a JPEG (by its content, whatever its
  `Content-Type`) within the size above; any other is refused. It is
  re-encoded as JPEG, so that only its pixels reach the viewer, and
  served at the viewer's server's own playback route, to the viewer
  playing it only. A viewer's server should bound how many sheets it
  reads at once (for example 4).

The viewer's server sets the `Content-Type` of what it relays itself:
`application/vnd.apple.mpegurl` for playlists, `text/vtt; charset=utf-8`
for WebVTT, `application/octet-stream` for PGS, `image/jpeg` for sheets.
For the file and segments, it keeps a `video/*` or `audio/*` type made
only of letters, digits and `.+-`, and sends `application/octet-stream`
instead of any other.

Test cases for sections 3.1 to 3.3 are in
[vectors/v1/media.json](../../vectors/v1/media.json).

### 3.1 HLS playlists

Media 1 uses a small subset of HLS (RFC 8216), with no encryption,
alternative renditions or variables.

**What the owning server sends.** Lines end in a line feed. The first line
is exactly `#EXTM3U`. A playlist holds only these tags, and the URI lines
after `#EXT-X-STREAM-INF` and `#EXTINF`:

| Playlist | Tags allowed |
|----------|--------------|
| `master.m3u8` | `#EXTM3U`, `#EXT-X-VERSION`, `#EXT-X-INDEPENDENT-SEGMENTS`, `#EXT-X-STREAM-INF` |
| a media playlist it names | `#EXTM3U`, `#EXT-X-VERSION`, `#EXT-X-TARGETDURATION`, `#EXT-X-MEDIA-SEQUENCE`, `#EXT-X-PLAYLIST-TYPE`, `#EXT-X-INDEPENDENT-SEGMENTS`, `#EXTINF`, `#EXT-X-DISCONTINUITY`, `#EXT-X-ENDLIST`, `#EXT-X-MAP` |

- URIs are only in URI lines and in `#EXT-X-MAP`'s `URI` attribute,
  written `#EXT-X-MAP:URI="<name>"`. Each is a bare name (section 1).
- Not in media 1, so never sent: `#EXT-X-MEDIA` (the audio comes in the
  stream; another track is another `play`), `#EXT-X-I-FRAME-STREAM-INF`
  (seek-bar previews are sheets), `#EXT-X-KEY` and `#EXT-X-SESSION-KEY`
  (TLS protects the media), `#EXT-X-DEFINE` (no variable substitution),
  `#EXT-X-SESSION-DATA`, `#EXT-X-BYTERANGE`, and the low-latency tags
  (`#EXT-X-PART`, `#EXT-X-PRELOAD-HINT`, `#EXT-X-RENDITION-REPORT`,
  `#EXT-X-SERVER-CONTROL`, `#EXT-X-SKIP`).
- A playlist holds at most 50,000 URIs.

**What the viewer's server checks.** In this order; the first failure
refuses the whole playlist:

1. It is at most 2 MiB (2,097,152 bytes).
2. It is split into lines at each line feed; one carriage return at the
   end of a line is removed.
3. The first line is exactly `#EXTM3U`.
4. Empty lines are skipped. A line that starts with `#` is a tag or a
   comment. Any other line is a URI line, and must be a bare name, with
   nothing before or after it.
5. In a tag line, every `URI=`, in any case and anywhere in the line
   (inside another attribute's quoted string too), is followed by `"`, a
   bare name, and `"`. So an unquoted URI, an empty one, and one holding
   `/`, `?`, `#`, `%`, a scheme or a host are refused. HLS quoted strings
   have no escapes, so nothing else can end the string.
6. No line is `#EXT-X-DEFINE` or starts with `#EXT-X-DEFINE:`.
7. No line starts with `#EXT-X-KEY:` or `#EXT-X-SESSION-KEY:`.
8. It holds at most 50,000 URIs, counting URI lines and `URI=` values.

Then:

- Tags outside the subset, and comments, should be dropped before the
  playlist is served to the viewer. They may be passed on unchanged
  instead: step 5 holds for them too.
- The viewer's server serves the playlist without rewriting a URI: each
  bare name resolves under the viewer's server's own route for the
  playback, which fetches the same name from the owning server.
- It may refuse to fetch a name that none of the playback's playlists
  named.

**Overfin.** As the owning server, Overfin sends exactly this subset. It
rewrites its media server's HLS: master playlists name `v<n>.m3u8`,
media playlists `init.<ext>` (in `#EXT-X-MAP`) and `seg<n>.<ext>`, where
*n* may be negative and *ext* is `mp4`, `m4s`, `ts`, `aac` or `mp3`; it
keeps a segment's duration in `#EXTINF` but not its title, drops every
other tag and any tag holding `URI=` in any case, and refuses a playlist
of its media server with any other URI. As the viewer's server, it
checks steps 1 to 8, and drops tags outside the subset, and comments,
before serving. It fetches any bare name the viewer asks for.

### 3.2 WebVTT

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

### 3.3 PGS

A PGS part is checked whole, then served unchanged: a player decodes and
draws it. Checking means reading every segment, and decoding every
object's run-length data to count it, not to draw it.

**The track.** A part is at least one segment and at most 64 MiB
(67,108,864 bytes), made of segments one after another, up to its exact
end. A segment is a 13-byte header and a payload:

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
server. It accepts only PGS as picture subtitles; other picture formats
(DVD, DVB) are left out of the track list.

## 4. How long a ticket works

A ticket works while its playback is live. The playback ends, and the
ticket with it, when:

- the viewer's server sends `stop` ([playback](playback.md#4-stop));
- neither `progress` nor a media request came for 2 minutes;
- the pairing ends, the caller is no longer `paired`, or its key is
  suspended ([core section 12.6](core.md#126-revocation));
- the library holding the copy is no longer offered to that peer.

A ticket works only for the pairing it was given to, and never for a
browser. A playback started before a peer's address changed keeps its
URLs until it ends ([core section 13.2](core.md#132-a-peer-that-learns-of-a-move)).

## 5. Security considerations

- **Media is protected by TLS only.** The ticket and the bytes aren't
  signed. HTTPS is required, with a *trusted* or *named* certificate, so
  an observer can't read a ticket, and an attacker on the path can't
  change the media without breaking TLS.
- **Preview sheets are images from another server**, the only ones a peer
  sends. Check a sheet's byte size first, then its dimensions from its
  header against the layout, and only then decode it. Re-encode it, so
  nothing but pixels (no metadata, no trailing bytes, no second image)
  reaches a browser. The layout's bounds keep the number of fetches, and
  the memory a sheet takes, small: at most 1,000 sheets of 4,096 × 4,096
  pixels. Never give the browser the peer's sheet URLs: they carry the
  ticket, and would let the peer see the viewer.
- **Hostile media.** Check playlists and subtitles before relaying them;
  never let a playlist name anything outside the stream.

## 6. Open questions

1. **Media isn't signed.** Only TLS protects what the stream root serves.
   With HTTPS required, that is true in every case; signing media (per
   segment, or signed playlists with hashes) would cost far more.

Choices of the review round of 2026-11-16, all confirmed by the owner on
2026-11-17 (they may still change as implementations show):

2. **The HLS subset** (section 3.1) is what Overfin sends today. Separate
   audio renditions (`#EXT-X-MEDIA`), I-frame playlists and encryption
   are left for a later version of `media`.
3. **Unknown tags** in a relayed playlist: dropped or passed on, at the
   viewer's server's choice (section 3.1), since URIs are checked in
   every tag either way.
4. **Timestamp tags in WebVTT** stay as escaped text (section 3.2), as
   Overfin does. Removing them would suit karaoke-style subtitles better.
5. **Checks left to the player**: WebVTT timings out of range or order,
   and PGS fields beyond sizes (sections 3.2 and 3.3). An open PGS object
   at the end of a part isn't refused.
6. **`Content-Range` checks** (section 2.1) are required of the viewer's
   server; Overfin makes them since 2026-11-16.
