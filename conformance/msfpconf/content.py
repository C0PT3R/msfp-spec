"""Title keys and titles: catalog.md sections 3 and 4, video.md sections
3 and 4, music.md sections 2 and 3."""

import json
import re

from .wire import clean_name, is_int

KINDS = {"movies", "tvshows", "music", "musicvideos", "homevideos", "boxsets", "books", "photos", "mixed", ""}
LIBRARY_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
TAG = re.compile(r"[A-Za-z0-9-]{2,12}")

# ---- video (video 4) ---------------------------------------------------------------

_VIDEO_KEY = re.compile(r"(movie|series)/tmdb/([1-9][0-9]{0,9})"
                        r"(?:/s(0|[1-9][0-9]{0,3})(?:/e(0|[1-9][0-9]{0,4}))?|/e([1-9][0-9]{0,9}))?")


def video_key(k):
    """(kind, series id) a video title key names, or None when it isn't
    one in canonical form (video 4)."""
    m = _VIDEO_KEY.fullmatch(k) if isinstance(k, str) else None
    if not m:
        return None
    if int(m.group(2)) > 9999999999:
        return None
    if m.group(1) == "movie":
        if m.group(3) is not None or m.group(5) is not None:
            return None
        return "movie", m.group(2)
    if m.group(5) is not None:
        if int(m.group(5)) > 9999999999:
            return None
        return "episode", m.group(2)
    if m.group(4) is not None:
        return "episode", m.group(2)
    if m.group(3) is not None:
        return "season", m.group(2)
    return "series", m.group(2)


# ---- music (music 2) ----------------------------------------------------------------

MBID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
ISRC = re.compile(r"[A-Z]{2}[A-Z0-9]{3}[0-9]{7}")
MUSIC_ID_KINDS = {"mbrelease": ("album", "track"), "mbtrack": ("track",), "isrc": ("track",)}


def music_key(k):
    """The kind a music title key names, or None."""
    if not isinstance(k, str):
        return None
    p = k.split("/")
    if len(p) != 3 or p[0] not in ("artist", "album", "track") or p[1] != "mb" or not MBID.fullmatch(p[2]):
        return None
    return p[0]


def _int_in(v, lo, hi):
    return v if is_int(v) and lo <= v <= hi else None


def keep_music_title(t, libraries):
    """What a caller keeps of a music title (catalog 3.3, music 3.2), as a
    dict in the vectors' order, or raises ValueError with why it is skipped."""
    if not isinstance(t, dict):
        raise ValueError("not an object")
    key, kind, lib = t.get("key"), t.get("kind"), t.get("library")
    if not all(isinstance(x, str) for x in (key, kind, lib)):
        raise ValueError("key, kind or library isn't a string")
    kk = music_key(key)
    if kk is None:
        raise ValueError("%r isn't a music title key" % key)
    if kind != kk:
        raise ValueError("kind %r, but the key names a %s" % (kind, kk))
    if lib not in libraries:
        raise ValueError("library %r wasn't asked for" % lib)
    out = {"key": key, "kind": kind, "library": lib}
    name = clean_name(t["name"], 256) if isinstance(t.get("name"), str) else ""
    if not name:
        raise ValueError("no name, once cleaned")
    out["name"] = name
    if kind in ("album", "track"):
        arts = []
        if isinstance(t.get("artists"), list):
            for a in t["artists"]:
                if isinstance(a, str) and a not in arts and len(arts) < 16 and music_key(a) == "artist":
                    arts.append(a)
        if arts:
            out["artists"] = arts
        an = clean_name(t["artistNames"], 512) if isinstance(t.get("artistNames"), str) else ""
        if an:
            out["artistNames"] = an
    if kind == "track":
        if isinstance(t.get("album"), str) and music_key(t["album"]) == "album":
            out["album"] = t["album"]
        for f, lo, hi in (("disc", 1, 999), ("number", 1, 999)):
            if _int_in(t.get(f), lo, hi) is not None:
                out[f] = t[f]
    if kind in ("album", "track") and _int_in(t.get("year"), 1000, 9999) is not None:
        out["year"] = t["year"]
    # music 3.2: a durationMs of 0 is absent.
    if kind == "track" and _int_in(t.get("durationMs"), 1, 86400000) is not None:
        out["durationMs"] = t["durationMs"]
    if isinstance(t.get("ids"), dict):
        ids = {}
        for scheme, v in t["ids"].items():
            if not isinstance(v, str) or scheme not in MUSIC_ID_KINDS or kind not in MUSIC_ID_KINDS[scheme]:
                continue
            if (ISRC if scheme == "isrc" else MBID).fullmatch(v):
                ids[scheme] = v
        if ids:
            out["ids"] = dict(sorted(ids.items()))
    return out


