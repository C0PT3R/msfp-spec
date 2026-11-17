package main

import (
	"encoding/binary"
	"encoding/hex"
	"strings"
	"unicode/utf8"
)

// vttCase is a WebVTT part and what rebuilding it gives.
type vttCase struct {
	Name   string `json:"name"`
	Text   string `json:"text,omitempty"`
	Hex    string `json:"hex,omitempty"`
	Valid  bool   `json:"valid"`
	Output string `json:"output,omitempty"`
	Reason string `json:"reason,omitempty"`
}

type v1MediaFile struct {
	About  []string  `json:"about"`
	WebVTT []vttCase `json:"webvtt"`
	HLS    []verdict `json:"hls"`
	PGS    []verdict `json:"pgs"`
}

const cue = "00:00:01.000 --> 00:00:02.000\n"

func vttCases() []vttCase {
	in := []struct{ name, text string }{
		{"a plain cue", "WEBVTT\n\n" + cue + "Hello\n"},
		{"byte order mark, CRLF, a cue identifier and cue settings", "\uFEFFWEBVTT\r\n\r\n1\r\n00:01.000 --> 00:02.500 align:start line:0\r\nHi\r\n"},
		{"hours of 1 to 3 digits", "WEBVTT\n\n1:00:00.000 --> 123:00:00.000\nlong\n"},
		{"every cue tag removed, its text kept", "WEBVTT\n\n" + cue + "<b>Bold</b> <i>it</i> <u>u</u> <c.yellow.bg>c</c> <v Roger>voice</v> <lang en>x</lang> <ruby>kan<rt>ji</rt></ruby>\n"},
		{"an unknown tag", "WEBVTT\n\n" + cue + "<script>alert(1)</script>Text\n"},
		{"a tag without its >", "WEBVTT\n\n" + cue + "before <b class=x and the rest\n"},
		{"character references decoded, then tags removed again", "WEBVTT\n\n" + cue + "Tom &amp; Jerry &lt;b&gt;x&lt;/b&gt; &#x3c;i&#62; &eacute;\n"},
		{"a lone < stays, escaped", "WEBVTT\n\n" + cue + "a < b, <3 and a > c\n"},
		{"STYLE, NOTE and REGION blocks dropped", "WEBVTT\n\nSTYLE\n::cue { color: red; background: url(https://example.org/x.png) }\n\nNOTE a note\n\nREGION\nid:r1\n\n" + cue + "x\n"},
		{"a timestamp tag stays as text", "WEBVTT\n\n" + cue + "<00:00:01.500>karaoke\n"},
		{"a URL stays as text", "WEBVTT\n\n" + cue + "see https://example.org/x\n"},
		{"direction controls removed", "WEBVTT\n\n" + cue + "\u202Eabc\u2066d\u200F\n"},
		{"white space and controls collapsed", "WEBVTT\n\n" + cue + "  a\tb\u00A0c\u0007d  \n"},
		{"a malformed timing: the block dropped", "WEBVTT\n\n00:00:01 --> 00:00:02\nno milliseconds\n\n" + cue + "kept\n"},
		{"a timing without spaces around -->: the block dropped", "WEBVTT\n\n00:00:01.000-->00:00:02.000\nx\n"},
		{"a cue left empty: dropped", "WEBVTT\n\n" + cue + "<b></b>\n\n" + cue + "kept\n"},
		{"a line shaped like a timing, inside a cue, is text", "WEBVTT\n\n" + cue + "one\n00:00:03.000 --> 00:00:04.000\n"},
		{"a cue right after the header, without an empty line", "WEBVTT\n" + cue + "x\n"},
		{"a line of spaces doesn't end a block", "WEBVTT\n\n" + cue + "a\n   \nb\n"},
		{"out-of-range timings are not checked", "WEBVTT\n\n00:99.999 --> 00:01.000\nx\n"},
		{"a line cut to 500 bytes", "WEBVTT\n\n" + cue + strings.Repeat("a", 499) + "é" + "b\n"},
		{"no cue left: valid", "WEBVTT\n\nNOTE only a note\n"},
		{"the header is a prefix", "WEBVTT - a title\n\n" + cue + "x\n"},
		{"no WEBVTT header", cue + "x\n"},
		{"empty", ""},
	}
	var out []vttCase
	for _, c := range in {
		out = append(out, vttCaseOf(c.name, []byte(c.text)))
	}
	out = append(out, vttCaseOf("invalid UTF-8 removed", []byte("WEBVTT\n\n"+cue+"ab\xffcd\xc3\n")))
	return out
}

