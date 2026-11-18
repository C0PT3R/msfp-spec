# MSFP version 1: the media part, version 1

**Draft.**

The `media` part says what the stream URLs of a playback serve, and how
a viewer's server fetches them: HLS and the file itself. The content
parts add their own: [video](video.md#6-media) adds text and picture
subtitles and seek-bar preview sheets. It needs only the
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

A peer that can't be called
([core section 7.5](core.md#75-a-peer-that-cant-be-called)) is never the
owning server: nothing is fetched from its stream root, which is under an
address that doesn't resolve. It fetches its peers' media as any viewer's
server does.

The **stream root** of a server is `<address><prefix>/api/v1/stream/`,
where `<address>` is its address exactly as its peer stores it, and
`<prefix>` is the part of its base path before `/api/v1/federation/`
([core section 11](core.md#11-the-discovery-document)); without a
discovery document, `<prefix>` is empty. Example:
`https://a.example.org/api/v1/stream/`. While the owning server is
moving, it uses the address whose host the `play` request was signed
for ([core section 13.1](core.md#131-the-server-that-moves)).

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
  `<name>` `file` (the file as it is, served with byte ranges). The
  `file` protocol is only for a copy of one file; a copy of several
  parts ([playback section 1](playback.md#1-terms)) is served as `hls`.
  With `file`, the copy comes whole, with all its tracks; the viewer's
  player selects `audioTrack` itself. A viewer's server can't tell a
  copy's parts from the answer, and plays what it is given.
- A content part may add URLs of its own under `<stream root><ticket>/`:
  [video section 6.1](video.md#61-the-urls) adds subtitle, PGS and
  preview sheet URLs, with a `<track>` name.

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
anything else is a failed fetch, with one exception: a `416` to a range
the viewer asked for may be passed to the viewer as a `416` of its own,
without the owning server's body or headers. It never passes on the
owning server's body or headers with a failure, and it doesn't retry a failed fetch by
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
- **What a content part adds.** Fetched as that part says
  ([video section 6.2](video.md#62-what-is-fetched): subtitles, PGS,
  preview sheets), with the same plain `GET`s and the same ticket.

The owning server serves only what these rules allow. The viewer's server
checks again everything it relays, whatever the owning server says it
did:

- playlists as section 3.1 says, and what a content part adds as that
  part says ([video section 6.2](video.md#62-what-is-fetched)); whatever
  fails is a failed fetch (section 2.3), answered `404` to the viewer.

The viewer's server sets the `Content-Type` of what it relays itself:
`application/vnd.apple.mpegurl` for playlists, and for what a content
part adds the type that part gives. For the file and segments, it keeps
a `video/*` or `audio/*` type made only of letters, digits and `.+-`,
which it sends lowercased, and sends `application/octet-stream` instead
of any other.

Test cases for section 3.1 are in
[vectors/v1/media.json](../../vectors/v1/media.json), beside video's
WebVTT and PGS cases.

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
- **Hostile media.** Check playlists, and what the content parts add
  ([video section 7](video.md#7-security-considerations): subtitles,
  preview sheets), before relaying them; never let a playlist name
  anything outside the stream.

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
4. **`Content-Range` checks** (section 2.1) are required of the viewer's
   server; Overfin makes them since 2026-11-16.

The choices on timestamp tags in WebVTT and on checks left to the player
moved to [video](video.md#8-open-questions) with the WebVTT and PGS rules.

**Choices this draft made, confirmed by the owner on 2026-11-17** (when the video rules were moved
out of this part on 2026-11-17):

5. **Bounds stay here**: the sizes of WebVTT parts, PGS parts and sheets
   (section 2.4), and the rule that they are fetched without `Range`
   (section 2.1), are still listed with the other bounds, though only
   `video` uses them.
6. **URL checks stay here** (section 1): the `<track>` name that video's
   URLs add follows the same pattern as `<name>`.
