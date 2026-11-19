package main

import "strings"

// The libraries the caller asked for, in every video title case.
var videoLibraries = []string{"v1", "v2"}

type v1VideoFile struct {
	About     []string    `json:"about"`
	Libraries []string    `json:"libraries"`
	Titles    []titleCase `json:"titles"`
}

func videoTitleCases() []titleCase {
	film := `"key":"movie/tmdb/949","kind":"movie","library":"v1"`
	bare := `"key":"series/tmdb/1399/e63056","kind":"episode","library":"v2"`
	episode := bare + `,"place":{"season":1,"episode":1}`
	series := `"key":"series/tmdb/1399","kind":"series","library":"v2"`
	season := `"key":"series/tmdb/1399/s1","kind":"season","library":"v2"`
	var tags []string
	for i := 0; i < 14; i++ {
		tags = append(tags, `"x`+string(rune('a'+i))+`"`)
	}
	var with []string
	for i := 0; i < 18; i++ {
		with = append(with, `"series/tmdb/1399/e630`+string(rune('6'+i/10))+string(rune('0'+i%10))+`"`)
	}
	in := []struct{ name, text string }{
		{"a film with every member", `{` + film + `,"audio":["en","fr-CA"],"subtitles":["fr"],"video":{"height":2160,"hdr":["hdr10","dv"]},"ids":{"imdb":"tt0113277"}}`},
		{"an episode with every member", `{` + episode + `,"audio":["en"],"subtitles":["en","fr"],"video":{"height":1080},"with":["series/tmdb/1399/e63057"],"ids":{"imdb":"tt1480055"}}`},
		{"a series", `{` + series + `,"ids":{"imdb":"tt0944947","tvdb":"121361"}}`},
		{"a season", `{` + season + `}`},
		{"an episode by its numbers", `{"key":"series/tmdb/1399/s1/e2","kind":"episode","library":"v2","video":{"height":720}}`},
		{"place: season 0 and episode 0 (a special, a pilot)", `{` + bare + `,"place":{"season":0,"episode":0}}`},
		{"place: the largest numbers", `{` + bare + `,"place":{"season":9999,"episode":99999}}`},
		{"place: other members ignored", `{` + bare + `,"place":{"season":2,"episode":5,"absolute":17}}`},
		{"place missing on an episode keyed by its TMDB ID: skipped", `{` + bare + `,"video":{"height":1080}}`},
		{"place that isn't an object: skipped", `{` + bare + `,"place":[1,1]}`},
		{"place without an episode: skipped", `{` + bare + `,"place":{"season":1}}`},
		{"place with a season above 9,999: skipped", `{` + bare + `,"place":{"season":10000,"episode":1}}`},
		{"place with an episode above 99,999: skipped", `{` + bare + `,"place":{"season":1,"episode":100000}}`},
		{"place with a negative number: skipped", `{` + bare + `,"place":{"season":-1,"episode":1}}`},
		{"place with numbers as strings: skipped", `{` + bare + `,"place":{"season":"1","episode":"1"}}`},
		{"place with a number that isn't an MSFP integer: skipped", `{` + bare + `,"place":{"season":1,"episode":1.0}}`},
		{"place of an episode keyed by its numbers: ignored", `{"key":"series/tmdb/1399/s1/e2","kind":"episode","library":"v2","place":{"season":3,"episode":4}}`},
		{"place of a film: ignored", `{` + film + `,"place":{"season":1,"episode":1}}`},
		{"video: standard range", `{` + film + `,"video":{"height":480}}`},
		{"video: every height", `{` + film + `,"video":{"height":4320,"hdr":["hlg"]}}`},
		{"video: 1440", `{` + film + `,"video":{"height":1440}}`},
		{"video: hdr kept in the order hdr10, hlg, dv", `{` + film + `,"video":{"height":2160,"hdr":["dv","hlg","hdr10"]}}`},
		{"video: hdr repeats, unknown formats and non-strings skipped", `{` + film + `,"video":{"height":2160,"hdr":["dv","HDR10","hdr10+","dv",7,null,"hdr10"]}}`},
		{"video: an empty hdr is standard range", `{` + film + `,"video":{"height":1080,"hdr":[]}}`},
		{"video: hdr of only unknown formats is standard range", `{` + film + `,"video":{"height":1080,"hdr":["hdr10plus"]}}`},
		{"video: other members ignored", `{` + film + `,"video":{"height":1080,"codec":"hevc","width":1920}}`},
		{"video: a height not among the six: absent", `{` + film + `,"video":{"height":1600,"hdr":["hdr10"]}}`},
		{"video: a height below 480: absent", `{` + film + `,"video":{"height":360}}`},
		{"video: a height above 4320: absent", `{` + film + `,"video":{"height":8640}}`},
		{"video: a height of 0: absent", `{` + film + `,"video":{"height":0}}`},
		{"video: a height that isn't an MSFP integer: absent", `{` + film + `,"video":{"height":1080.0}}`},
		{"video: a height as a string: absent", `{` + film + `,"video":{"height":"1080"}}`},
		{"video: a height in exponent form: absent", `{` + film + `,"video":{"height":1.08e3}}`},
		{"video: no height: absent", `{` + film + `,"video":{"hdr":["hdr10"]}}`},
		{"video: a null height: absent", `{` + film + `,"video":{"height":null}}`},
		{"video: hdr that isn't an array: absent", `{` + film + `,"video":{"height":2160,"hdr":"hdr10"}}`},
		{"video: a null hdr: absent", `{` + film + `,"video":{"height":2160,"hdr":null}}`},
		{"video that isn't an object: absent", `{` + film + `,"video":[2160]}`},
		{"video as a string: absent", `{` + film + `,"video":"2160p"}`},
		{"video of a series: ignored", `{` + series + `,"video":{"height":2160}}`},
		{"video of a season: ignored", `{` + season + `,"video":{"height":2160},"audio":["en"]}`},
		{"languages: bad, repeated (without case) and non-string tags skipped, the first 12 kept", `{` + film + `,"audio":["e","en","EN","fr_CA","abcdefghijklm",7,` + strings.Join(tags, ",") + `]}`},
		{"languages that aren't arrays: absent", `{` + film + `,"audio":"en","subtitles":{"en":true}}`},
		{"with: other series, itself, films, seasons, repeats skipped, the first 16 kept", `{` + episode + `,"with":["series/tmdb/1400/e63057","series/tmdb/1399/e63056","movie/tmdb/949","series/tmdb/1399/s1","series/tmdb/1399/e063057",` + strings.Join(with[:2], ",") + `,` + with[0] + `,` + strings.Join(with[2:], ",") + `]}`},
		{"with of a film: ignored", `{` + film + `,"with":["series/tmdb/1399/e63057"]}`},
		{"ids: values out of form, unknown schemes and non-strings skipped", `{` + film + `,"ids":{"imdb":"tt01133","tvdb":"081189","tmdb":"949","mb":"x"}}`},
		{"ids: one good, one not a string", `{` + film + `,"ids":{"imdb":7,"tvdb":"81189"}}`},
		{"ids of a season: ignored", `{` + season + `,"ids":{"tvdb":"81189"}}`},
		{"a kind that doesn't match the key: skipped", `{"key":"movie/tmdb/949","kind":"series","library":"v1","video":{"height":1080}}`},
		{"a library not asked for: skipped", `{"key":"movie/tmdb/949","kind":"movie","library":"v3"}`},
		{"a key with a leading zero: skipped", `{"key":"movie/tmdb/0949","kind":"movie","library":"v1"}`},
		{"a TMDB ID above 9,999,999,999: skipped", `{"key":"movie/tmdb/10000000000","kind":"movie","library":"v1"}`},
		{"a music key: skipped", `{"key":"track/mb/0c000000-0000-4000-8000-000000000003","kind":"track","library":"v1"}`},
		{"a key that isn't a string: skipped", `{"key":949,"kind":"movie","library":"v1"}`},
		{"not an object: skipped", `"movie/tmdb/949"`},
	}
	var out []titleCase
	for _, c := range in {
		got, err := keepVideoTitle([]byte(c.text), videoLibraries)
		ok, r := reason(err)
		out = append(out, titleCase{Name: c.name, Text: c.text, Valid: ok, Output: string(got), Reason: r})
	}
	return out
}

func genV1Video() []byte {
	return encode(v1VideoFile{
		About: []string{
			"MSFP video part version 1 (spec/v1/video.md): what a caller keeps of a video title (section 3.1), its picture (video, section 3.2) included. Generated by tools/vectors; no implementation has produced them yet.",
			"titles: text is one entry of a titles answer, as JSON; the caller asked for the libraries listed in libraries. valid false: the caller skips the title. valid true: output is what it keeps, members in this order: key, kind, library, audio, subtitles, video (height, hdr), place (season, episode), with, ids (its members sorted); absent members left out.",
			"Title keys themselves are in spec/v1/video.md section 4; the WebVTT and PGS cases of video section 6 are in media.json.",
		},
		Libraries: videoLibraries,
		Titles:    videoTitleCases(),
	})
}
