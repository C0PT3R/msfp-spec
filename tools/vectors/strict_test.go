package main

import (
	"crypto/ed25519"
	"encoding/json"
	"os"
	"testing"

	"filippo.io/edwards25519"
)

// The comments in v0-strict.json about what common libraries do: Go's
// crypto/ed25519 accepts the identity key's signature and refuses the
// torsion R; a cofactored check accepts the torsion R.
func TestLibraryBehaviour(t *testing.T) {
	var f struct {
		Signatures []sigVector `json:"signatures"`
	}
	b, err := os.ReadFile("../../vectors/v0-strict.json")
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(b, &f); err != nil {
		t.Fatal(err)
	}
	for _, s := range f.Signatures {
		pub, _ := b64.DecodeString(s.Public)
		sig, _ := b64.DecodeString(s.Signature)
		goOK := ed25519.Verify(pub, []byte(s.Message), sig)
		switch s.Name {
		case "identity key, R = identity, S = 0":
			if !goOK || !ed25519.Verify(pub, []byte("any other message"), sig) {
				t.Errorf("%s: Go refuses it", s.Name)
			}
		case "torsion R":
			if goOK {
				t.Errorf("%s: Go accepts it", s.Name)
			}
			if !cofactored(pub, []byte(s.Message), sig) {
				t.Errorf("%s: a cofactored check refuses it", s.Name)
			}
		}
	}
}

// cofactored is RFC 8032's cofactored equation: [8][S]B = [8]R + [8][k]A.
func cofactored(pub, msg, sig []byte) bool {
	A, err1 := new(edwards25519.Point).SetBytes(pub)
	R, err2 := new(edwards25519.Point).SetBytes(sig[:32])
	S, err3 := edwards25519.NewScalar().SetCanonicalBytes(sig[32:])
	if err1 != nil || err2 != nil || err3 != nil {
		return false
	}
	k := hramScalar(sig[:32], pub, string(msg))
	left := new(edwards25519.Point).ScalarBaseMult(S)
	right := new(edwards25519.Point).ScalarMult(k, A)
	right.Add(right, R)
	return new(edwards25519.Point).MultByCofactor(left).Equal(new(edwards25519.Point).MultByCofactor(right)) == 1
}

// IPv6 hosts aren't in the vectors (their examples would need RFC 3849
// addresses); the rules are checked here instead.
func TestIPv6Addresses(t *testing.T) {
	for addr, want := range map[string]bool{
		"https://[2001:db8::1]":          true,
		"https://[2001:db8::1]:8443":     true,
		"https://[2001:DB8::1]":          false,
		"https://[2001:db8:0:0:0:0:0:1]": false,
		"https://[2001:db8::1%25eth0]":   false,
		"https://[2001:db8::1]:443":      false,
		"https://[192.0.2.1]":            false,
		"https://[2001:db8::1":           false,
	} {
		if got := checkAddress(addr, false) == nil; got != want {
			t.Errorf("%s: valid=%v, want %v", addr, got, want)
		}
	}
}
