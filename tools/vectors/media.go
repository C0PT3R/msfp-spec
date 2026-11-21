package main

// The media rules of spec/v0/media.md section 3 (HLS playlists, WebVTT,
// PGS), and the destinations of spec/v0/core.md section 3.3. Written from
// the specification's text, to check vectors/v0/media.json and the
// destinations of vectors/v0/strict.json.

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"html"
	"net/netip"
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"
)

// --- Destinations (core section 3.3) ---

var refusedRanges = []struct {
	prefix netip.Prefix
	why    string
}{
	{netip.MustParsePrefix("127.0.0.0/8"), "loopback"},
	{netip.MustParsePrefix("::1/128"), "loopback"},
	{netip.MustParsePrefix("169.254.0.0/16"), "link-local"},
	{netip.MustParsePrefix("fe80::/10"), "link-local"},
	{netip.MustParsePrefix("0.0.0.0/8"), "unspecified or this network"},
	{netip.MustParsePrefix("::/128"), "unspecified"},
	{netip.MustParsePrefix("224.0.0.0/4"), "multicast"},
	{netip.MustParsePrefix("ff00::/8"), "multicast"},
	{netip.MustParsePrefix("240.0.0.0/4"), "reserved or broadcast"},
}

var (
	nat64     = netip.MustParsePrefix("64:ff9b::/96")
	sixToFour = netip.MustParsePrefix("2002::/16")
)

// checkDestination says whether a server connects to ip for a peer by
// default: nil when it does.
func checkDestination(s string) error {
	ip, err := netip.ParseAddr(s)
	if err != nil || ip.Zone() != "" {
		return errors.New("not an IP address")
	}
	ip = ip.Unmap() // an IPv4-mapped address is judged as IPv4
	// NAT64's well-known prefix (RFC 6052: the last 32 bits) and 6to4
	// (RFC 3056: bits 16 to 47) are judged as the IPv4 address they carry.
	if b := ip.As16(); ip.Is6() && nat64.Contains(ip) {
		ip = netip.AddrFrom4([4]byte(b[12:16]))
	} else if ip.Is6() && sixToFour.Contains(ip) {
		ip = netip.AddrFrom4([4]byte(b[2:6]))
	}
	for _, r := range refusedRanges {
		if r.prefix.Contains(ip) {
			return fmt.Errorf("refused: %s", r.why)
		}
	}
	return nil
}

// --- HLS (media section 3.1) ---

const maxPlaylist = 2 << 20
const maxPlaylistURIs = 50_000

var playlistURI = regexp.MustCompile(`(?i)URI=`)

// checkPlaylist applies the viewer's server's checks, in order.
func checkPlaylist(b []byte) error {
	if len(b) > maxPlaylist {
		return errors.New("over 2 MiB")
	}
	lines := strings.Split(string(b), "\n")
	for i, l := range lines {
		lines[i] = strings.TrimSuffix(l, "\r")
	}
	if lines[0] != "#EXTM3U" {
		return errors.New("the first line isn't #EXTM3U")
	}
	uris := 0
	for _, l := range lines[1:] {
		switch {
		case l == "":
			continue
		case !strings.HasPrefix(l, "#"):
			if err := checkMediaName(l); err != nil {
				return fmt.Errorf("a URI line: %v", err)
			}
			uris++
			continue
		}
		for _, m := range playlistURI.FindAllStringIndex(l, -1) {
			rest := l[m[1]:]
			if !strings.HasPrefix(rest, `"`) {
				return errors.New("an unquoted URI attribute")
			}
			end := strings.IndexByte(rest[1:], '"')
			if end < 0 {
				return errors.New("a URI attribute without its closing quote")
			}
			if err := checkMediaName(rest[1 : 1+end]); err != nil {
				return fmt.Errorf("a URI attribute: %v", err)
			}
			uris++
		}
		switch {
		case l == "#EXT-X-DEFINE" || strings.HasPrefix(l, "#EXT-X-DEFINE:"):
			return errors.New("EXT-X-DEFINE")
		case strings.HasPrefix(l, "#EXT-X-KEY:") || strings.HasPrefix(l, "#EXT-X-SESSION-KEY:"):
			return errors.New("EXT-X-KEY or EXT-X-SESSION-KEY")
		}
	}
	if uris > maxPlaylistURIs {
		return errors.New("over 50,000 URIs")
	}
	return nil
}

