package main

import "strings"

// The libraries the caller asked for, in every music title case.
var musicLibraries = []string{"m1", "m2"}

// Made-up MBIDs for the cases.
const (
	mbArtist  = "0a000000-0000-4000-8000-000000000001"
	mbArtist2 = "0a000000-0000-4000-8000-000000000004"
	mbAlbum   = "0b000000-0000-4000-8000-000000000002"
	mbTrack   = "0c000000-0000-4000-8000-000000000003"
	mbRelease = "0d000000-0000-4000-8000-000000000005"
	mbOnRel   = "0e000000-0000-4000-8000-000000000006"
)

// keyCase is a music title key, its verdict, and the kind it names.
type keyCase struct {
	Name   string `json:"name"`
	Text   string `json:"text"`
	Valid  bool   `json:"valid"`
	Kind   string `json:"kind,omitempty"`
	Reason string `json:"reason,omitempty"`
}

// titleCase is one entry of titles and what the caller keeps of it.
type titleCase struct {
	Name   string `json:"name"`
	Text   string `json:"text"`
	Valid  bool   `json:"valid"`
	Output string `json:"output,omitempty"`
	Reason string `json:"reason,omitempty"`
}

type v1MusicFile struct {
	About     []string    `json:"about"`
	Libraries []string    `json:"libraries"`
	Keys      []keyCase   `json:"keys"`
	Titles    []titleCase `json:"titles"`
}

func musicKeyCases() []keyCase {
	in := []struct{ name, text string }{
		{"an artist", "artist/mb/" + mbArtist},
		{"an album (a release group)", "album/mb/" + mbAlbum},
		{"a track (a recording)", "track/mb/" + mbTrack},
		{"another track", "track/mb/9f3c1e2a-7b4d-4c8e-a1f0-2d6b8e4c7a95"},
		{"uppercase hex", "track/mb/0C000000-0000-4000-8000-000000000003"},
		{"without hyphens", "track/mb/0c000000000040008000000000000003"},
		{"in braces", "track/mb/{0c000000-0000-4000-8000-000000000003}"},
		{"as a URN", "track/mb/urn:uuid:0c000000-0000-4000-8000-000000000003"},
		{"one character short", "track/mb/0c000000-0000-4000-8000-00000000003"},
		{"one character long", "track/mb/0c000000-0000-4000-8000-0000000000003"},
		{"a letter that isn't hex", "track/mb/0g000000-0000-4000-8000-000000000003"},
		{"hyphens in the wrong places", "track/mb/0c0000000-000-4000-8000-000000000003"},
		{"an empty identifier", "track/mb/"},
		{"a release isn't a kind", "release/mb/" + mbRelease},
		{"a recording isn't a kind: tracks are", "recording/mb/" + mbTrack},
		{"song isn't a kind", "song/mb/" + mbTrack},
		{"a kind in another case", "Track/mb/" + mbTrack},
		{"another scheme", "track/musicbrainz/" + mbTrack},
		{"the scheme in another case", "track/MB/" + mbTrack},
		{"a part after the identifier", "track/mb/" + mbTrack + "/s1"},
		{"a trailing slash", "track/mb/" + mbTrack + "/"},
		{"a space before", " track/mb/" + mbTrack},
		{"a video key", "movie/tmdb/949"},
	}
	var out []keyCase
	for _, c := range in {
		k, err := checkMusicKey(c.text)
		ok, r := reason(err)
		out = append(out, keyCase{Name: c.name, Text: c.text, Valid: ok, Kind: k, Reason: r})
	}
	return out
}

