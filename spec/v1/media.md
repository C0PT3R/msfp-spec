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

- `<ticket>` matches `^[A-Za-z0-9_-]{1,64}$`. It is the only credential.
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
shape. `<name>` and `<track>` match `^[A-Za-z0-9._-]{1,64}$`.

## 2. Requests

The viewer's server fetches with plain `GET`:

- No signature headers. No cookies. No query string: the owning server
  answers `404` to any query.
- No `Origin`, `Sec-Fetch-Site` or `Sec-Fetch-Mode` header. The owning
  server answers `404` to a peer's ticket when any of them is present,
  because only a browser sends them, and a browser must never use a
  peer's ticket.
- `Range: bytes=<first>-<last>` is allowed on media (the file and
  segments), with at most 15 digits on each side. The answer is `200` or
  `206`, with `Content-Length`, `Content-Range` and `Accept-Ranges` as
  usual.
- Redirects must not be followed.

A fetch refused for its certificate makes the viewer's server send a
`hello` and try again once, as
[core section 3.2](core.md#32-https-certificates) says ("Renewals").

## 3. What is fetched

- **HLS.** Fetch `master.m3u8`. Every URI in it, and in the playlists it
  names, is a bare file name of the same stream (it matches
  `^[A-Za-z0-9._-]{1,64}$`), relative to `<stream root><ticket>/`. Fetch
  each the same way. The viewer's server refuses a playlist that doesn't
  start with `#EXTM3U`, or that names anything else, including an
  unquoted `URI=` attribute. Playlists are at most 2 MiB.
- **File.** Fetch `file`, with ranges.
- **Text subtitles.** Fetch `<track url>/<part>`, where `<part>` is a
  decimal integer from 0 to 9,999 without leading zeros. Part *n* covers
  the video from *n* × 120 to (*n* + 1) × 120 seconds, and starts 10
  seconds early, so a line already on screen comes along; drop the
  doubles. The answer is WebVTT, at most 5 MiB.
- **PGS subtitles.** Fetch `<track url>/<part>` the same way. The answer
  is the stretch's PGS data, `application/octet-stream`.
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

The viewer's server checks again everything it relays:

- WebVTT sanitized; PGS checked whole; playlists as above.
- A preview sheet is read whole, refused past 8 MiB, then checked from its
  header, before decoding, to be a JPEG (by its content, whatever its
  `Content-Type`) within the size above; any other is refused. It is
  re-encoded as JPEG, so that only its pixels reach the viewer, and
  served at the viewer's server's own playback route, to the viewer
  playing it only. A viewer's server should bound how many sheets it
  reads at once (for example 4).

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