// --- WebVTT (media section 3.2) ---

const (
	maxVTT     = 5 << 20
	maxCues    = 50_000
	maxCueLine = 500
)

var timingLine = regexp.MustCompile(`^((?:[0-9]{1,3}:)?[0-9]{2}:[0-9]{2}\.[0-9]{3})[\t\f ]+-->[\t\f ]+((?:[0-9]{1,3}:)?[0-9]{2}:[0-9]{2}\.[0-9]{3})([\t\f ].*)?$`)

var escapeCue = strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;")

// rebuildVTT rebuilds a WebVTT part, or refuses it.
func rebuildVTT(in []byte) ([]byte, error) {
	if len(in) > maxVTT {
		return nil, errors.New("over 5 MiB")
	}
	text := strings.ReplaceAll(strings.ReplaceAll(string(in), "\r\n", "\n"), "\r", "\n")
	text = strings.TrimPrefix(text, "\uFEFF")
	if !strings.HasPrefix(text, "WEBVTT") {
		return nil, errors.New("doesn't start with WEBVTT")
	}
	var out bytes.Buffer
	out.WriteString("WEBVTT\n")
	cues := 0
	for _, block := range strings.Split(text, "\n\n") {
		lines := strings.Split(strings.Trim(block, "\n"), "\n")
		at := -1
		var m []string
		for i, l := range lines {
			if m = timingLine.FindStringSubmatch(strings.TrimSpace(l)); m != nil {
				at = i
				break
			}
		}
		if at < 0 {
			continue
		}
		var body []string
		for _, l := range lines[at+1:] {
			if c := cleanCueLine(l); c != "" {
				body = append(body, escapeCue.Replace(c))
			}
		}
		if len(body) == 0 {
			continue
		}
		if cues++; cues > maxCues {
			return nil, errors.New("over 50,000 cues")
		}
		out.WriteString("\n" + m[1] + " --> " + m[2] + "\n" + strings.Join(body, "\n") + "\n")
	}
	return out.Bytes(), nil
}

func directionControl(r rune) bool {
	return r == 0x061C || r == 0x200E || r == 0x200F || r >= 0x202A && r <= 0x202E || r >= 0x2066 && r <= 0x2069
}

// dropInvisible is step 1: invalid UTF-8, U+FFFD, direction controls.
func dropInvisible(s string) string {
	return strings.Map(func(r rune) rune {
		if r == utf8.RuneError || directionControl(r) {
			return -1
		}
		return r
	}, s)
}

