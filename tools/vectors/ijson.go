package main

// An I-JSON (RFC 7493) checker for MSFP bodies: UTF-8 without a byte
// order mark, no surrogates or noncharacters (escaped or not), no object
// with the same member name twice. It checks the JSON grammar of
// RFC 8259 along the way. It doesn't check what members mean.

import (
	"errors"
	"fmt"
	"unicode/utf8"
)

func checkIJSON(b []byte) error {
	if len(b) >= 3 && b[0] == 0xef && b[1] == 0xbb && b[2] == 0xbf {
		return errors.New("a byte order mark")
	}
	if !utf8.Valid(b) {
		return errors.New("invalid UTF-8")
	}
	p := &jparser{b: b}
	p.ws()
	if err := p.value(0); err != nil {
		return err
	}
	p.ws()
	if p.i != len(p.b) {
		return errors.New("text after the value")
	}
	return nil
}

type jparser struct {
	b []byte
	i int
}

func (p *jparser) ws() {
	for p.i < len(p.b) {
		switch p.b[p.i] {
		case ' ', '\t', '\n', '\r':
			p.i++
		default:
			return
		}
	}
}

func (p *jparser) peek() byte {
	if p.i < len(p.b) {
		return p.b[p.i]
	}
	return 0
}

func (p *jparser) value(depth int) error {
	if depth > 64 {
		return errors.New("nested too deep")
	}
	switch c := p.peek(); {
	case c == '{':
		return p.object(depth)
	case c == '[':
		return p.array(depth)
	case c == '"':
		_, err := p.str()
		return err
	case c == '-' || c >= '0' && c <= '9':
		return p.number()
	default:
		for _, lit := range []string{"true", "false", "null"} {
			if len(p.b)-p.i >= len(lit) && string(p.b[p.i:p.i+len(lit)]) == lit {
				p.i += len(lit)
				return nil
			}
		}
		return fmt.Errorf("unexpected byte at %d", p.i)
	}
}

func (p *jparser) object(depth int) error {
	p.i++
	p.ws()
	seen := map[string]bool{}
	if p.peek() == '}' {
		p.i++
		return nil
	}
	for {
		p.ws()
		if p.peek() != '"' {
			return errors.New("a member name that isn't a string")
		}
		name, err := p.str()
		if err != nil {
			return err
		}
		if seen[name] {
			return fmt.Errorf("member %q twice", name)
		}
		seen[name] = true
		p.ws()
		if p.peek() != ':' {
			return errors.New("no colon after a member name")
		}
		p.i++
		p.ws()
		if err := p.value(depth + 1); err != nil {
			return err
		}
		p.ws()
		switch p.peek() {
		case ',':
			p.i++
		case '}':
			p.i++
			return nil
		default:
			return errors.New("an unterminated object")
		}
	}
}

func (p *jparser) array(depth int) error {
	p.i++
	p.ws()
	if p.peek() == ']' {
		p.i++
		return nil
	}
	for {
		p.ws()
		if err := p.value(depth + 1); err != nil {
			return err
		}
		p.ws()
		switch p.peek() {
		case ',':
			p.i++
		case ']':
			p.i++
			return nil
		default:
			return errors.New("an unterminated array")
		}
	}
}

func noncharacter(r rune) bool {
	return r >= 0xfdd0 && r <= 0xfdef || r&0xfffe == 0xfffe
}

func hex4(b []byte) (rune, bool) {
	if len(b) < 4 {
		return 0, false
	}
	var r rune
	for _, c := range b[:4] {
		r <<= 4
		switch {
		case c >= '0' && c <= '9':
			r |= rune(c - '0')
		case c >= 'a' && c <= 'f':
			r |= rune(c-'a') + 10
		case c >= 'A' && c <= 'F':
			r |= rune(c-'A') + 10
		default:
			return 0, false
		}
	}
	return r, true
}

// str reads a string and returns its decoded value.
func (p *jparser) str() (string, error) {
	p.i++
	var out []rune
	for {
		if p.i >= len(p.b) {
			return "", errors.New("an unterminated string")
		}
		c := p.b[p.i]
		switch {
		case c == '"':
			p.i++
			return string(out), nil
		case c < 0x20:
			return "", errors.New("a control character in a string")
		case c == '\\':
			if p.i+1 >= len(p.b) {
				return "", errors.New("an unterminated escape")
			}
			e := p.b[p.i+1]
			p.i += 2
			switch e {
			case '"', '\\', '/':
				out = append(out, rune(e))
			case 'b':
				out = append(out, '\b')
			case 'f':
				out = append(out, '\f')
			case 'n':
				out = append(out, '\n')
			case 'r':
				out = append(out, '\r')
			case 't':
				out = append(out, '\t')
			case 'u':
				r, ok := hex4(p.b[p.i:])
				if !ok {
					return "", errors.New("a bad \\u escape")
				}
				p.i += 4
				if r >= 0xdc00 && r <= 0xdfff {
					return "", errors.New("a lone surrogate")
				}
				if r >= 0xd800 && r <= 0xdbff {
					if p.i+6 > len(p.b) || p.b[p.i] != '\\' || p.b[p.i+1] != 'u' {
						return "", errors.New("a lone surrogate")
					}
					lo, ok := hex4(p.b[p.i+2:])
					if !ok || lo < 0xdc00 || lo > 0xdfff {
						return "", errors.New("a lone surrogate")
					}
					p.i += 6
					r = 0x10000 + (r-0xd800)<<10 + (lo - 0xdc00)
				}
				if noncharacter(r) {
					return "", errors.New("a noncharacter")
				}
				out = append(out, r)
			default:
				return "", errors.New("a bad escape")
			}
		default:
			r, n := utf8.DecodeRune(p.b[p.i:])
			if noncharacter(r) {
				return "", errors.New("a noncharacter")
			}
			out = append(out, r)
			p.i += n
		}
	}
}

func (p *jparser) number() error {
	start := p.i
	if p.peek() == '-' {
		p.i++
	}
	switch c := p.peek(); {
	case c == '0':
		p.i++
	case c >= '1' && c <= '9':
		for c := p.peek(); c >= '0' && c <= '9'; c = p.peek() {
			p.i++
		}
	default:
		return fmt.Errorf("a bad number at %d", start)
	}
	if p.peek() == '.' {
		p.i++
		if c := p.peek(); c < '0' || c > '9' {
			return errors.New("a bad fraction")
		}
		for c := p.peek(); c >= '0' && c <= '9'; c = p.peek() {
			p.i++
		}
	}
	if c := p.peek(); c == 'e' || c == 'E' {
		p.i++
		if c := p.peek(); c == '+' || c == '-' {
			p.i++
		}
		if c := p.peek(); c < '0' || c > '9' {
			return errors.New("a bad exponent")
		}
		for c := p.peek(); c >= '0' && c <= '9'; c = p.peek() {
			p.i++
		}
	}
	return nil
}
