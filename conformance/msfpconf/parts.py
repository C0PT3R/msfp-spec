"""The parts' checks: catalog (libraries, titles), playback (play,
progress, stop, limits, track choice) and media (HLS, the file, ranges,
subtitles, PGS, preview sheets), with what video and music add."""

import concurrent.futures
import os
import re
import time

from .content import KINDS, LIBRARY_ID, title_problems, video_key, music_key
from .media import Refused, check_206, check_owner_playlist, check_pgs, jpeg_size, rebuild_vtt
from .report import PASS
from .wire import STREAM, b64u, dumps, is_int, NonInteger

PLAY_ID = re.compile(r"play_[a-z2-7]{26}")
TICKET = re.compile(r"[A-Za-z0-9_-]{1,64}")
TRACK_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
BROAD_CAPS = {"containers": ["aac", "flac", "m4a", "m4v", "mkv", "mov", "mp3", "mp4", "ogg", "opus", "ts", "wav", "webm"],
              "audioCodecs": ["aac", "ac3", "alac", "eac3", "flac", "mp3", "opus", "pcm_s16le", "vorbis"],
              "videoCodecs": ["av1", "h264", "hevc", "vp8", "vp9"], "hdr": ["hdr10", "hlg"],
              "maxAudioChannels": 8, "maxHeight": 2160}


def _x():
    from .checks import Fail, Skip
    return Fail, Skip