// dropTags is step 2.
func dropTags(s string) string {
	var b strings.Builder
	in := false
	for i, r := range s {
		switch {
		case in:
			if r == '>' {
				in = false
				b.WriteByte(' ')
			}
		case r == '<':
			next, _ := utf8.DecodeRuneInString(s[i+1:])
			if unicode.IsLetter(next) || next == '/' || next == '!' || next == '?' {
				in = true
			} else {
				b.WriteRune(r)
			}
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

// cleanCueLine is steps 1 to 6; the caller escapes (step 7).
func cleanCueLine(s string) string {
	s = dropTags(dropInvisible(s))
	s = html.UnescapeString(s)
	s = dropTags(dropInvisible(s))
	var b strings.Builder
	space := false
	for _, r := range s {
		if r == utf8.RuneError || directionControl(r) {
			continue
		}
		if unicode.IsControl(r) || unicode.IsSpace(r) {
			space = true
			continue
		}
		if space && b.Len() > 0 {
			b.WriteByte(' ')
		}
		space = false
		b.WriteRune(r)
	}
	out := b.String()
	if len(out) > maxCueLine {
		cut := maxCueLine
		for cut > 0 && !utf8.RuneStart(out[cut]) {
			cut--
		}
		out = strings.TrimRight(out[:cut], " ")
	}
	return out
}

// --- PGS (media section 3.3) ---

const (
	maxPGS        = 64 << 20
	maxPGSSide    = 4096
	maxPGSObjects = 20_000
)

// checkPGS checks a PGS part whole.
func checkPGS(raw []byte) error {
	if len(raw) > maxPGS { // an empty part is valid: a stretch with no subtitles
		return errors.New("over 64 MiB")
	}
	side := func(v uint16) bool { return v >= 1 && v <= maxPGSSide }
	type object struct {
		w, h int
		data []byte
	}
	open := map[uint16]*object{}
	firsts := 0
	for pos := 0; pos < len(raw); {
		if len(raw)-pos < 13 {
			return errors.New("a segment header cut short")
		}
		if raw[pos] != 'P' || raw[pos+1] != 'G' {
			return errors.New("a segment without its PG magic")
		}
		typ := raw[pos+10]
		size := int(binary.BigEndian.Uint16(raw[pos+11:]))
		if pos+13+size > len(raw) {
			return errors.New("a payload past the end")
		}
		seg := raw[pos+13 : pos+13+size]
		pos += 13 + size
		switch typ {
		case 0x16: // presentation
			if len(seg) < 11 {
				return errors.New("a presentation under 11 bytes")
			}
			if !side(binary.BigEndian.Uint16(seg)) || !side(binary.BigEndian.Uint16(seg[2:])) {
				return errors.New("a screen size outside 1 to 4,096")
			}
			o := 11
			for range int(seg[10]) {
				if o+8 > len(seg) {
					return errors.New("composition objects past the payload")
				}
				n := 8
				if seg[o+3]&0x80 != 0 {
					n = 16
				}
				o += n
			}
			if o > len(seg) {
				return errors.New("composition objects past the payload")
			}
		case 0x17: // window
			if len(seg) < 1 || len(seg) != 1+9*int(seg[0]) {
				return errors.New("a window segment of the wrong size")
			}
		case 0x14: // palette
			if len(seg) < 2 || (len(seg)-2)%5 != 0 {
				return errors.New("a palette segment of the wrong size")
			}
		case 0x15: // object
			if len(seg) < 4 {
				return errors.New("an object segment under 4 bytes")
			}
			id, flags := binary.BigEndian.Uint16(seg), seg[3]
			if flags&0x80 != 0 {
				if len(seg) < 11 {
					return errors.New("a first fragment under 11 bytes")
				}
				w, h := binary.BigEndian.Uint16(seg[7:]), binary.BigEndian.Uint16(seg[9:])
				if !side(w) || !side(h) {
					return errors.New("an object size outside 1 to 4,096")
				}
				if firsts++; firsts > maxPGSObjects {
					return errors.New("over 20,000 objects")
				}
				open[id] = &object{w: int(w), h: int(h), data: append([]byte(nil), seg[11:]...)}
			} else {
				o := open[id]
				if o == nil {
					return errors.New("a fragment of no open object")
				}
				o.data = append(o.data, seg[4:]...)
			}
			if flags&0x40 != 0 {
				o := open[id]
				if err := runsFit(o.data, o.w, o.h); err != nil {
					return err
				}
				delete(open, id)
			}
		case 0x80: // end
			if len(seg) != 0 {
				return errors.New("an end segment that isn't empty")
			}
		default:
			return fmt.Errorf("an unknown segment type 0x%02x", typ)
		}
	}
	return nil
}

// runsFit says whether run-length data fits w by h pixels.
func runsFit(d []byte, w, h int) error {
	short := errors.New("a run cut short")
	x, y := 0, 0
	for i := 0; i < len(d); {
		b := d[i]
		i++
		if b != 0 {
			x++
		} else {
			if i >= len(d) {
				return short
			}
			f := d[i]
			i++
			if f == 0 {
				x, y = 0, y+1
				if y > h {
					return errors.New("more lines than the object's height")
				}
				continue
			}
			n := int(f & 0x3f)
			if f&0x40 != 0 {
				if i >= len(d) {
					return short
				}
				n = n<<8 | int(d[i])
				i++
			}
			if f&0x80 != 0 {
				if i >= len(d) {
					return short
				}
				i++
			}
			x += n
		}
		if x > w {
			return errors.New("a line wider than the object")
		}
	}
	return nil
}