func vttCaseOf(name string, in []byte) vttCase {
	c := vttCase{Name: name}
	if utf8.Valid(in) {
		c.Text = string(in)
	} else {
		c.Hex = hex.EncodeToString(in)
	}
	got, err := rebuildVTT(in)
	c.Valid, c.Reason = reason(err)
	c.Output = string(got)
	return c
}

func hlsVerdicts() []verdict {
	cases := []struct{ name, text string }{
		{"a master playlist", "#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-INDEPENDENT-SEGMENTS\n#EXT-X-STREAM-INF:BANDWIDTH=5000000,CODECS=\"avc1.640028,mp4a.40.2\",RESOLUTION=1920x1080\nv0.m3u8\n"},
		{"a media playlist", "#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-TARGETDURATION:6\n#EXT-X-MEDIA-SEQUENCE:0\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-MAP:URI=\"init.mp4\"\n#EXTINF:6.000000, title\nseg0.mp4\n#EXT-X-DISCONTINUITY\n#EXTINF:6.000000,\nseg-1.mp4\n#EXT-X-ENDLIST\n"},
		{"CRLF line ends", "#EXTM3U\r\n#EXTINF:6,\r\nseg0.ts\r\n#EXT-X-ENDLIST\r\n"},
		{"an unknown tag without a URI, and a comment: may pass", "#EXTM3U\n#EXT-X-FOO:BAR=1\n# a comment\n#EXTINF:6,\nseg0.ts\n"},
		{"EXT-X-MEDIA with a bare name: the URI passes", "#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID=\"a\",NAME=\"fr\",URI=\"a0.m3u8\"\n"},
		{"no #EXTM3U", "#EXTINF:6,\nseg0.ts\n"},
		{"a first line that only starts with #EXTM3U", "#EXTM3UX\n#EXTINF:6,\nseg0.ts\n"},
		{"#EXTM3U after a blank line", "\n#EXTM3U\n"},
		{"an absolute URI line", "#EXTM3U\n#EXTINF:6,\nhttps://example.org/seg0.ts\n"},
		{"a path in a URI line", "#EXTM3U\n#EXTINF:6,\nhls1/main/0.ts\n"},
		{"a dot segment as a URI line", "#EXTM3U\n#EXTINF:6,\n..\n"},
		{"a query in a URI line", "#EXTM3U\n#EXTINF:6,\nseg0.ts?x=1\n"},
		{"percent-encoding in a URI line", "#EXTM3U\n#EXTINF:6,\nseg%2e.ts\n"},
		{"a space after a URI line", "#EXTM3U\n#EXTINF:6,\nseg0.ts \n"},
		{"an unquoted URI attribute", "#EXTM3U\n#EXT-X-MAP:URI=init.mp4\n"},
		{"an empty URI attribute", "#EXTM3U\n#EXT-X-MAP:URI=\"\"\n"},
		{"a URI attribute without its closing quote", "#EXTM3U\n#EXT-X-MAP:URI=\"init.mp4\n"},
		{"an absolute URI in EXT-X-MEDIA", "#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID=\"a\",NAME=\"fr\",URI=\"https://example.org/a.m3u8\"\n"},
		{"an absolute URI in an I-frame playlist", "#EXTM3U\n#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=1,URI=\"https://example.org/i.m3u8\"\n"},
		{"uri= in lower case, in a comment", "#EXTM3U\n# uri=\"a/b\"\n"},
		{"URI= inside another attribute's quoted string", "#EXTM3U\n#EXT-X-SESSION-DATA:DATA-ID=\"x\",VALUE=\"URI=a/b\"\n"},
		{"EXT-X-DEFINE", "#EXTM3U\n#EXT-X-DEFINE:NAME=\"h\",VALUE=\"example.org\"\n#EXTINF:6,\nseg0.ts\n"},
		{"EXT-X-KEY with a bare name", "#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"key\"\n#EXTINF:6,\nseg0.ts\n"},
		{"EXT-X-KEY with METHOD=NONE", "#EXTM3U\n#EXT-X-KEY:METHOD=NONE\n#EXTINF:6,\nseg0.ts\n"},
		{"EXT-X-SESSION-KEY", "#EXTM3U\n#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES,URI=\"k\"\n"},
	}
	var out []verdict
	for _, c := range cases {
		ok, r := reason(checkPlaylist([]byte(c.text)))
		out = append(out, verdict{Name: c.name, Text: c.text, Valid: ok, Reason: r})
	}
	return out
}

