"""The media rules: HLS playlists (spec/v1/media.md section 3.1), ranges
(media 2.1), WebVTT and PGS parts (video.md sections 6.3 and 6.4), and a
JPEG's size from its header (video 6.2)."""

import html
import re
import unicodedata

from .wire import WHITE_SPACE, check_media_name

# ---- HLS (media 3.1) -------------------------------------------------------------

MASTER_TAGS = {"#EXTM3U", "#EXT-X-VERSION", "#EXT-X-INDEPENDENT-SEGMENTS", "#EXT-X-STREAM-INF"}
MEDIA_TAGS = {"#EXTM3U", "#EXT-X-VERSION", "#EXT-X-TARGETDURATION", "#EXT-X-MEDIA-SEQUENCE", "#EXT-X-PLAYLIST-TYPE",
              "#EXT-X-INDEPENDENT-SEGMENTS", "#EXTINF", "#EXT-X-DISCONTINUITY", "#EXT-X-ENDLIST", "#EXT-X-MAP"}
_URI = re.compile(r"URI=", re.I)


def check_playlist(b):
    """The viewer's server's checks, steps 1 to 8, in order. Returns
    (None, uris) when they pass, else (why, [])."""
    if len(b) > 2 * 1024 * 1024:
        return "over 2 MiB", []
    try:
        text = b.decode("utf-8")
    except UnicodeDecodeError:
        text = b.decode("latin-1")
    lines = [x[:-1] if x.endswith("\r") else x for x in text.split("\n")]
    if lines[0] != "#EXTM3U":
        return "the first line isn't #EXTM3U", []
    uris = []
    for line in lines[1:]:
        if line == "":
            continue
        if not line.startswith("#"):
            if check_media_name(line):
                return "a URI line that isn't a bare name: %r" % line[:80], []
            uris.append(line)
            continue
        for m in _URI.finditer(line):
            rest = line[m.end():]
            if not rest.startswith('"'):
                return "an unquoted URI attribute: %r" % line[:80], []
            end = rest.find('"', 1)
            if end < 0:
                return "a URI attribute without its closing quote", []
            if check_media_name(rest[1:end]):
                return "a URI attribute that isn't a bare name: %r" % rest[1:end][:80], []
            uris.append(rest[1:end])
        if line == "#EXT-X-DEFINE" or line.startswith("#EXT-X-DEFINE:"):
            return "#EXT-X-DEFINE", []
        if line.startswith("#EXT-X-KEY:") or line.startswith("#EXT-X-SESSION-KEY:"):
            return "#EXT-X-KEY or #EXT-X-SESSION-KEY", []
    if len(uris) > 50000:
        return "over 50,000 URIs", []
    return None, uris


def check_owner_playlist(b, master):
    """What the owning server sends (media 3.1): the viewer's checks, and
    besides: lines end in a line feed, only the subset's tags, URIs only
    in URI lines and #EXT-X-MAP:URI="<name>", a URI line only after
    #EXT-X-STREAM-INF or #EXTINF. Returns (problems, uris)."""
    why, uris = check_playlist(b)
    if why:
        return [why], []
    text = b.decode("utf-8", "replace")
    bad = []
    if not text.endswith("\n"):
        bad.append("the last line doesn't end in a line feed")
    if "\r" in text:
        bad.append("a carriage return (lines end in a line feed)")
    allowed = MASTER_TAGS if master else MEDIA_TAGS
    want_uri = False
    for line in text.split("\n"):
        if not line:
            continue
        if line.startswith("#"):
            tag = line.split(":", 1)[0]
            if tag not in allowed:
                bad.append("%s isn't in the %s playlist's subset" % (tag if tag.startswith("#EXT") else "a comment",
                                                                   "master" if master else "media"))
            if _URI.search(line) and not re.fullmatch(r'#EXT-X-MAP:URI="[A-Za-z0-9._-]{1,64}"', line):
                bad.append("a URI outside #EXT-X-MAP:URI=\"<name>\": %r" % line[:80])
            want_uri = tag in ("#EXT-X-STREAM-INF", "#EXTINF")
        else:
            if not want_uri:
                bad.append("a URI line not after #EXT-X-STREAM-INF or #EXTINF: %r" % line[:80])
            want_uri = False
    return bad, uris