func musicTitleCases() []titleCase {
	track := `"key":"track/mb/` + mbTrack + `","kind":"track","library":"m1"`
	album := `"key":"album/mb/` + mbAlbum + `","kind":"album","library":"m1"`
	artist := `"key":"artist/mb/` + mbArtist + `","kind":"artist","library":"m2"`
	ak := func(id string) string { return `"artist/mb/` + id + `"` }
	var many []string
	for i := 0; i < 18; i++ {
		many = append(many, ak("0a000000-0000-4000-8000-0000000001"+string(rune('a'+i/10))+string(rune('0'+i%10))))
	}
	many = append(many[:2], append([]string{ak(mbArtist), `"album/mb/` + mbAlbum + `"`, `"ARTIST"`, `7`, ak(mbArtist)}, many[2:]...)...)
	long := strings.Repeat("é", 255) + "ab"
	in := []struct{ name, text string }{
		{"a track with every member", `{` + track + `,"name":"The Boxer","artists":[` + ak(mbArtist) + `],"artistNames":"Simon & Garfunkel","album":"album/mb/` + mbAlbum + `","disc":1,"number":2,"year":1970,"durationMs":308000,"ids":{"mbrelease":"` + mbRelease + `","mbtrack":"` + mbOnRel + `","isrc":"USSM17000123"}}`},
		{"an album", `{` + album + `,"name":"Bridge","artists":[` + ak(mbArtist) + `,` + ak(mbArtist2) + `],"artistNames":"A & B","year":1970,"ids":{"mbrelease":"` + mbRelease + `"}}`},
		{"an artist", `{` + artist + `,"name":"Simon & Garfunkel"}`},
		{"names cleaned: white space runs, controls and format characters", `{` + track + `,"name":"  The\t\tBoxer\n\u0007(live)‮ ","artistNames":" Simon &​Garfunkel "}`},
		{"a format character between spaces leaves two", `{` + artist + `,"name":"a ​ b"}`},
		{"a name cut to 256 code points, then trimmed", `{` + artist + `,"name":"` + strings.Repeat("é", 255) + ` b"}`},
		{"a name cut to 256 code points", `{` + artist + `,"name":"` + long + `"}`},
		{"artistNames cut to 512 code points", `{` + track + `,"name":"x","artistNames":"` + strings.Repeat("a", 511) + `bc"}`},
		{"no name: skipped", `{` + track + `}`},
		{"a name empty once cleaned: skipped", `{` + track + `,"name":" ​\t "}`},
		{"a name that isn't a string: skipped", `{` + track + `,"name":7}`},
		{"a null name: skipped", `{` + track + `,"name":null}`},
		{"a kind that doesn't match the key: skipped", `{"key":"track/mb/` + mbTrack + `","kind":"album","library":"m1","name":"x"}`},
		{"a library not asked for: skipped", `{"key":"track/mb/` + mbTrack + `","kind":"track","library":"m3","name":"x"}`},
		{"a key in uppercase: skipped", `{"key":"track/mb/0C000000-0000-4000-8000-000000000003","kind":"track","library":"m1","name":"x"}`},
		{"a video key: skipped", `{"key":"movie/tmdb/949","kind":"movie","library":"m1","name":"x"}`},
		{"a key that isn't a string: skipped", `{"key":7,"kind":"track","library":"m1","name":"x"}`},
		{"not an object: skipped", `"track/mb/` + mbTrack + `"`},
		{"artists: bad, repeated and non-string entries skipped, the first 16 kept", `{` + track + `,"name":"x","artists":[` + strings.Join(many, ",") + `]}`},
		{"artists that isn't an array: absent", `{` + track + `,"name":"x","artists":` + ak(mbArtist) + `}`},
		{"numbers at their bounds", `{` + track + `,"name":"x","disc":999,"number":1,"year":1000,"durationMs":0}`},
		{"numbers at their other bounds", `{` + track + `,"name":"x","disc":1,"number":999,"year":9999,"durationMs":86400000}`},
		{"numbers out of range: absent", `{` + track + `,"name":"x","disc":0,"number":1000,"year":999,"durationMs":86400001}`},
		{"numbers that aren't MSFP integers: absent", `{` + track + `,"name":"x","disc":1.0,"number":"2","year":1.97e3,"durationMs":-0}`},
		{"an album key that isn't one: absent", `{` + track + `,"name":"x","album":"artist/mb/` + mbArtist + `"}`},
		{"members of other kinds ignored", `{` + album + `,"name":"x","album":"album/mb/` + mbAlbum + `","disc":1,"number":1,"durationMs":1000,"ids":{"mbtrack":"` + mbOnRel + `","isrc":"USSM17000123"}}`},
		{"an artist carries no artists, artistNames or year", `{` + artist + `,"name":"x","artists":[` + ak(mbArtist2) + `],"artistNames":"y","year":1970,"ids":{"mbrelease":"` + mbRelease + `"}}`},
		{"ids: values out of form, unknown schemes and non-strings skipped", `{` + track + `,"name":"x","ids":{"mbrelease":"0D000000-0000-4000-8000-000000000005","mbtrack":"` + mbOnRel + `","isrc":"ussm17000123","discogs":"123","imdb":"tt0133093"}}`},
		{"ids: an ISRC that isn't a string", `{` + track + `,"name":"x","ids":{"isrc":7,"mbtrack":"` + mbOnRel + `"}}`},
		{"ids that isn't an object: absent", `{` + track + `,"name":"x","ids":["` + mbRelease + `"]}`},
	}
	var out []titleCase
	for _, c := range in {
		got, err := keepMusicTitle([]byte(c.text), musicLibraries)
		ok, r := reason(err)
		out = append(out, titleCase{Name: c.name, Text: c.text, Valid: ok, Output: string(got), Reason: r})
	}
	return out
}

func genV1Music() []byte {
	return encode(v1MusicFile{
		About: []string{
			"MSFP music part version 1 (spec/v1/music.md): title keys by MusicBrainz ID (section 2) and what a caller keeps of a music title (section 3.2). Generated by tools/vectors; no implementation has produced them yet. The MBIDs are made up.",
			"keys: valid says whether the text is a music title key; kind is the kind it names.",
			"titles: text is one entry of a titles answer, as JSON; the caller asked for the libraries listed in libraries. valid false: the caller skips the title. valid true: output is what it keeps, members in this order: key, kind, library, name, artists, artistNames, album, disc, number, year, durationMs, ids (its members sorted); absent members left out.",
			"Names are cleaned as spec/v1/core.md section 9.1 cleans a server's name, with 256 code points for name and 512 for artistNames.",
		},
		Libraries: musicLibraries,
		Keys:      musicKeyCases(),
		Titles:    musicTitleCases(),
	})
}