// pgsSeg is one PGS segment: header (times zero) and payload.
func pgsSeg(typ byte, payload ...byte) []byte {
	b := make([]byte, 13, 13+len(payload))
	b[0], b[1], b[10] = 'P', 'G', typ
	binary.BigEndian.PutUint16(b[11:], uint16(len(payload)))
	return append(b, payload...)
}

func u16(v int) []byte { return []byte{byte(v >> 8), byte(v)} }

func cat(parts ...[]byte) []byte {
	var b []byte
	for _, p := range parts {
		b = append(b, p...)
	}
	return b
}

// pcs is a presentation of a w by h screen with no composition object.
func pcs(w, h int) []byte {
	return pgsSeg(0x16, cat(u16(w), u16(h), []byte{0x10, 0, 0, 0x80, 0, 0, 0})...)
}

// ods is an object segment: id 0, version 0, flags; first fragments carry
// a length (not checked), the size and the data.
func ods(flags byte, w, h int, data ...byte) []byte {
	if flags&0x80 == 0 {
		return pgsSeg(0x15, cat(u16(0), []byte{0, flags}, data)...)
	}
	return pgsSeg(0x15, cat(u16(0), []byte{0, flags, 0, 0, byte(len(data) + 4)}, u16(w), u16(h), data)...)
}

func pgsVerdicts() []verdict {
	end := pgsSeg(0x80)
	wds := pgsSeg(0x17, cat([]byte{1, 0}, u16(0), u16(0), u16(2), u16(2))...)
	pds := pgsSeg(0x14, 0, 0, 1, 235, 128, 128, 255)
	// 2 by 2: two pixels, end of line, twice.
	square := []byte{1, 1, 0, 0, 1, 1, 0, 0}
	cases := []struct {
		name string
		b    []byte
	}{
		{"a display set: presentation, window, palette, object, end", cat(pcs(1920, 1080), wds, pds, ods(0xC0, 2, 2, square...), end)},
		{"an object in two fragments", cat(pcs(1920, 1080), ods(0x80, 2, 2, 1, 1, 0, 0), ods(0x40, 0, 0, 1, 1, 0, 0), end)},
		{"runs: 2 pixels of color 3, then a 14-bit run of 300 of color 0", cat(pcs(1920, 1080), ods(0xC0, 302, 1, 0, 0x82, 3, 0, 0x41, 0x2C, 0, 0), end)},
		{"a presentation with one cropped object", pgsSeg(0x16, cat(u16(1920), u16(1080), []byte{0x10, 0, 0, 0x80, 0, 0, 1}, []byte{0, 0, 0, 0x80, 0, 0, 0, 0}, make([]byte, 8))...)},
		{"an object left open at the end", cat(pcs(1920, 1080), ods(0x80, 2, 2, 1, 1), end)},
		{"empty", nil},
		{"another magic", append([]byte("PX"), pgsSeg(0x80)[2:]...)},
		{"a header cut short", pgsSeg(0x80)[:12]},
		{"a payload past the end", pgsSeg(0x14, 0, 0, 1, 2, 3, 4, 5)[:15]},
		{"an unknown segment type", pgsSeg(0x18)},
		{"a screen 0 wide", pcs(0, 1080)},
		{"a screen 4,097 high", pcs(1920, 4097)},
		{"a presentation of 10 bytes", pgsSeg(0x16, cat(u16(1920), u16(1080), make([]byte, 6))...)},
		{"a presentation whose object doesn't fit", pgsSeg(0x16, cat(u16(1920), u16(1080), []byte{0x10, 0, 0, 0x80, 0, 0, 1}, make([]byte, 4))...)},
		{"a cropped object without its crop", pgsSeg(0x16, cat(u16(1920), u16(1080), []byte{0x10, 0, 0, 0x80, 0, 0, 1}, []byte{0, 0, 0, 0x80, 0, 0, 0, 0})...)},
		{"a window segment of the wrong size", pgsSeg(0x17, 1, 0, 0, 0)},
		{"a palette segment of 3 bytes", pgsSeg(0x14, 0, 0, 1)},
		{"an end segment that isn't empty", pgsSeg(0x80, 0)},
		{"an object 0 wide", ods(0xC0, 0, 2, square...)},
		{"an object 4,097 high", ods(0xC0, 2, 4097, square...)},
		{"a first fragment of 10 bytes", pgsSeg(0x15, 0, 0, 0, 0xC0, 0, 0, 4, 0, 2, 0)},
		{"a fragment of no open object", ods(0x40, 0, 0, square...)},
		{"a line wider than the object", ods(0xC0, 2, 2, 1, 1, 1, 0, 0)},
		{"more lines than the object's height", ods(0xC0, 2, 2, 1, 0, 0, 1, 0, 0, 1, 0, 0)},
		{"a run cut short", ods(0xC0, 2, 2, 1, 0)},
		{"a 14-bit run cut short", ods(0xC0, 2, 2, 0, 0x41)},
		{"a run longer than the line", ods(0xC0, 2, 2, 0, 3)},
	}
	var out []verdict
	for _, c := range cases {
		ok, r := reason(checkPGS(c.b))
		out = append(out, verdict{Name: c.name, Hex: hex.EncodeToString(c.b), Valid: ok, Reason: r})
	}
	return out
}