# ---- Ranges (media 2.1) ----------------------------------------------------------

def check_206(range_form, headers, body, first=None, last=None, count=None):
    """Checks a 206 against the range asked for: None when it answers it."""
    h = {k.lower(): v for k, v in headers}
    cr = h.get("content-range", "")
    m = re.fullmatch(r"bytes ([0-9]+)-([0-9]+)/([0-9]+|\*)", cr.strip())
    if not m:
        return "Content-Range %r isn't bytes <start>-<end>/<total>" % cr
    start, end = int(m.group(1)), int(m.group(2))
    total = None if m.group(3) == "*" else int(m.group(3))
    if start > end or (total is not None and end >= total):
        return "Content-Range %r: not start <= end < total" % cr
    if count is not None:
        if total is not None and start != max(total - count, 0):
            return "Content-Range %r for bytes=-%d: start isn't total - count" % (cr, count)
    elif start != first:
        return "Content-Range %r: start isn't %d" % (cr, first)
    if last is not None and end > last:
        return "Content-Range %r: end past %d" % (cr, last)
    cl = h.get("content-length")
    if cl is not None and cl.strip() != str(end - start + 1):
        return "Content-Length %s isn't end - start + 1 = %d" % (cl, end - start + 1)
    if len(body) != end - start + 1:
        return "%d bytes in the body, the range has %d" % (len(body), end - start + 1)
    return None


# ---- WebVTT (video 6.3) ------------------------------------------------------------

_TIMING = re.compile(r"((?:[0-9]{1,3}:)?[0-9]{2}:[0-9]{2}\.[0-9]{3})[\t\f ]+-->[\t\f ]+((?:[0-9]{1,3}:)?[0-9]{2}:[0-9]{2}\.[0-9]{3})(?:[\t\f ].*)?")
_DIRECTION = {0x061C, 0x200E, 0x200F} | set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))


class Refused(ValueError):
    pass


def _drop_invisible(s):
    return "".join(ch for ch in s if ch != "�" and ord(ch) not in _DIRECTION)


def _drop_tags(s):
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "<" and i + 1 < n and (s[i + 1].isalpha() or s[i + 1] in "/!?"):
            j = s.find(">", i + 1)
            if j < 0:
                break
            out.append(" ")
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _clean_cue_line(s):
    s = _drop_tags(_drop_invisible(s))
    s = html.unescape(s)
    s = _drop_tags(_drop_invisible(s))
    words, cur = [], []
    for ch in s:
        if ch in WHITE_SPACE or unicodedata.category(ch) == "Cc" or ch.isspace():
            if cur:
                words.append("".join(cur))
                cur = []
            continue
        cur.append(ch)
    if cur:
        words.append("".join(cur))
    out = " ".join(words).encode("utf-8")
    if len(out) > 500:
        cut = 500
        while cut > 0 and (out[cut] & 0xC0) == 0x80:
            cut -= 1
        out = out[:cut]
    return out.decode("utf-8").rstrip(" ")