class PartChecks:

    # ---- catalog: libraries (catalog 2) -------------------------------------------

    def need(self, part):
        _, Skip = _x()
        if part not in self.parts_on():
            raise Skip("%s isn't on between the server and this suite (core 10.3)" % part)

    def catalog_checks(self):
        Fail, Skip = _x()
        c = self.client

        def libs():
            self.need("catalog")
            a = self.signed(c.call("libraries", {}), 200)
            j = a.json
            if "name" in j and not isinstance(j["name"], str):
                raise Fail("name isn't a string (a caller fails the answer)")
            ls = j.get("libraries")
            if not isinstance(ls, list):
                raise Fail("libraries isn't an array (a caller fails the answer)")
            ids = []
            for lib in ls:
                if not isinstance(lib, dict):
                    raise Fail("a library that isn't an object: %r" % lib)
                i = lib.get("id")
                if not isinstance(i, str) or not LIBRARY_ID.fullmatch(i):
                    raise Fail("an ID outside 1 to 64 characters of A-Z a-z 0-9 _ -: %r" % i)
                if i in ids:
                    raise Fail("the ID %r twice" % i)
                ids.append(i)
                if not isinstance(lib.get("name"), str):
                    raise Fail("library %s: name isn't a string" % i)
                if lib.get("kind") not in KINDS:
                    raise Fail("library %s: kind %r isn't one of catalog 2's" % (i, lib.get("kind")))
            if len(ls) > 200:
                raise Fail("%d libraries: a caller keeps 200" % len(ls))
            self.libraries = ls
            self.limits = j.get("limits")
            return "%d librar%s: %s" % (len(ls), "y" if len(ls) == 1 else "ies",
                                       ", ".join("%s (%s)" % (x["id"], x["kind"]) for x in ls) or "none offered")
        self.check("L1", "catalog 2", "libraries: 200 signed, IDs and kinds in their forms, no ID twice", libs)

        def limits():
            self.need("catalog")
            lim = self.limits
            if "playback" not in self.parts_on():
                if lim is not None:
                    raise Fail("limits sent while playback is off (catalog 2: only when it is on)")
                return "playback off, no limits"
            if lim is None:
                return (PASS, "no limits (a server that doesn't enforce limits sends none, playback 5)")
            if not isinstance(lim, dict):
                raise Fail("limits isn't an object")
            s, t, b = lim.get("streams"), lim.get("transcodes"), lim.get("bitrateKbps")
            bad = []
            if not (is_int(s) and 0 <= s <= 50):
                bad.append("streams %r not 0 to 50" % s)
            if not (is_int(t) and is_int(s) and 0 <= t <= s):
                bad.append("transcodes %r not 0 to streams" % t)
            if not (is_int(b) and 0 <= b <= 1000000):
                bad.append("bitrateKbps %r not 0 to 1,000,000" % b)
            if "audioStreams" in lim or "audioTranscodes" in lim:
                aus, aut = lim.get("audioStreams"), lim.get("audioTranscodes")
                if not (is_int(aus) and 0 <= aus <= 50 and is_int(aut) and 0 <= aut <= aus):
                    bad.append("audioStreams %r / audioTranscodes %r out of range (music 5.1)" % (aus, aut))
            if bad:
                raise Fail("; ".join(bad))
            return "limits %s" % lim
        self.check("L2", "playback 5, music 5.1", "libraries' limits: only with playback on, each in its range", limits)

        def opaque():
            self.need("catalog")
            if not self.libraries:
                raise Skip("nothing offered to this suite")
            looks = [x["id"] for x in self.libraries if re.fullmatch(
                r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", x["id"])]
            if looks:
                raise Fail("IDs shaped like a media server's item IDs (32 hex digits, a GUID): %s; catalog 2.1 says "
                           "they must not be one (a heuristic: a random value may look so)" % looks)
            return "none looks like a media server's ID"
        self.check("L3", "catalog 2.1", "library IDs don't look like the media server's own IDs", opaque, "SHOULD")

        def stable():
            self.need("catalog")
            a = self.signed(c.call("libraries", {}), 200)
            again = [x.get("id") for x in a.json.get("libraries", []) if isinstance(x, dict)]
            if again != [x["id"] for x in self.libraries]:
                raise Fail("two readings a moment apart give other IDs: %s, then %s" % ([x["id"] for x in self.libraries], again))
            return "the same IDs twice"
        self.check("L4", "catalog 2.1", "library IDs are stable between two readings", stable)

        def bad_body():
            self.need("catalog")
            out = []
            for name, body in (("an array", b"[]"), ("not JSON", b"libraries"), ("a member twice", b'{"a":1,"a":2}'),
                               ("a lone surrogate", b'{"x":"\\udc00"}')):
                a = c.raw(c.base + "libraries", body, c.headers(c.base + "libraries", body))
                self.signed(a, 404)
                out.append(name)
            return "signed 404 for " + ", ".join(out)
        self.check("L5", "catalog 2, core 2.3", "a libraries body that isn't an I-JSON object gets a signed 404", bad_body)
        self.titles_checks()

    # ---- catalog: titles (catalog 3, video 3-4, music 2-3) ------------------------------

    def read_titles(self, libs, since=None, after="", limit_pages=400):
        Fail, _ = _x()
        pages = []
        while len(pages) < limit_pages:
            req = {"libraries": libs, "after": after}
            if since is not None:
                req["since"] = since
            a = self.signed(self.client.call("titles", req), 200)
            j = a.json
            for f, t in (("titles", list), ("gone", list), ("next", str), ("changes", bool)):
                if f in j and not isinstance(j[f], t):
                    raise Fail("%s isn't a%s %s: a caller fails the whole answer (catalog 3.3)" % (f, "n" if t is list else "", t.__name__))
            if "seq" in j and not is_int(j["seq"]):
                raise Fail("seq isn't an integer: a caller fails the answer (catalog 3.3)")
            pages.append(j)
            nxt = j.get("next")
            if not isinstance(nxt, str) or nxt == "" or nxt <= after:
                break
            after = nxt
        if len({bool(p.get("changes")) for p in pages}) > 1:
            raise Fail("a reading mixes changes and whole-list pages (catalog 3.2)")
        return pages

    def validate_page(self, j, libs, after, whole):
        bad = []
        titles = j.get("titles") or []
        keys = []
        on = self.parts_on()
        for t in titles:
            _, probs = title_problems(t, libs, on)
            bad += probs
            if isinstance(t, dict) and isinstance(t.get("key"), str):
                keys.append(t["key"])
        bk = [k.encode() for k in keys]
        if bk != sorted(bk) or len(set(bk)) != len(bk):
            bad.append("keys not in strictly ascending byte order (catalog 3.1)")
        if any(k.encode() <= after.encode() for k in keys):
            bad.append("keys not after %r" % after)
        gone = j.get("gone") or []
        if len(titles) + len(gone) > 5000:
            bad.append("more than 5,000 keys in a page")
        if whole and j.get("next") and len(titles) < 5000:
            bad.append("a whole-list page with next but fewer than 5,000 titles (catalog 3.1: next only when full)")
        if whole and j.get("next") and keys and j["next"] != keys[-1]:
            bad.append("next isn't the page's last key")
        if "seq" in j and not j["seq"] > 0:
            bad.append("seq %r isn't positive" % j["seq"])
        if not whole and any(not isinstance(g, str) or len(g.encode()) > 128 for g in gone):
            bad.append("a gone entry that isn't a key of at most 128 bytes")
        return bad

    def titles_checks(self):
        Fail, Skip = _x()
        c = self.client
        libs = sorted(x["id"] for x in self.libraries)

        def need():
            self.need("catalog")
            if not libs:
                raise Skip("the server offers this suite no library: offer one on the server, then run again")

        def whole():
            need()
            pages = self.read_titles(libs)
            bad, after = [], ""
            for j in pages:
                if j.get("changes") is True:
                    bad.append("a reading without since answered with changes")
                bad += self.validate_page(j, libs, after, True)
                ks = [t["key"] for t in (j.get("titles") or []) if isinstance(t, dict) and isinstance(t.get("key"), str)]
                if ks:
                    after = ks[-1]
            self.whole = [t for j in pages for t in (j.get("titles") or []) if isinstance(t, dict)]
            self.seq = pages[0].get("seq")
            if bad:
                raise Fail("\n".join(sorted(set(bad))[:25]))
            kinds = {}
            for t in self.whole:
                kinds[t.get("kind")] = kinds.get(t.get("kind"), 0) + 1
            return "%d titles in %d page(s) (%s), seq %s" % (len(self.whole), len(pages),
                                                          ", ".join("%d %s" % (v, k) for k, v in sorted(kinds.items())), self.seq)
        self.check("T1", "catalog 3, 3.1, 4; video 3, 4; music 2, 3", "titles, the whole list: keys, kinds, libraries, "
                   "members, order, paging", whole)

        def paging():
            need()
            if not self.whole or len(self.whole) < 2:
                raise Skip("fewer than 2 titles offered")
            after = self.whole[0]["key"]
            got = [t["key"] for j in self.read_titles(libs, after=after) for t in (j.get("titles") or [])]
            want = [t["key"] for t in self.whole[1:]]
            if got != want:
                raise Fail("after %r gave %d titles; the whole list has %d after it" % (after, len(got), len(want)))
            return "after %r gives the rest of the list" % after
        self.check("T2", "catalog 3.1", "a page starts strictly after `after`", paging)

        def changes():
            need()
            if not self.seq:
                raise Skip("the server sends no seq: it is asked for the whole list every time (allowed)")
            pages = self.read_titles(libs, since=self.seq)
            j = pages[0]
            if j.get("changes") is not True:
                return (PASS, "the whole list (allowed: catalog 3.2 lets a receiver without the log answer so)")
            bad = sum((self.validate_page(p, libs, "", False) for p in pages), [])
            if bad:
                raise Fail("\n".join(bad))
            return "changes: %d new or changed, %d gone, seq %s" % (len(j.get("titles") or []), len(j.get("gone") or []), j.get("seq"))
        self.check("T3", "catalog 3.2", "titles since the current seq: a changes answer (or the whole list)", changes)

        def above():
            need()
            if not self.seq:
                raise Skip("no seq")
            if self.read_titles(libs, since=self.seq + 1000000)[0].get("changes") is True:
                raise Fail("since above the current seq was answered with changes; catalog 3.2: the whole list")
            return "the whole list"
        self.check("T4", "catalog 3.2", "since above the current seq: the whole list", above)

        def negative():
            need()
            if self.read_titles(libs, since=-1)[0].get("changes") is True:
                raise Fail("a negative since was answered with changes")
            return "the whole list"
        self.check("T5", "catalog 3", "a negative since is answered like 0", negative)

        def bad_requests():
            need()
            L = dumps(libs)
            forms = [("since as a string", dumps({"libraries": libs, "since": "5"})),
                     ("since 1.0", b'{"libraries":%s,"since":1.0}' % L), ("since 1e1", b'{"libraries":%s,"since":1e1}' % L),
                     ("since 2^53", b'{"libraries":%s,"since":9007199254740992}' % L),
                     ("since -0", b'{"libraries":%s,"since":-0}' % L), ("since null", b'{"libraries":%s,"since":null}' % L),
                     ("after over 512 bytes", dumps({"libraries": libs, "after": "a" * 513})),
                     ("after not a string", dumps({"libraries": libs, "after": 5})),
                     ("after null", b'{"libraries":%s,"after":null}' % L),
                     ("a library ID that isn't a string", dumps({"libraries": libs + [7]})),
                     ("libraries missing", b"{}"), ("libraries null", b'{"libraries":null}'),
                     ("libraries a string", dumps({"libraries": libs[0]}))]
            bad = []
            for name, body in forms:
                a = c.raw(c.base + "titles", body, c.headers(c.base + "titles", body))
                self.answers.append(a)
                if not (a.status == 404 and a.signed):
                    bad.append("%s: %s" % (name, a.short()))
            if bad:
                raise Fail("expected a signed 404 for:\n" + "\n".join(bad))
            return "%d bad requests refused with a signed 404" % len(forms)
        self.check("T6", "catalog 3, core 2.3", "bad titles requests (since, after, libraries; null) get a signed 404", bad_requests)

        def unknown_library():
            need()
            j = self.read_titles(["lib_conformance_not_offered"])[0]
            if j.get("titles"):
                raise Fail("titles for a library that isn't offered: %r" % j["titles"][:2])
            return "ignored"
        self.check("T7", "catalog 3, 5", "a library ID that isn't offered is ignored", unknown_library)

        def first_library():
            need()
            if len(libs) < 2:
                raise Skip("one library offered")
            holders = {}
            for lib in libs:
                for p in self.read_titles([lib]):
                    for t in p.get("titles") or []:
                        if isinstance(t, dict):
                            holders.setdefault(t.get("key"), []).append(lib)
            shared = {k: v for k, v in holders.items() if len(v) > 1}
            if not shared:
                return (PASS, "no title is in two libraries; nothing to tell")
            got = {t["key"]: t.get("library") for t in self.whole}
            bad = ["%s: library %r, the first by bytes of %s is %r" % (k, got.get(k), v, min(v, key=str.encode))
                   for k, v in shared.items() if got.get(k) != min(v, key=str.encode)]
            if bad:
                raise Fail("\n".join(bad[:10]))
            return "%d titles in several libraries name the first by bytes" % len(shared)
        self.check("T8", "catalog 3", "a title in several asked libraries names the first in byte order", first_library)

        def watch():
            need()
            ok, why = self.can_ask_operator()
            if not ok:
                raise Skip(why)
            if not self.a.watch_changes:
                raise Skip("run with --watch-changes to have the operator add and remove a title")
            if not self.seq:
                raise Skip("the server sends no seq")
            old = {t["key"] for t in self.whole}
            seen = {}

            def changed():
                pages = self.read_titles(libs, since=self.seq)
                if pages[0].get("changes") is True and any((p.get("titles") or p.get("gone")) for p in pages):
                    seen["pages"] = pages
                    return True
                return False
            self.ask_operator("change", "add one title to an offered library and remove one", changed, self.a.watch_changes)
            if "pages" not in seen:
                raise Skip("no change seen")
            pages = seen["pages"]
            new = [t["key"] for p in pages for t in (p.get("titles") or [])]
            gone = [k for p in pages for k in (p.get("gone") or [])]
            after = [t for p in self.read_titles(libs) for t in (p.get("titles") or []) if isinstance(t, dict)]
            now = {t["key"] for t in after}
            # The titles the checks after this one take (play among them):
            # the list as it is now, not as it was before the change.
            self.whole = after
            expect = (old - set(gone)) | set(new)
            if now != expect:
                raise Fail("the changes don't add up to the new whole list: differ on %s" % sorted(expect ^ now)[:10])
            return "%s new or changed, %s gone, and they add up to the whole list" % (new, gone)
        self.check("T9", "catalog 3.2", "after a change on the server: titles and gone add up to the new whole list", watch,
                   operator=True)

    # ---- playback (playback 2-6, video 5, music 5) -------------------------------------

    def play(self, body):
        """A play, paced below the suggested play limit (core 8.3: 30 a
        minute, bursts of 20), and waiting out a signed retryAfter once."""
        now = time.time()
        self._plays = [t for t in getattr(self, "_plays", []) if t > now - 60]
        if len(self._plays) >= 15:
            time.sleep(2.2)
        self._plays.append(time.time())
        a = self.client.call("play", body)
        if a.status == 429 and a.signed:
            ra = a.json.get("retryAfter") if isinstance(a.json, dict) else None
            wait = ra if is_int(ra) and 0 < ra <= 120 else 10
            self.r.note("play answered 429 rate-limited: waiting %d s and trying again once" % wait)
            time.sleep(wait)
            a = self.client.call("play", body)
        return a

    def stop(self, pb):
        if isinstance(pb, dict) and isinstance(pb.get("id"), str):
            try:
                self.client.call("stop", {"id": pb["id"]})
            except OSError:
                pass

    def playable(self):
        """A title play takes: a film or an episode (video 5), else a track (music 5)."""
        _, Skip = _x()
        on = self.parts_on()
        if "playback" not in on:
            raise Skip("playback isn't on between the server and this suite")
        if not self.whole:
            raise Skip("no titles read (offer a library with a film or an episode)")
        for want in ("movie", "episode", "track"):
            if ("music" if want == "track" else "video") not in on:
                continue
            for t in self.whole:
                if t.get("kind") == want and (video_key(t["key"]) or music_key(t["key"])):
                    return t["key"]
        raise Skip("no film, episode or track among the titles offered")

    def check_playback(self, j, title):
        """Playback 2.3, media 1, video 5.3 and 5.5: the problems of a play answer."""
        bad = []
        if not isinstance(j.get("id"), str) or not PLAY_ID.fullmatch(j["id"]):
            bad.append("id %r doesn't match ^play_[a-z2-7]{26}$" % j.get("id"))
        if j.get("method") not in ("direct", "remux", "transcode"):
            bad.append("method %r" % j.get("method"))
        s = j.get("stream")
        root = self.target + self.client.base[:-len("/api/v1/federation/")] + STREAM
        ticket = None
        if not isinstance(s, dict):
            bad.append("stream isn't an object")
        else:
            url, proto = s.get("url"), s.get("protocol")
            if not isinstance(url, str) or not url.startswith(root):
                bad.append("stream.url %r isn't under the stream root %s (media 1)" % (url, root))
            else:
                rest = url[len(root):]
                parts = rest.split("/")
                if len(parts) != 2 or not TICKET.fullmatch(parts[0]) or any(ch in url for ch in "%?#"):
                    bad.append("stream.url %r isn't <stream root><ticket>/<name> (media 1)" % url)
                else:
                    ticket = parts[0]
                    want = {"hls": "master.m3u8", "file": "file"}.get(proto)
                    if want is None:
                        bad.append("stream.protocol %r isn't hls or file" % proto)
                    elif parts[1] != want:
                        bad.append("a %s stream named %r, not %s (media 1)" % (proto, parts[1], want))
                    if proto == "hls" and s.get("mimeType") not in (None, "application/vnd.apple.mpegurl"):
                        bad.append("stream.mimeType %r for hls" % s.get("mimeType"))
                    if len(ticket) < 22:
                        bad.append("a ticket of %d characters can't hold 128 random bits (media 1)" % len(ticket))
        if not is_int(j.get("positionMs")):
            bad.append("positionMs isn't an integer")
        if "durationMs" in j and not (is_int(j["durationMs"]) and 0 <= j["durationMs"] <= 8640000000):
            bad.append("durationMs %r outside 0 to 100 days" % j["durationMs"])
        vids = []
        for v in j.get("versions", []) if isinstance(j.get("versions"), list) else [None]:
            if not isinstance(v, dict) or not TRACK_ID.fullmatch(str(v.get("id"))) or not isinstance(v.get("name"), str):
                bad.append("a version that isn't {id, name} with an ID of ^[A-Za-z0-9_-]{1,64}$: %r" % v)
            else:
                vids.append(v["id"])
        if "versionId" in j and (not isinstance(j["versionId"], str) or not TRACK_ID.fullmatch(j["versionId"])
                                 or (vids and j["versionId"] not in vids)):
            bad.append("versionId %r isn't one of versions" % j.get("versionId"))

        def tracks(name, prefix):
            out = []
            v = j.get(name)
            if v is None:
                return out
            if not isinstance(v, list):
                bad.append("%s isn't an array" % name)
                return out
            for t in v:
                if not isinstance(t, dict):
                    bad.append("a %s entry isn't an object" % name)
                    continue
                tid = t.get("id")
                if not isinstance(tid, str) or not re.fullmatch(prefix + r"[0-9]{1,3}", tid):
                    bad.append("%s: ID %r isn't %s<n>" % (name, tid, prefix))
                if not isinstance(t.get("label"), str) or not t["label"]:
                    bad.append("%s %s: no label (a viewer's server drops it)" % (name, tid))
                if "role" in t and t["role"] not in ("commentary", "description"):
                    bad.append("%s %s: role %r" % (name, tid, t["role"]))
                for f in ("default", "forced", "hearingImpaired", "pictures"):
                    if f in t and not isinstance(t[f], bool):
                        bad.append("%s %s: %s isn't a boolean" % (name, tid, f))
                if "channels" in t and not is_int(t["channels"]):
                    bad.append("%s %s: channels isn't an integer" % (name, tid))
                if "url" in t:
                    kind = "pictures" if t.get("pictures") else "subtitles"
                    want = "%s%s/%s/%s" % (root, ticket, kind, tid)
                    if t["url"] != want:
                        bad.append("%s %s: url %r isn't %s (video 6.1)" % (name, tid, t["url"], want))
                out.append(t)
            return out

        audio = tracks("audioTracks", "a")
        if "audioTrack" in j and audio and j["audioTrack"] not in [t.get("id") for t in audio]:
            bad.append("audioTrack %r isn't one of audioTracks" % j["audioTrack"])
        if "maxBitrateKbps" in j and not is_int(j["maxBitrateKbps"]):
            bad.append("maxBitrateKbps isn't an integer")
        if "info" in j and not isinstance(j["info"], dict):
            bad.append("info isn't an object")
        is_video = video_key(title) is not None
        if is_video:
            subs = tracks("subtitleTracks", "s")
            tracks("forcedTracks", "s")
            if "subtitleTrack" in j and j["subtitleTrack"] not in [t.get("id") for t in subs]:
                bad.append("subtitleTrack %r isn't one of subtitleTracks" % j["subtitleTrack"])
            if "subtitleStretchSeconds" in j and j["subtitleStretchSeconds"] != 120:
                bad.append("subtitleStretchSeconds %r, not 120 (video 5.3)" % j["subtitleStretchSeconds"])
            segs = j.get("segments")
            if segs is not None:
                if not isinstance(segs, list):
                    bad.append("segments isn't an array")
                else:
                    for sg in segs:
                        if not isinstance(sg, dict) or sg.get("kind") not in ("intro", "outro", "recap", "preview", "commercial") \
                                or not is_int(sg.get("startMs")) or not is_int(sg.get("endMs")) \
                                or not 0 <= sg["startMs"] <= 8640000000 or not 0 <= sg["endMs"] <= 8640000000:
                            bad.append("a skip marker that isn't {kind, startMs, endMs} in range: %r" % sg)
            tp = j.get("trickplay")
            if tp is not None:
                bad += self.check_trickplay(tp, root, ticket)
        else:
            for f in ("subtitleTracks", "forcedTracks", "segments", "trickplay"):
                if j.get(f):
                    bad.append("%s in the answer for a track (music 5: audio only; a viewer's server drops it)" % f)
        return bad, ticket

    @staticmethod
    def check_trickplay(tp, root, ticket):
        bad = []
        if not isinstance(tp, dict):
            return ["trickplay isn't an object"]
        bounds = {"tileWidth": (1, 2048), "tileHeight": (1, 2048), "columns": (1, 100), "rows": (1, 100),
                  "intervalMs": (100, 3600000), "tileCount": (1, MAX)}
        for f, (lo, hi) in bounds.items():
            v = tp.get(f)
            if not is_int(v):
                bad.append("trickplay.%s %r isn't an integer (a viewer's server refuses the whole answer)" % (f, v))
            elif not lo <= v <= hi:
                bad.append("trickplay.%s %r outside %d to %d" % (f, v, lo, hi))
        if bad:
            return bad
        if tp["columns"] * tp["tileWidth"] > 4096 or tp["rows"] * tp["tileHeight"] > 4096:
            bad.append("a full sheet wider or taller than 4,096 pixels")
        sheets = tp.get("sheets")
        per = tp["columns"] * tp["rows"]
        n = -(-tp["tileCount"] // per)
        if not isinstance(sheets, list):
            return bad + ["trickplay.sheets isn't an array"]
        if len(sheets) != n or n > 1000:
            bad.append("trickplay.sheets has %d entries; ceil(tileCount / (columns x rows)) is %d (at most 1,000)" % (len(sheets), n))
        for i, u in enumerate(sheets):
            if u != "%s%s/trickplay/%d" % (root, ticket, i):
                bad.append("sheets[%d] is %r, not <stream root><ticket>/trickplay/%d (video 6.1)" % (i, u, i))
                break
        return bad

    def playback_checks(self):
        Fail, Skip = _x()
        c = self.client
        st = {}

        def title():
            if "key" not in st:
                st["key"] = self.playable()
            return st["key"]

        def bad_bodies():
            k = title()
            series = next((t["key"] for t in self.whole or [] if t.get("kind") in ("series", "season", "artist", "album")), None)
            forms = [("no title", {}), ("title null", {"title": None}), ("title not a string", {"title": 7}),
                     ("startPositionMs -1", {"title": k, "startPositionMs": -1}),
                     ("startPositionMs over 100 days", {"title": k, "startPositionMs": 8640000001}),
                     ("startPositionMs 1.5", {"title": k, "startPositionMs": NonInteger(1.5)}),
                     ("maxBitrateKbps over 10,000,000", {"title": k, "maxBitrateKbps": 10000001}),
                     ("audioLanguage over 12 characters", {"title": k, "audioLanguage": "fr-CA-x-abcdef"}),
                     ("audioLanguage with _", {"title": k, "audioLanguage": "fr_CA"}),
                     ("audioTrack b1", {"title": k, "audioTrack": "b1"}), ("audioTrack a1234", {"title": k, "audioTrack": "a1234"}),
                     ("versionId not a string", {"title": k, "versionId": 7}),
                     ("capabilities not an object", {"title": k, "capabilities": "mp4"}),
                     ("capabilities.containers not an array", {"title": k, "capabilities": {"containers": "mp4"}}),
                     ("capabilities.containers with a number", {"title": k, "capabilities": {"containers": ["mp4", 1]}}),
                     ("a key play doesn't take", {"title": series or "series/tmdb/1399"}),
                     ("a key in no canonical form", {"title": "movie/tmdb/0949"})]
            if video_key(k):
                forms.append(("subtitleTrack x1", {"title": k, "subtitleTrack": "x1"}))
            bad = []
            for name, b in forms:
                a = self.play(b)
                self.answers.append(a)
                if a.status == 200:
                    self.stop(a.json)
                if not (a.status == 400 and a.signed and a.problem_type() == "invalid-request"):
                    bad.append("%s: %s" % (name, a.short()))
            if bad:
                raise Fail("expected a signed 400 invalid-request for:\n" + "\n".join(bad))
            return "%d malformed plays refused with a signed 400" % len(forms)
        self.check("PB1", "playback 2.1, 2.2, video 5.1", "play with a malformed member: the signed 400 invalid-request", bad_bodies)

        def not_held():
            title()
            k = "movie/tmdb/9999999999" if "video" in self.parts_on() else "track/mb/00000000-0000-4000-8000-000000000000"
            a = self.play({"title": k})
            if a.status == 200:
                self.stop(a.json)
            self.signed(a, 404, "not-found")
            return "signed 404 not-found for %s" % k
        self.check("PB2", "playback 2.2", "play of a key the server doesn't offer: a signed 404", not_held)

        def plain():
            k = title()
            a = self.play({"title": k})
            if a.status != 200:
                raise Fail("play %s: %s (offer a playable copy; limits may be 0)" % (k, a.short()))
            self.signed(a, 200)
            bad, ticket = self.check_playback(a.json, k)
            st["pb"], st["ticket"] = a.json, ticket
            if bad:
                raise Fail("\n".join(bad))
            j = a.json
            return "%s: %s over %s, %d audio, %d subtitle tracks%s" % (
                j["id"], j["method"], j["stream"]["protocol"], len(j.get("audioTracks") or []), len(j.get("subtitleTracks") or []),
                ", previews" if j.get("trickplay") else "")
        if not self.check("PB3", "playback 2.3, media 1, video 5.3, 5.5", "play: 200 signed, the playback object in its "
                          "forms, URLs under the stream root", plain):
            self.stop(st.get("pb"))
            return

        def nothing_said():
            j = st["pb"]
            if j["method"] == "direct" or j["stream"]["protocol"] != "hls":
                raise Fail("with no capabilities, %s over %s: nothing said means no direct play, H.264 and AAC (or AAC "
                           "alone for a track) in HLS" % (j["method"], j["stream"]["protocol"]))
            return "%s over hls" % j["method"]
        self.check("PB4", "video 5.1, music 5", "play with nothing said: not direct, HLS", nothing_said)

        self.media_checks(st["pb"], st["key"], "M")

        def progress():
            j = st["pb"]
            for b in ({"id": j["id"], "positionMs": 1000}, {"id": j["id"], "positionMs": 2000, "paused": True}, {"id": j["id"]}):
                a = self.signed(c.call("progress", b), 200)
                if a.json != {}:
                    raise Fail("progress answered %r, not {}" % a.body[:80])
            bad = []
            for name, b in (("an id of another form", {"id": "play_x"}), ("no id", {}),
                            ("positionMs -1", {"id": j["id"], "positionMs": -1}),
                            ("paused not a boolean", {"id": j["id"], "paused": "yes"}),
                            ("positionMs null", {"id": j["id"], "positionMs": None})):
                a = c.call("progress", b)
                self.answers.append(a)
                if not (a.status == 400 and a.signed):
                    bad.append("%s: %s" % (name, a.short()))
            a = c.call("progress", {"id": "play_" + "a" * 26})
            try:
                self.signed(a, 410, "playback-stopped")
            except Fail as e:
                bad.append("a playback ID never given: %s" % e)
            if bad:
                raise Fail("\n".join(bad))
            return "200 {} three times; 400 for malformed bodies; 410 playback-stopped for an ID never given"
        self.check("PB5", "playback 3, 6.1", "progress: 200 {}, 400 for a bad body, 410 for a playback that isn't live", progress)

        def stop():
            j = st["pb"]
            a = self.signed(c.call("stop", {"id": j["id"], "positionMs": 3000}), 200)
            if a.json != {}:
                raise Fail("stop answered %r" % a.body[:80])
            self.signed(c.call("stop", {"id": j["id"]}), 200)
            self.signed(c.call("stop", {"id": "play_" + "b" * 26}), 200)
            bad = []
            a = c.call("progress", {"id": j["id"]})
            try:
                self.signed(a, 410, "playback-stopped")
            except Fail as e:
                bad.append("progress after stop: %s" % e)
            for name, b in (("positionMs -1", {"id": j["id"], "positionMs": -1}), ("no id", {})):
                a = c.call("stop", b)
                self.answers.append(a)
                if not (a.status == 400 and a.signed):
                    bad.append("stop with %s: %s" % (name, a.short()))
            status, _, _ = c.get(j["stream"]["url"])
            if status != 404:
                bad.append("the ticket still works after stop: %d for %s (media 4: it stops at once)" % (status, "the stream"))
            if bad:
                raise Fail("\n".join(bad))
            return "200 {} (twice, and for an ID never given); then progress 410 and the media 404"
        self.check("PB6", "playback 4, 6.1, 6.3, media 4", "stop: 200 {} even when repeated; the playback ends at once", stop)
        self.stop(st["pb"])
        for later in getattr(self, "_subs_later", []):
            self.check(*later)
        self._subs_later = []

        self.track_checks(st["key"], st["pb"])
        self.limit_checks(st["key"])

    def track_checks(self, k, pb):
        Fail, Skip = _x()

        def run(body):
            a = self.play(dict(body, title=k))
            self.signed(a, 200)
            self.stop(a.json)
            return a.json

        audio = [t for t in pb.get("audioTracks") or [] if isinstance(t, dict)]
        subs = [t for t in pb.get("subtitleTracks") or [] if isinstance(t, dict)]

        def audio_rules():
            if not audio:
                raise Skip("the answer lists no audio tracks")
            out = []
            j = run({"audioTrack": "a999"})
            if j.get("audioTrack") != pb.get("audioTrack"):
                raise Fail("audioTrack a999 (not of the copy) gave %r; absent gave %r: it must count as absent"
                           % (j.get("audioTrack"), pb.get("audioTrack")))
            out.append("a999 counts as absent")
            others = [t for t in audio if t.get("id") != pb.get("audioTrack")]
            if others:
                t = others[0]
                j = run({"audioTrack": t["id"]})
                if j.get("audioTrack") != t["id"]:
                    raise Fail("audioTrack %s gave %r" % (t["id"], j.get("audioTrack")))
                out.append("%s chosen" % t["id"])
                default = next((x for x in audio if x.get("id") == pb.get("audioTrack")), {})
                lang = next((x for x in others if x.get("language") and x.get("language") != default.get("language")
                             and not x.get("role")), None)
                if lang:
                    j = run({"audioLanguage": lang["language"]})
                    got = next((x for x in audio if x.get("id") == j.get("audioTrack")), {})
                    if (got.get("language") or "").lower().split("-")[0] != lang["language"].lower().split("-")[0]:
                        raise Fail("audioLanguage %s gave %r (%s)" % (lang["language"], j.get("audioTrack"), got.get("language")))
                    if got.get("role"):
                        raise Fail("audioLanguage %s chose a %s track" % (lang["language"], got["role"]))
                    out.append("audioLanguage %s gives a track in it" % lang["language"])
            return "; ".join(out)
        self.check("PB7", "playback 2.6", "the audio: a track not of the copy counts as absent; a track named; a language", audio_rules)

        def subtitle_rules():
            if not video_key(k):
                raise Skip("not a film or an episode")
            out = []
            j = run({"subtitleTrack": "off"})
            if "subtitleTrack" in j:
                raise Fail("subtitleTrack off gave subtitleTrack %r: none shown" % j["subtitleTrack"])
            out.append("off shows none")
            j = run({"subtitleTrack": "s999"})
            if j.get("subtitleTrack") != pb.get("subtitleTrack"):
                raise Fail("subtitleTrack s999 gave %r; absent gave %r" % (j.get("subtitleTrack"), pb.get("subtitleTrack")))
            out.append("s999 counts as absent")
            if subs:
                t = subs[-1]
                j = run({"subtitleTrack": t["id"]})
                if j.get("subtitleTrack") != t["id"]:
                    raise Fail("subtitleTrack %s gave %r" % (t["id"], j.get("subtitleTrack")))
                out.append("%s chosen" % t["id"])
                lt = next((x for x in subs if x.get("language") and not x.get("forced")), None)
                if lt:
                    j = run({"subtitleLanguage": lt["language"]})
                    got = next((x for x in subs if x.get("id") == j.get("subtitleTrack")), {})
                    if (got.get("language") or "").lower().split("-")[0] != lt["language"].lower().split("-")[0]:
                        raise Fail("subtitleLanguage %s gave %r" % (lt["language"], j.get("subtitleTrack")))
                    out.append("subtitleLanguage %s gives a track in it" % lt["language"])
            if j.get("method") == "transcode" and pb.get("method") != "transcode":
                raise Fail("choosing subtitles made the playback transcode (video 5.4: never burned in)")
            return "; ".join(out)
        self.check("PB8", "video 5.4", "the subtitles: off, a track not of the copy, a track named, a language", subtitle_rules)

        def version_rules():
            out = []
            j = run({"versionId": "conformance-no-such-version"})
            if j.get("versionId") != pb.get("versionId"):
                raise Fail("an unknown versionId gave %r; absent gave %r (playback 2.6: as absent)" % (j.get("versionId"), pb.get("versionId")))
            out.append("an unknown versionId counts as absent")
            vs = [v["id"] for v in pb.get("versions") or [] if isinstance(v, dict) and v.get("id") != pb.get("versionId")]
            if vs:
                j = run({"versionId": vs[0]})
                if j.get("versionId") != vs[0]:
                    raise Fail("versionId %s gave %r" % (vs[0], j.get("versionId")))
                out.append("%s chosen" % vs[0])
            else:
                out.append("one copy only")
            return "; ".join(out)
        self.check("PB9", "playback 2.6", "the copy: an unknown versionId counts as absent; a version named", version_rules)

    def limit_checks(self, k):
        Fail, Skip = _x()
        lim = self.limits if isinstance(self.limits, dict) else None

        def over():
            if lim is None or not is_int(lim.get("streams")):
                raise Skip("the server sends no limits")
            n = lim["streams"]
            if n > 4:
                raise Skip("streams is %d: the suite starts at most 4 playbacks" % n)
            live = []
            try:
                for i in range(n):
                    a = self.play({"title": k, "capabilities": BROAD_CAPS})
                    self.signed(a, 200)
                    live.append(a.json)
                a = self.play({"title": k, "capabilities": BROAD_CAPS})
                if a.status == 200:
                    live.append(a.json)
                    raise Fail("play number %d of a pairing whose streams is %d was answered 200" % (n + 1, n))
                if a.status == 503:
                    self.signed(a, 503, "server-busy")
                    return (PASS, "the %d+1th play: 503 server-busy (it needed a transcode)" % n)
                self.signed(a, 409, "stream-limit-reached")
                return "streams %d: the next play gets 409 stream-limit-reached" % n
            finally:
                for j in live:
                    self.stop(j)
        self.check("PB10", "playback 2.2, 2.5, 6", "past the pairing's streams: 409 stream-limit-reached", over)

        def race():
            if lim is None or not is_int(lim.get("streams")) or not 1 <= lim["streams"] <= 4:
                raise Skip("needs limits with streams 1 to 4")
            n = lim["streams"]
            live = []
            try:
                for _ in range(n - 1):
                    a = self.play({"title": k, "capabilities": BROAD_CAPS})
                    self.signed(a, 200)
                    live.append(a.json)
                with concurrent.futures.ThreadPoolExecutor(2) as ex:
                    res = list(ex.map(lambda _: self.client.call("play", {"title": k, "capabilities": BROAD_CAPS}), range(2)))
                ok = [a for a in res if a.status == 200]
                live += [a.json for a in ok]
                if len(ok) != 1:
                    raise Fail("two plays for the last stream: %s (playback 6.2: exactly one wins)" % [a.short() for a in res])
                return "two plays at once for the last stream: one 200, one %d" % [a for a in res if a.status != 200][0].status
            finally:
                for j in live:
                    self.stop(j)
        self.check("PB11", "playback 6.2", "two plays at once for the last stream: exactly one starts", race)

    # ---- media (media 1-4, video 6) ---------------------------------------------------

    def media_checks(self, pb, title, prefix):
        Fail, Skip = _x()
        c = self.client
        url = pb["stream"]["url"]
        base = url.rsplit("/", 1)[0] + "/"
        st = {}

        def fetch(u, headers=(), method="GET"):
            return c.get(u, headers, method)

        def master():
            if pb["stream"]["protocol"] != "hls":
                raise Skip("a file stream")
            status, hdrs, body = fetch(url)
            if status != 200:
                raise Fail("master.m3u8: %d" % status)
            bad, uris = check_owner_playlist(body, True)
            if bad:
                raise Fail("\n".join(bad))
            if not uris:
                raise Fail("the master playlist names no media playlist")
            st["variant"] = uris[0]
            return "%d bytes, %d media playlist(s), the subset of media 3.1 only" % (len(body), len(uris))
        self.check(prefix + "1", "media 3.1", "master.m3u8: 200, only the master subset, bare names", master)

        def media_playlist():
            if "variant" not in st:
                raise Skip("no master playlist read")
            status, _, body = fetch(base + st["variant"])
            if status != 200:
                raise Fail("%s: %d" % (st["variant"], status))
            bad, uris = check_owner_playlist(body, False)
            if bad:
                raise Fail("\n".join(bad))
            if not uris:
                raise Fail("the media playlist names no segment")
            st["segment"] = uris[0]
            st["segments"] = uris
            return "%s: %d URIs (EXT-X-MAP included), the subset only" % (st["variant"], len(uris))
        self.check(prefix + "2", "media 3.1", "the media playlist: 200, only the media subset, bare names", media_playlist)

        def segment():
            if pb["stream"]["protocol"] == "file":
                st["ranged"] = url
                return "a file stream: ranges checked below"
            if "segment" not in st:
                raise Skip("no segment named")
            u = base + st["segment"]
            for _ in range(30):
                status, hdrs, body = fetch(u)
                if status != 503:
                    break
                time.sleep(2)
            if status != 200:
                raise Fail("%s: %d" % (st["segment"], status))
            st["ranged"], st["size"] = u, len(body)
            return "%s: %d bytes" % (st["segment"], len(body))
        self.check(prefix + "3", "media 3", "the first segment of the media playlist: 200", segment)
        self.range_checks(prefix, st)

        def refusals():
            if pb["stream"]["protocol"] == "hls" and "variant" not in st:
                raise Skip("no playlist read")
            bad = []
            for name, u, hs, method in (("a query string", url + "?x=1", (), "GET"),
                                        ("an Origin header", url, [("Origin", "https://example.org")], "GET"),
                                        ("Sec-Fetch-Site", url, [("Sec-Fetch-Site", "same-origin")], "GET"),
                                        ("Sec-Fetch-Mode", url, [("Sec-Fetch-Mode", "cors")], "GET"),
                                        ("a ticket never given", url.replace("/" + base.rsplit("/", 2)[1] + "/", "/" + b64u(os.urandom(24)) + "/"), (), "GET"),
                                        ("a name that isn't served", base + "conformance-no-such-file", (), "GET")):
                status, _, _ = fetch(u, hs, method)
                if status != 404:
                    bad.append("%s: %d" % (name, status))
            for m in ("POST", "PUT", "DELETE"):
                status, _, _ = fetch(url, (), m)
                if status not in (404, 405):
                    bad.append("%s: %d (media 2.2: 404 or 405)" % (m, status))
            status, hdrs, body = fetch(url, (), "HEAD")
            if status not in (200, 404):
                bad.append("HEAD: %d (media 2.2: as GET without the body, or 404)" % status)
            if bad:
                raise Fail("\n".join(bad))
            return "404 for a query, browser headers, an unknown ticket and name; POST, PUT, DELETE refused; HEAD %d" % status
        self.check(prefix + "4", "media 1, 2, 2.2", "a query, browser headers, a ticket never given: 404; other methods refused", refusals)

        def range_on_playlist():
            if pb["stream"]["protocol"] != "hls":
                raise Skip("a file stream")
            status, hdrs, body = fetch(url, [("Range", "bytes=0-9")])
            if status != 200:
                raise Fail("a Range on master.m3u8 gave %d; media 2.1: the owning server ignores it and sends the whole" % status)
            return "200, the whole playlist"
        self.check(prefix + "5", "media 2.1", "a Range on a playlist is ignored: 200 and the whole", range_on_playlist)

        if not video_key(title):
            return
        def tracks_of(j):
            return [t for t in (j.get("subtitleTracks") or []) + (j.get("forcedTracks") or [])
                    if isinstance(t, dict) and t.get("url")]
        subs = tracks_of(pb)

        def find_track(pictures):
            """A subtitle track with pictures (PGS) or text, with a url: the
            first play's, else one of another film or episode whose title
            lists subtitles, played for it (up to 8). Returns the track, the
            other playback to stop then (or None), and what was played."""
            t = next((x for x in subs if bool(x.get("pictures")) == pictures), None)
            if t or prefix != "M":
                return t, None, title
            others = [x["key"] for x in self.whole if x.get("kind") in ("movie", "episode") and x.get("subtitles")
                      and x["key"] != title and video_key(x["key"])]
            tried = []
            for key in others[:8]:
                a = self.play({"title": key})
                if a.status != 200 or not isinstance(a.json, dict):
                    tried.append("%s: %s" % (key, a.short()))
                    continue
                found = tracks_of(a.json)
                t = next((x for x in found if bool(x.get("pictures")) == pictures), None)
                if t:
                    return t, a.json, key
                tried.append("%s: %d subtitle tracks with a url, none %s" % (key, len(found), "PGS" if pictures else "text"))
                self.stop(a.json)
            return None, None, "; ".join(tried) or "no other title lists subtitles"

        def text_subs():
            t, other, key = find_track(False)
            if not t:
                raise Skip("no text subtitle track with a url, in the first play or in up to 8 others listing subtitles (%s)" % key)
            try:
                return text_part(t) + ("" if other is None else " (of %s, played for it)" % key)
            finally:
                self.stop(other)

        def text_part(t):
            status, hdrs, body = fetch(t["url"] + "/0")
            if status != 200:
                raise Fail("%s/0: %d" % (t["id"], status))
            ct = dict((k.lower(), v) for k, v in hdrs).get("content-type", "")
            try:
                again = rebuild_vtt(body)
            except Refused as e:
                raise Fail("part 0 of %s is refused by video 6.3: %s" % (t["id"], e))
            if again != body:
                raise Fail("part 0 of %s isn't in the rebuilt form video 6.3 writes (the owning server applies the rules "
                           "to what it serves): %r..." % (t["id"], body[:120]))
            if not ct.lower().replace(" ", "").startswith("text/vtt"):
                raise Fail("Content-Type %r, not text/vtt; charset=utf-8" % ct)
            return "%s part 0: %d bytes, in its rebuilt form" % (t["id"], len(body))
        # Without a track of its kind in the first play, a check waits
        # for that playback to stop (PB6): another play may need the
        # stream or the transcode it holds (a server-busy 503 otherwise).
        self._subs_later = []

        def check_subs(cid, section, name, fn, pictures):
            if prefix == "M" and not any(bool(x.get("pictures")) == pictures for x in subs):
                self._subs_later.append((cid, section, name, fn))
            else:
                self.check(cid, section, name, fn)
        check_subs(prefix + "6", "video 6.2, 6.3", "a text subtitle part: 200 text/vtt, already in its rebuilt form", text_subs,
                   False)

        def pgs():
            t, other, key = find_track(True)
            if not t:
                raise Skip("no PGS track with a url, in the first play or in up to 8 others listing subtitles (%s)" % key)
            try:
                return pgs_part(t) + ("" if other is None else " (of %s, played for it)" % key)
            finally:
                self.stop(other)

        def pgs_part(t):
            status, hdrs, body = fetch(t["url"] + "/0")
            if status != 200:
                raise Fail("%s/0: %d" % (t["id"], status))
            try:
                check_pgs(body)
            except Refused as e:
                raise Fail("part 0 of %s fails video 6.4: %s" % (t["id"], e))
            return "%s part 0: %d bytes of valid PGS" % (t["id"], len(body))
        check_subs(prefix + "7", "video 6.2, 6.4", "a PGS part: 200, every segment and object checked", pgs, True)

        def sheets():
            tp = pb.get("trickplay")
            if not isinstance(tp, dict) or not tp.get("sheets"):
                raise Skip("no previews in the answer")
            u = tp["sheets"][0]
            status, hdrs, body = fetch(u)
            if status != 200:
                raise Fail("sheet 0: %d" % status)
            ct = dict((k.lower(), v) for k, v in hdrs).get("content-type", "")
            size = jpeg_size(body)
            bad = []
            if ct.split(";")[0].strip().lower() != "image/jpeg":
                bad.append("Content-Type %r" % ct)
            if len(body) > 8 * 1024 * 1024:
                bad.append("%d bytes, over 8 MiB" % len(body))
            if size is None:
                bad.append("not a JPEG by its header")
            elif size[0] > tp["columns"] * tp["tileWidth"] or size[1] > tp["rows"] * tp["tileHeight"]:
                bad.append("%dx%d, bigger than a full sheet" % size)
            n = len(tp["sheets"])
            root = u.rsplit("/", 1)[0]
            for name, x in (("the sheet count", "%s/%d" % (root, n)), ("a leading zero", "%s/00" % root), ("a query", u + "?x=1")):
                s2, _, _ = fetch(x)
                if s2 != 404:
                    bad.append("%s: %d, not 404" % (name, s2))
            if bad:
                raise Fail("\n".join(bad))
            return "sheet 0: %dx%d JPEG, %d bytes; 404 past the count, with a leading zero, with a query" % (size[0], size[1], len(body))
        self.check(prefix + "8", "video 5.5, 6.2", "a preview sheet: 200 image/jpeg within the layout; 404 past the count", sheets)

    def range_checks(self, prefix, st):
        Fail, Skip = _x()

        def ranges():
            u = st.get("ranged")
            if not u:
                raise Skip("no file or segment fetched")
            c = self.client
            out, bad = [], []
            status, hdrs, body = c.get(u, [("Range", "bytes=0-99")])
            if status == 200:
                return (PASS, "a 200 with the whole to bytes=0-99 (allowed: media 2.1 accepts it); ranges not served")
            if status != 206:
                raise Fail("bytes=0-99: %d" % status)
            why = check_206("", hdrs, body, first=0, last=99)
            if why:
                bad.append("bytes=0-99: " + why)
            total = re.search(r"/([0-9]+)", dict((k.lower(), v) for k, v in hdrs).get("content-range", ""))
            total = int(total.group(1)) if total else None
            for form, kw in (("bytes=-10", {"count": 10}), ("bytes=5-", {"first": 5}), ("bytes=000-009", {"first": 0, "last": 9})):
                s2, h2, b2 = c.get(u, [("Range", form)])
                if s2 == 206:
                    why = check_206(form, h2, b2, **kw)
                    if why:
                        bad.append("%s: %s" % (form, why))
                elif s2 != 200:
                    bad.append("%s: %d" % (form, s2))
            malformed = ["bytes=0-1,5-9", "bytes=-", "bytes=5-1", "items=0-9", "bytes = 0-9", "bytes=0-1234567890123456",
                         "bytes=-0", "bytes=a-b"]
            if total:
                malformed.append("bytes=%d-" % (total + 10))
            for form in malformed:
                s2, _, _ = c.get(u, [("Range", form)])
                if s2 != 416:
                    bad.append("%s: %d, not 416" % (form, s2))
            if bad:
                raise Fail("\n".join(bad))
            return "206s that answer bytes=0-99, -10, 5-, 000-009; 416 for %d malformed or past-the-end ranges" % len(malformed)
        self.check(prefix + "9", "media 2.1", "ranges: the three forms give a matching 206; malformed or past the end give 416", ranges)


MAX = 2**53 - 1