func genV1Media() []byte {
	return encode(v1MediaFile{
		About: []string{
			"What a server does with media it serves or relays (spec/v1/media.md section 3). Generated by tools/vectors from the specification's rules; Overfin's own checks give the same verdicts.",
			"webvtt: a part (text, or hex when it isn't UTF-8), whether it is refused, and the rebuilt part (output) when it isn't (section 3.2). The size and cue-count limits are not exercised here.",
			"hls: playlists as the viewer's server checks them (section 3.1). valid means the checks pass; tags outside the subset may still be dropped before serving.",
			"pgs: PGS parts, in hex, as section 3.3 checks them; times are zero.",
		},
		WebVTT: vttCases(),
		HLS:    hlsVerdicts(),
		PGS:    pgsVerdicts(),
	})
}

// destinationVerdicts are IP addresses a server connects to for a peer by
// default (valid) or refuses (spec/v1/core.md section 3.3).
func destinationVerdicts() []verdict {
	var out []verdict
	for _, a := range []string{"192.0.2.10", "198.51.100.7", "203.0.113.200", "2001:db8::1", "10.1.2.3", "172.16.0.1",
		"192.168.1.5", "100.64.0.1", "fd00::5", "::ffff:192.0.2.10",
		"127.0.0.1", "127.1.2.3", "::1", "::ffff:127.0.0.1", "169.254.169.254", "::ffff:169.254.169.254", "fe80::1",
		"0.0.0.0", "0.1.2.3", "::", "224.0.0.1", "239.255.255.250", "ff02::1", "240.0.0.1", "255.255.255.255", "fe80::1%eth0",
		// NAT64 (64:ff9b::/96) and 6to4 (2002::/16), judged as the IPv4 address they carry.
		"64:ff9b::c000:20a", "64:ff9b::a01:203", "64:ff9b::a9fe:a9fe", "64:ff9b::7f00:1", "64:ff9b::e000:1",
		"2002:c000:20a::1", "2002:a9fe:a9fe::1", "2002:7f00:1::", "2002::1"} {
		ok, r := reason(checkDestination(a))
		out = append(out, verdict{Text: a, Valid: ok, Reason: r})
	}
	return out
}
