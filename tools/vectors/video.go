package main

// The video part's titles (spec/v1/video.md): title keys by TMDB ID
// (section 4), and what a caller keeps of a video title (section 3.1),
// its picture (section 3.2) included.

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
)

var (
	movieKey   = regexp.MustCompile(`^movie/tmdb/([1-9][0-9]{0,9})$`)
	seriesKey  = regexp.MustCompile(`^series/tmdb/([1-9][0-9]{0,9})((/s(0|[1-9][0-9]{0,3}))(/e(0|[1-9][0-9]{0,4}))?|/e[1-9][0-9]{0,9})?$`)
	tagForm    = regexp.MustCompile(`^[A-Za-z0-9-]{2,12}$`)
	imdbForm   = regexp.MustCompile(`^tt[0-9]{7,10}$`)
	tvdbForm   = regexp.MustCompile(`^[1-9][0-9]{0,9}$`)
	heights    = []int64{480, 720, 1080, 1440, 2160, 4320}
	hdrFormats = []string{"hdr10", "hlg", "dv"}
)

// checkVideoKey returns the kind a video title key names and the TMDB ID
// of its film or series.
func checkVideoKey(key string) (kind, id string, err error) {
	if m := movieKey.FindStringSubmatch(key); m != nil {
		return "movie", m[1], tmdbRange(m[1])
	}
	m := seriesKey.FindStringSubmatch(key)
	if m == nil {
		return "", "", errors.New("not a canonical video title key")
	}
	switch {
	case m[2] == "":
		kind = "series"
	case m[3] != "" && m[5] == "":
		kind = "season"
	default:
		kind = "episode"
	}
	return kind, m[1], tmdbRange(m[1])
}

// tmdbRange: 1 to 9,999,999,999.
func tmdbRange(id string) error {
	if len(id) == 10 && id > "9999999999" {
		return errors.New("a TMDB ID above 9,999,999,999")
	}
	return nil
}

// videoPicture is a title's video, as the vectors write it.
type videoPicture struct {
	Height int64    `json:"height"`
	HDR    []string `json:"hdr,omitempty"`
}

// videoPlace is an episode's place in TMDB's numbering (section 4.1).
type videoPlace struct {
	Season  int64 `json:"season"`
	Episode int64 `json:"episode"`
}

// videoTitle is what a caller keeps of a video title, in the order the
// vectors write it.
type videoTitle struct {
	Key       string            `json:"key"`
	Kind      string            `json:"kind"`
	Library   string            `json:"library"`
	Audio     []string          `json:"audio,omitempty"`
	Subtitles []string          `json:"subtitles,omitempty"`
	Video     *videoPicture     `json:"video,omitempty"`
	Place     *videoPlace       `json:"place,omitempty"`
	With      []string          `json:"with,omitempty"`
	IDs       map[string]string `json:"ids,omitempty"`
}

// keepTags: at most 12, each 2 to 12 of A–Z a–z 0–9 -, each once
// without case; anything else skipped alone. Not an array: none.
func keepTags(v any) []string {
	list, _ := v.([]any)
	var out []string
	for _, e := range list {
		s, ok := e.(string)
		if !ok || !tagForm.MatchString(s) || len(out) == 12 {
			continue
		}
		dup := false
		for _, o := range out {
			dup = dup || strings.EqualFold(o, s)
		}
		if !dup {
			out = append(out, s)
		}
	}
	return out
}

// keepPicture reads video (section 3.1): nil, absent, for anything but
// an object with a height among the six, as an MSFP integer, and no hdr
// or an array for it.
func keepPicture(v any) *videoPicture {
	o, ok := v.(map[string]any)
	if !ok {
		return nil
	}
	h := integerIn(o["height"], 480, 4320)
	if h == nil || !containsInt(heights, *h) {
		return nil
	}
	p := &videoPicture{Height: *h}
	raw, present := o["hdr"]
	if !present {
		return p
	}
	list, ok := raw.([]any)
	if !ok {
		return nil
	}
	have := map[string]bool{}
	for _, e := range list {
		if s, ok := e.(string); ok {
			have[s] = true
		}
	}
	for _, f := range hdrFormats {
		if have[f] {
			p.HDR = append(p.HDR, f)
		}
	}
	return p
}

func containsInt(list []int64, n int64) bool {
	for _, v := range list {
		if v == n {
			return true
		}
	}
	return false
}

// keepVideoTitle applies catalog section 3.3 and video section 3.1 to
// one entry of titles, given the libraries the caller asked for. It
// returns what the caller keeps, written as JSON, or why the title is
// skipped.
func keepVideoTitle(raw []byte, libraries []string) ([]byte, error) {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	var v any
	if err := d.Decode(&v); err != nil {
		return nil, err
	}
	o, ok := v.(map[string]any)
	if !ok {
		return nil, errors.New("not an object")
	}
	text := func(k string) (string, bool) { s, ok := o[k].(string); return s, ok }
	key, ok1 := text("key")
	kind, ok2 := text("kind")
	lib, ok3 := text("library")
	if !ok1 || !ok2 || !ok3 {
		return nil, errors.New("key, kind or library isn't a string")
	}
	keyKind, id, err := checkVideoKey(key)
	if err != nil {
		return nil, fmt.Errorf("key: %v", err)
	}
	if kind != keyKind {
		return nil, fmt.Errorf("kind %q, but the key names a %s", kind, keyKind)
	}
	if !kindIn(lib, libraries...) {
		return nil, fmt.Errorf("library %q wasn't asked for", lib)
	}
	t := videoTitle{Key: key, Kind: kind, Library: lib}
	if kind == "movie" || kind == "episode" {
		t.Audio, t.Subtitles = keepTags(o["audio"]), keepTags(o["subtitles"])
		t.Video = keepPicture(o["video"])
	}
	if kind == "episode" && !strings.Contains(key, "/s") {
		// Keyed by TMDB's episode ID: its place is required (section 4.1).
		p, ok := o["place"].(map[string]any)
		if !ok {
			return nil, errors.New("an episode keyed by its TMDB ID without a place")
		}
		season, episode := integerIn(p["season"], 0, 9999), integerIn(p["episode"], 0, 99999)
		if season == nil || episode == nil {
			return nil, errors.New("place: season or episode missing or out of range")
		}
		t.Place = &videoPlace{Season: *season, Episode: *episode}
	}
	if kind == "episode" {
		list, _ := o["with"].([]any)
		for _, e := range list {
			s, ok := e.(string)
			if !ok || s == key || len(t.With) == 16 || kindIn(s, t.With...) {
				continue
			}
			if k, other, err := checkVideoKey(s); err == nil && k == "episode" && other == id {
				t.With = append(t.With, s)
			}
		}
	}
	if ids, ok := o["ids"].(map[string]any); ok && kind != "season" {
		for scheme, val := range ids {
			s, ok := val.(string)
			if !ok || !(scheme == "imdb" && imdbForm.MatchString(s) || scheme == "tvdb" && tvdbForm.MatchString(s)) {
				continue
			}
			if t.IDs == nil {
				t.IDs = map[string]string{}
			}
			t.IDs[scheme] = s
		}
	}
	var buf bytes.Buffer
	e := json.NewEncoder(&buf)
	e.SetEscapeHTML(false)
	if err := e.Encode(t); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(buf.Bytes(), []byte("\n")), nil
}