def music_problems(t):
    """What an owning server got wrong in a music title it sent: members a
    caller would clean, skip or ignore (music 3, 3.1)."""
    bad = []
    kind = t.get("kind")
    for f, n in (("name", 256), ("artistNames", 512)):
        if f in t and (not isinstance(t[f], str) or clean_name(t[f], n) != t[f]):
            bad.append("%s isn't text in its cleaned form, at most %d characters" % (f, n))
    if kind in ("album", "track") and "artists" in t:
        a = t["artists"]
        if not isinstance(a, list) or len(a) > 16 or len(set(map(str, a))) != len(a) or any(music_key(x) != "artist" for x in a):
            bad.append("artists isn't at most 16 artist keys, each once")
    if kind == "track":
        if "album" in t and music_key(t["album"]) != "album":
            bad.append("album isn't an album key")
        for f, lo, hi in (("disc", 1, 999), ("number", 1, 999), ("durationMs", 0, 86400000)):
            if f in t and _int_in(t[f], lo, hi) is None:
                bad.append("%s isn't an integer from %d to %d" % (f, lo, hi))
    if kind in ("album", "track") and "year" in t and _int_in(t["year"], 1000, 9999) is None:
        bad.append("year isn't an integer from 1000 to 9999")
    if "ids" in t:
        ids = t["ids"]
        if not isinstance(ids, dict):
            bad.append("ids isn't an object")
        else:
            for s, v in ids.items():
                if s in MUSIC_ID_KINDS and (kind not in MUSIC_ID_KINDS[s] or not isinstance(v, str)
                                            or not (ISRC if s == "isrc" else MBID).fullmatch(v)):
                    bad.append("ids.%s isn't in its form, or not for a %s" % (s, kind))
    return bad


# ---- language tags (catalog 3, core 2.5) -----------------------------------------------

# ISO 639-2 codes whose language has an ISO 639-1 code (a common subset):
# a tag written with them isn't the shortest form catalog 3 asks for.
ISO639_2_WITH_1 = {
    "eng", "fre", "fra", "ger", "deu", "spa", "ita", "por", "rus", "jpn", "chi", "zho", "kor", "ara", "hin", "dut",
    "nld", "swe", "nor", "nob", "nno", "dan", "fin", "pol", "cze", "ces", "slo", "slk", "hun", "rum", "ron", "gre",
    "ell", "tur", "heb", "tha", "vie", "ind", "msa", "may", "ukr", "bul", "hrv", "srp", "slv", "est", "lav", "lit",
    "per", "fas", "cat", "baq", "eus", "glg", "ice", "isl", "gle", "wel", "cym", "tam", "tel", "ben", "urd",
}


def conventional_case(tag):
    parts = tag.split("-")
    if parts[0] != parts[0].lower():
        return False
    for x in parts[1:]:
        if len(x) == 4 and x.isalpha() and x != x.title():
            return False
        if len(x) == 2 and x.isalpha() and x != x.upper():
            return False
    return True


def tag_problems(where, v):
    """A list of language tags as an owning server must send it."""
    if not isinstance(v, list):
        return ["%s isn't an array" % where]
    bad, seen = [], set()
    if len(v) > 12:
        bad.append("%s holds %d tags (a caller keeps 12)" % (where, len(v)))
    for tag in v:
        if not isinstance(tag, str) or not TAG.fullmatch(tag):
            bad.append("%s: %r isn't 2 to 12 characters of A-Z a-z 0-9 -" % (where, tag))
            continue
        base = tag.split("-")[0].lower()
        if tag.lower() in seen:
            bad.append("%s: %r twice (compared without case)" % (where, tag))
        elif base in ("und", "mul", "zxx", "mis"):
            bad.append("%s: %r is a tag catalog 3 says isn't sent" % (where, tag))
        elif not conventional_case(tag):
            bad.append("%s: %r isn't in BCP 47's case conventions (core 2.5)" % (where, tag))
        elif len(base) == 3 and base in ISO639_2_WITH_1:
            bad.append("%s: %r has a two-letter code (catalog 3: the shortest)" % (where, tag))
        seen.add(tag.lower())
    return bad


