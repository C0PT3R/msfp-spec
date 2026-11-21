package main

// The music part's rules (spec/v0/music.md): title keys by MusicBrainz
// ID (section 2), and what a caller keeps of a music title (section 3.2),
// with names cleaned as core section 9.1 cleans a server's name.

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"unicode"
)

var (
	mbidForm = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
	isrcForm = regexp.MustCompile(`^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$`)
)

// checkMBID: 36 characters, lowercase hex in groups of 8-4-4-4-12.
func checkMBID(s string) error {
	if len(s) != 36 {
		return fmt.Errorf("an MBID of %d characters, not 36", len(s))
	}
	if !mbidForm.MatchString(s) {
		return errors.New("not a lowercase MBID (8-4-4-4-12 lowercase hex)")
	}
	return nil
}

// checkMusicKey returns the kind a music title key names.
func checkMusicKey(key string) (string, error) {
	p := strings.Split(key, "/")
	if len(p) != 3 {
		return "", fmt.Errorf("%d parts joined by /, not 3", len(p))
	}
	switch p[0] {
	case "artist", "album", "track":
	default:
		return "", fmt.Errorf("kind %q is not a music kind", p[0])
	}
	if p[1] != "mb" {
		return "", fmt.Errorf("scheme %q is not mb", p[1])
	}
	if err := checkMBID(p[2]); err != nil {
		return "", err
	}
	return p[0], nil
}

// cleanName is core section 9.1's cleaning, with max code points
// instead of 80.
func cleanName(s string, max int) string {
	var b strings.Builder
	space := false
	for _, r := range s { // 1. runs of White_Space become one space
		if unicode.Is(unicode.White_Space, r) {
			if !space {
				b.WriteByte(' ')
			}
			space = true
			continue
		}
		space = false
		b.WriteRune(r)
	}
	t := strings.Map(func(r rune) rune { // 2. Cc and Cf removed
		if unicode.Is(unicode.Cc, r) || unicode.Is(unicode.Cf, r) {
			return -1
		}
		return r
	}, b.String())
	t = strings.Trim(t, " ") // 3. both ends trimmed
	if r := []rune(t); len(r) > max {
		t = string(r[:max]) // 4. cut, then trimmed again
	}
	return strings.Trim(t, " ")
}

// musicTitle is what a caller keeps of a music title, in the order the
// vectors write it.
type musicTitle struct {
	Key         string            `json:"key"`
	Kind        string            `json:"kind"`
	Library     string            `json:"library"`
	Name        string            `json:"name"`
	Artists     []string          `json:"artists,omitempty"`
	ArtistNames string            `json:"artistNames,omitempty"`
	Album       string            `json:"album,omitempty"`
	Disc        *int64            `json:"disc,omitempty"`
	Number      *int64            `json:"number,omitempty"`
	Year        *int64            `json:"year,omitempty"`
	DurationMs  *int64            `json:"durationMs,omitempty"`
	IDs         map[string]string `json:"ids,omitempty"`
}

// musicIDKinds: the kinds each scheme of ids is for (music section 3.1).
var musicIDKinds = map[string][]string{
	"mbrelease": {"album", "track"},
	"mbtrack":   {"track"},
	"isrc":      {"track"},
}

func kindIn(kind string, kinds ...string) bool {
	for _, k := range kinds {
		if k == kind {
			return true
		}
	}
	return false
}

// keepMusicTitle applies catalog section 3.3 and music section 3.2 to one
// entry of titles, given the libraries the caller asked for. It returns
// what the caller keeps, written as JSON, or why the title is skipped.
func keepMusicTitle(raw []byte, libraries []string) ([]byte, error) {
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
	keyKind, err := checkMusicKey(key)
	if err != nil {
		return nil, fmt.Errorf("key: %v", err)
	}
	if kind != keyKind {
		return nil, fmt.Errorf("kind %q, but the key names a %s", kind, keyKind)
	}
	if !kindIn(lib, libraries...) {
		return nil, fmt.Errorf("library %q wasn't asked for", lib)
	}
	t := musicTitle{Key: key, Kind: kind, Library: lib}
	name, _ := text("name")
	if t.Name = cleanName(name, 256); t.Name == "" {
		return nil, errors.New("no name, once cleaned")
	}
	if kindIn(kind, "album", "track") {
		if a, ok := o["artists"].([]any); ok {
			seen := map[string]bool{}
			for _, e := range a {
				s, ok := e.(string)
				if !ok || seen[s] || len(t.Artists) == 16 {
					continue
				}
				if k, err := checkMusicKey(s); err == nil && k == "artist" {
					seen[s] = true
					t.Artists = append(t.Artists, s)
				}
			}
		}
		an, _ := text("artistNames")
		t.ArtistNames = cleanName(an, 512)
		t.Year = integerIn(o["year"], 1000, 9999)
	}
	if kind == "track" {
		if a, ok := text("album"); ok {
			if k, err := checkMusicKey(a); err == nil && k == "album" {
				t.Album = a
			}
		}
		t.Disc = integerIn(o["disc"], 1, 999)
		t.Number = integerIn(o["number"], 1, 999)
		// 0 counts as absent (music section 3.2).
		t.DurationMs = integerIn(o["durationMs"], 1, 86_400_000)
	}
	if ids, ok := o["ids"].(map[string]any); ok {
		for scheme, val := range ids {
			s, ok := val.(string)
			kinds, known := musicIDKinds[scheme]
			if !ok || !known || !kindIn(kind, kinds...) {
				continue
			}
			if (scheme == "isrc" && isrcForm.MatchString(s)) || (scheme != "isrc" && checkMBID(s) == nil) {
				if t.IDs == nil {
					t.IDs = map[string]string{}
				}
				t.IDs[scheme] = s
			}
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

// integerIn reads an MSFP integer (core section 2.3) in [lo, hi]; any
// other value counts as absent.
func integerIn(v any, lo, hi int64) *int64 {
	n, ok := v.(json.Number)
	if !ok || checkInteger(n.String()) != nil {
		return nil
	}
	i, err := strconv.ParseInt(n.String(), 10, 64)
	if err != nil || i < lo || i > hi {
		return nil
	}
	return &i
}