def rebuild_vtt(raw):
    """Rebuilds a WebVTT part as video 6.3 says; raises Refused."""
    if len(raw) > 5 * 1024 * 1024:
        raise Refused("over 5 MiB")
    text = raw.decode("utf-8", "replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("﻿"):
        text = text[1:]
    if not text.startswith("WEBVTT"):
        raise Refused("doesn't start with WEBVTT")
    out, cues = ["WEBVTT\n"], 0
    for block in text.split("\n\n"):
        lines = block.strip("\n").split("\n")
        at, m = -1, None
        for i, line in enumerate(lines):
            m = _TIMING.fullmatch("".join(line).strip("".join(WHITE_SPACE)))
            if m:
                at = i
                break
        if at < 0:
            continue
        body = []
        for line in lines[at + 1:]:
            c = _clean_cue_line(line)
            if c:
                body.append(c.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        if not body:
            continue
        cues += 1
        if cues > 50000:
            raise Refused("over 50,000 cues")
        out.append("\n%s --> %s\n%s\n" % (m.group(1), m.group(2), "\n".join(body)))
    return "".join(out).encode("utf-8")


# ---- PGS (video 6.4) ------------------------------------------------------------------

def check_pgs(raw):
    """Checks a PGS part whole; raises Refused."""
    if not raw or len(raw) > 64 * 1024 * 1024:
        raise Refused("empty, or over 64 MiB")

    def side(v):
        return 1 <= v <= 4096

    opened, firsts, pos = {}, 0, 0
    while pos < len(raw):
        if len(raw) - pos < 13:
            raise Refused("a segment header cut short")
        if raw[pos:pos + 2] != b"PG":
            raise Refused("a segment without its PG magic")
        typ, size = raw[pos + 10], int.from_bytes(raw[pos + 11:pos + 13], "big")
        if pos + 13 + size > len(raw):
            raise Refused("a payload past the end")
        seg = raw[pos + 13:pos + 13 + size]
        pos += 13 + size
        if typ == 0x16:
            if len(seg) < 11:
                raise Refused("a presentation under 11 bytes")
            if not side(int.from_bytes(seg[0:2], "big")) or not side(int.from_bytes(seg[2:4], "big")):
                raise Refused("a screen size outside 1 to 4,096")
            o = 11
            for _ in range(seg[10]):
                if o + 8 > len(seg):
                    raise Refused("composition objects past the payload")
                o += 16 if seg[o + 3] & 0x80 else 8
            if o > len(seg):
                raise Refused("composition objects past the payload")
        elif typ == 0x17:
            if len(seg) < 1 or len(seg) != 1 + 9 * seg[0]:
                raise Refused("a window segment of the wrong size")
        elif typ == 0x14:
            if len(seg) < 2 or (len(seg) - 2) % 5:
                raise Refused("a palette segment of the wrong size")
        elif typ == 0x15:
            if len(seg) < 4:
                raise Refused("an object segment under 4 bytes")
            oid, flags = int.from_bytes(seg[0:2], "big"), seg[3]
            if flags & 0x80:
                if len(seg) < 11:
                    raise Refused("a first fragment under 11 bytes")
                w, h = int.from_bytes(seg[7:9], "big"), int.from_bytes(seg[9:11], "big")
                if not side(w) or not side(h):
                    raise Refused("an object size outside 1 to 4,096")
                firsts += 1
                if firsts > 20000:
                    raise Refused("over 20,000 objects")
                opened[oid] = [w, h, bytearray(seg[11:])]
            else:
                if oid not in opened:
                    raise Refused("a fragment of no open object")
                opened[oid][2] += seg[4:]
            if flags & 0x40:
                w, h, data = opened.pop(oid)
                _runs_fit(bytes(data), w, h)
        elif typ == 0x80:
            if seg:
                raise Refused("an end segment that isn't empty")
        else:
            raise Refused("an unknown segment type 0x%02x" % typ)


def _runs_fit(d, w, h):
    x = y = i = 0
    while i < len(d):
        b = d[i]
        i += 1
        if b:
            x += 1
        else:
            if i >= len(d):
                raise Refused("a run cut short")
            f = d[i]
            i += 1
            if f == 0:
                x, y = 0, y + 1
                if y > h:
                    raise Refused("more lines than the object's height")
                continue
            n = f & 0x3F
            if f & 0x40:
                if i >= len(d):
                    raise Refused("a run cut short")
                n = n << 8 | d[i]
                i += 1
            if f & 0x80:
                if i >= len(d):
                    raise Refused("a run cut short")
                i += 1
            x += n
        if x > w:
            raise Refused("a line wider than the object")


# ---- JPEG (video 6.2) -------------------------------------------------------------------

def jpeg_size(b):
    """(width, height) from a JPEG's header (its first SOF marker), or None
    when it isn't a JPEG."""
    if b[:3] != b"\xff\xd8\xff":
        return None
    i = 2
    while i + 4 <= len(b):
        if b[i] != 0xFF:
            return None
        m = b[i + 1]
        if m == 0xFF:
            i += 1
            continue
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        n = int.from_bytes(b[i + 2:i + 4], "big")
        if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if i + 9 > len(b):
                return None
            return int.from_bytes(b[i + 7:i + 9], "big"), int.from_bytes(b[i + 5:i + 7], "big")
        if m == 0xDA:
            return None
        i += 2 + n
    return None