# ---- a title as the owning server sends it --------------------------------------------

def title_problems(t, libs, parts_on):
    """What's wrong with one entry of a titles answer, as the owning server
    sent it (catalog 3, 3.3; video 3, 4; music 2, 3). Returns (kind, problems)."""
    if not isinstance(t, dict):
        return None, ["an entry that isn't an object"]
    k, kind, lib = t.get("key"), t.get("kind"), t.get("library")
    bad = []
    if not all(isinstance(x, str) for x in (k, kind, lib)):
        return None, ["%r: key, kind or library isn't a string" % (k,)]
    vk, mk = video_key(k), music_key(k)
    if vk:
        if "video" not in parts_on:
            bad.append("%s is a video title, and video is off between the two servers (catalog 5)" % k)
        if vk[0] != kind:
            bad.append("%s: kind %r, the key names a %s" % (k, kind, vk[0]))
    elif mk:
        if "music" not in parts_on:
            bad.append("%s is a music title, and music is off between the two servers (catalog 5)" % k)
        if mk != kind:
            bad.append("%s: kind %r, the key names a %s" % (k, kind, mk))
    else:
        bad.append("%r isn't a title key of a content part in canonical form (catalog 4, video 4, music 2)" % k)
    if lib not in libs:
        bad.append("%s: library %r wasn't asked for" % (k, lib))
    if vk:
        for f in ("audio", "subtitles"):
            if f in t:
                if kind in ("series", "season"):
                    bad.append("%s (%s) carries %s (video 3: films and episodes only)" % (k, kind, f))
                bad += tag_problems("%s %s" % (k, f), t[f])
        if "with" in t:
            w = t["with"]
            if kind != "episode":
                bad.append("%s (%s) carries with (video 3: episodes only)" % (k, kind))
            elif not isinstance(w, list) or len(w) > 16:
                bad.append("%s: with isn't an array of at most 16 keys" % k)
            else:
                if w != sorted(w, key=lambda x: str(x).encode()) or len(set(map(str, w))) != len(w):
                    bad.append("%s: with isn't in byte order, each key once (video 4.2)" % k)
                for x in w:
                    vx = video_key(x)
                    if not vx or vx[0] != "episode" or vx[1] != vk[1] or x == k:
                        bad.append("%s: with holds %r, not another episode of the same series" % (k, x))
        if "ids" in t:
            ids = t["ids"]
            if kind == "season":
                bad.append("%s: a season carries ids (video 4.3: films, series and episodes)" % k)
            if not isinstance(ids, dict):
                bad.append("%s: ids isn't an object" % k)
            else:
                for s, v in ids.items():
                    if s == "imdb" and not (isinstance(v, str) and re.fullmatch(r"tt[0-9]{7,10}", v)):
                        bad.append("%s: ids.imdb %r isn't tt and 7 to 10 digits" % (k, v))
                    if s == "tvdb" and not (isinstance(v, str) and re.fullmatch(r"[1-9][0-9]{0,9}", v)):
                        bad.append("%s: ids.tvdb %r isn't 1 to 10 digits without a leading zero" % (k, v))
    if mk:
        try:
            keep_music_title(t, libs)
        except ValueError as e:
            bad.append("%s: a caller skips it: %s" % (k, e))
        bad += ["%s: %s" % (k, x) for x in music_problems(t)]
    return kind, bad


def music_vectors_ok(path):
    """Checks keep_music_title against vectors/v1/music.json: a list of mismatches."""
    v = json.load(open(path))
    bad = []
    for c in v["keys"]:
        kind = music_key(c["text"])
        if (kind is not None) != c["valid"] or (kind and kind != c.get("kind")):
            bad.append("music key %s" % c["name"])
    for c in v["titles"]:
        from .wire import parse_ijson
        try:
            out = keep_music_title(parse_ijson(c["text"].encode()), v["libraries"])
            ok = True
        except ValueError:
            ok, out = False, None
        if ok != c["valid"]:
            bad.append("music title %s: kept %s" % (c["name"], ok))
        elif ok and json.dumps(out, separators=(",", ":"), ensure_ascii=False) != c["output"]:
            bad.append("music title %s: %s, not %s" % (c["name"], json.dumps(out, ensure_ascii=False), c["output"]))
    return bad
