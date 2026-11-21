package main

// The groups part (spec/v0/groups.md): events, the state they give, a
// code for a group, and a mail. The state is computed here by the rules of
// groups section 3, written from the specification alone.

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/hkdf"
	"crypto/hpke"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"sort"
	"time"
	"unicode/utf8"
)

// The members of the examples: A the owner (key a), B an admin (key b),
// C a member, N a newcomer, D a server banned later.
var (
	keyGC = newKey(sha([]byte("msfp-spec group member c")))
	keyGN = newKey(sha([]byte("msfp-spec group member n")))
	keyGD = newKey(sha([]byte("msfp-spec group member d")))
	// X25519 keys of the profiles, for the mail.
	xC = mustX25519(sha([]byte("msfp-spec x25519 c")))
	xN = mustX25519(sha([]byte("msfp-spec x25519 n")))
	// The ephemeral key of the example mail (RFC 9180 skE), fixed so that
	// the file is the same at every run.
	xEph = mustX25519(sha([]byte("msfp-spec x25519 ephemeral")))
)

const groupEventLabel = "msfp-group-event-1\n"
const groupMailLabel = "msfp-group-mail-1\n"
const groupDate = 1800086400

func mustX25519(seed []byte) *ecdh.PrivateKey {
	k, err := ecdh.X25519().NewPrivateKey(seed)
	if err != nil {
		panic(err)
	}
	return k
}

// ---- events ----------------------------------------------------------------

type gEvent struct {
	Name      string          `json:"name"`
	Payload   string          `json:"payload"`
	Event     string          `json:"event"`
	Signature string          `json:"signature"`
	ID        string          `json:"id"`
	Valid     bool            `json:"valid"`
	Reason    string          `json:"reason,omitempty"`
	parsed    map[string]any  `json:"-"`
	raw       json.RawMessage `json:"-"`
}

// signEvent makes an event: payload bytes (map keys sorted by Go's
// encoder), its envelope, its signature and ID.
func signEvent(name string, k key, p map[string]any) gEvent {
	b, err := json.Marshal(p)
	if err != nil {
		panic(err)
	}
	return gEvent{Name: name, Payload: string(b), Event: b64.EncodeToString(b),
		Signature: k.sign(groupEventLabel + string(b)), ID: b64.EncodeToString(sha(b))}
}

// gState is a copy's state (groups section 3.5).
type gState struct {
	ID       string            `json:"id"`
	Name     string            `json:"name"`
	Settings map[string]int64  `json:"settings"`
	Owner    string            `json:"owner"`
	Admins   []string          `json:"admins"`
	Members  []string          `json:"members"`
	Banned   []string          `json:"banned"`
	Heir     string            `json:"heir,omitempty"`
	Excluded []string          `json:"excluded"`
	Keys     map[string]string `json:"keys"` // member ID -> current key

	ownerSeq  int64
	lastSeq   map[string]int64            // member -> last kept seq
	payloads  map[string]map[int64]string // member -> seq -> payload, for equivocation
	adminLog  []adminChange
	bans      map[string]string // banned event ID -> target
	joinedAt  map[string]int64
	capCount  map[string]int   // inviter + day -> count
	removedAt map[string]int64 // admin -> lastSeq that counts
}

type adminChange struct {
	ownerSeq int64
	target   string
	on       bool
}

func newState() *gState {
	return &gState{Settings: map[string]int64{"waitDays": 3, "capPerDay": 5}, Keys: map[string]string{},
		lastSeq: map[string]int64{}, payloads: map[string]map[int64]string{}, bans: map[string]string{},
		joinedAt: map[string]int64{}, capCount: map[string]int{}, removedAt: map[string]int64{},
		Admins: []string{}, Members: []string{}, Banned: []string{}, Excluded: []string{}}
}

func (s *gState) adminAsOf(m string, k int64) bool {
	on := false
	for _, c := range s.adminLog {
		if c.target == m && c.ownerSeq <= k {
			on = c.on
		}
	}
	return on
}

func (s *gState) isMember(m string) bool { return slices.Contains(s.Members, m) }

func num64(p map[string]any, k string) (int64, bool) {
	f, ok := p[k].(float64)
	if !ok || f != float64(int64(f)) {
		return 0, false
	}
	return int64(f), true
}

func strOf(p map[string]any, k string) string { s, _ := p[k].(string); return s }

// apply keeps an event, or says why not (groups sections 3.2 to 3.5). now
// is the copy's clock.
func (s *gState) apply(e gEvent, now int64) error {
	b, err := b64.DecodeString(e.Event)
	if err != nil || len(b) > 4096 || checkIJSON(b) != nil {
		return errors.New("not a payload of at most 4,096 bytes of I-JSON")
	}
	var p map[string]any
	if json.Unmarshal(b, &p) != nil {
		return errors.New("not a JSON object")
	}
	typ, signer, member := strOf(p, "type"), strOf(p, "signer"), strOf(p, "member")
	seq, ok := num64(p, "seq")
	date, okd := num64(p, "date")
	if typ == "" || signer == "" || member == "" || !ok || seq < 1 || !okd {
		return errors.New("a common member is missing")
	}
	sigKey, err := b64.DecodeString(signer)
	if err != nil || checkKey(sigKey) != nil {
		return errors.New("signer isn't a valid key")
	}
	sig, err := checkB64(e.Signature, 64)
	if err != nil || verifyStrict(sigKey, []byte(groupEventLabel+string(b)), sig) != nil {
		return errors.New("the signature doesn't verify under signer")
	}
	if date > now+300 {
		return errors.New("dated more than 5 minutes in the future")
	}
	if typ == "founded" {
		if s.ID != "" {
			return errors.New("a second founded event")
		}
		if seq != 1 || member != signer {
			return errors.New("founded: seq 1, signed by the founder's own key")
		}
		s.ID, s.Owner, s.ownerSeq = b64.EncodeToString(sha(b)), member, 1
		s.Name = cleanName(strOf(p, "name"), 80)
		s.applySettings(p)
		s.Members = append(s.Members, member)
		s.Keys[member] = signer
		s.lastSeq[member] = 1
		s.payloads[member] = map[int64]string{1: string(b)}
		return nil
	}
	if strOf(p, "group") != s.ID {
		return errors.New("another group's event")
	}
	if slices.Contains(s.Excluded, member) {
		return errors.New("its signer was excluded for equivocation")
	}
	if prev, ok := s.payloads[member][seq]; ok {
		if prev == string(b) {
			return errors.New("already kept")
		}
		s.Excluded = append(s.Excluded, member)
		s.Members = slices.DeleteFunc(s.Members, func(x string) bool { return x == member })
		s.Admins = slices.DeleteFunc(s.Admins, func(x string) bool { return x == member })
		return errors.New("equivocation: another event with this seq: the signer is excluded")
	}
	if !s.isMember(member) {
		return errors.New("its signer isn't a member")
	}
	if s.Keys[member] != signer {
		return errors.New("signer isn't the member's current key")
	}
	if seq != s.lastSeq[member]+1 {
		return errors.New("seq doesn't follow the member's last kept event")
	}
	if r, ok := s.removedAt[member]; ok && seq > r && typ != "left" && typ != "profile" {
		return errors.New("signed after the removal of its signer's role")
	}
	owner := member == s.Owner
	var oSeq int64
	if owner && typ != "profile" && typ != "rotated" && typ != "revoked" {
		o, ok := num64(p, "ownerSeq")
		if !ok || o != s.ownerSeq+1 {
			return errors.New("an owner event whose ownerSeq doesn't follow the last one")
		}
		oSeq = o
	}
	asOf, hasAsOf := num64(p, "asOf")
	admin := !owner && hasAsOf && asOf <= s.ownerSeq && s.adminAsOf(member, asOf)
	target := strOf(p, "target")
	switch typ {
	case "profile":
	case "joined":
		if !owner && !admin {
			return errors.New("joined by a member without the right to invite")
		}
		nm := strOf(p, "newMember")
		if slices.Contains(s.Banned, nm) {
			return errors.New("the newcomer is banned")
		}
		if s.isMember(nm) {
			return errors.New("the newcomer is a member already")
		}
		day := fmt.Sprintf("%s %s", member, time.Unix(date, 0).UTC().Format("2006-01-02"))
		if int64(s.capCount[day]) >= s.Settings["capPerDay"] {
			return errors.New("over the inviter's daily cap")
		}
		s.capCount[day]++
		s.Members = append(s.Members, nm)
		s.Keys[nm] = nm
		s.joinedAt[nm] = date
	case "admin":
		if !owner {
			return errors.New("admin events are the owner's")
		}
		if !s.isMember(target) {
			return errors.New("the target isn't a member")
		}
		on, _ := p["on"].(bool)
		s.adminLog = append(s.adminLog, adminChange{oSeq, target, on})
		if on {
			s.Admins = append(s.Admins, target)
			delete(s.removedAt, target)
		} else {
			ls, _ := num64(p, "lastSeq")
			s.removedAt[target] = ls
			s.Admins = slices.DeleteFunc(s.Admins, func(x string) bool { return x == target })
		}
	case "heir":
		if !owner {
			return errors.New("heir events are the owner's")
		}
		s.Heir = target
	case "owner":
		if !owner {
			return errors.New("owner events are the owner's")
		}
		if !s.isMember(target) {
			return errors.New("the target isn't a member")
		}
		s.Owner = target
	case "settings":
		if !owner {
			return errors.New("settings are the owner's")
		}
		s.Name = cleanName(strOf(p, "name"), 80)
		s.applySettings(p)
	case "banned":
		if !owner && !admin {
			return errors.New("banned by a member without the right to ban")
		}
		if target == s.Owner {
			return errors.New("the owner can't be banned")
		}
		if !owner && (s.adminAsOf(target, asOf) || slices.Contains(s.Admins, target)) {
			return errors.New("an admin can't ban an admin: the owner removes its role first")
		}
		if !s.isMember(target) {
			return errors.New("the target isn't a member")
		}
		if r := strOf(p, "reason"); utf8.RuneCountInString(r) > 280 {
			return errors.New("a reason over 280 code points")
		}
		s.bans[e.ID] = target
		s.Banned = append(s.Banned, target)
		s.Members = slices.DeleteFunc(s.Members, func(x string) bool { return x == target })
		s.Admins = slices.DeleteFunc(s.Admins, func(x string) bool { return x == target })
	case "unbanned":
		if !owner {
			return errors.New("unbanned is the owner's")
		}
		t, ok := s.bans[strOf(p, "ban")]
		if !ok {
			return errors.New("no such ban")
		}
		s.Banned = slices.DeleteFunc(s.Banned, func(x string) bool { return x == t })
	case "left":
		if owner {
			return errors.New("the owner gives the group away before leaving")
		}
		s.Members = slices.DeleteFunc(s.Members, func(x string) bool { return x == member })
		s.Admins = slices.DeleteFunc(s.Admins, func(x string) bool { return x == member })
	default:
		return errors.New("a type these vectors don't use")
	}
	if oSeq > 0 {
		s.ownerSeq = oSeq
	}
	s.lastSeq[member] = seq
	if s.payloads[member] == nil {
		s.payloads[member] = map[int64]string{}
	}
	s.payloads[member][seq] = string(b)
	return nil
}

func (s *gState) applySettings(p map[string]any) {
	st, _ := p["settings"].(map[string]any)
	if v, ok := num64(st, "waitDays"); ok && v >= 0 && v <= 30 {
		s.Settings["waitDays"] = v
	}
	if v, ok := num64(st, "capPerDay"); ok && v >= 1 && v <= 100 {
		s.Settings["capPerDay"] = v
	}
}

func (s *gState) out() gState {
	c := *s
	c.Admins, c.Members, c.Banned, c.Excluded = sorted(s.Admins), sorted(s.Members), sorted(s.Banned), sorted(s.Excluded)
	return c
}

func sorted(l []string) []string {
	c := slices.Clone(l)
	sort.Strings(c)
	if c == nil {
		c = []string{}
	}
	return c
}

// groupEvents is the example list: valid events, then invalid ones, each
// judged on the state the valid ones before it built.
func groupEvents() ([]gEvent, string) {
	a, b, c, n, d := keyA.text(), keyB.text(), keyGC.text(), keyGN.text(), keyGD.text()
	founded := signEvent("A founds Family", keyA, map[string]any{"type": "founded", "signer": a, "member": a, "seq": 1,
		"date": groupDate, "ownerSeq": 1, "name": "Family", "settings": map[string]any{"waitDays": 3, "capPerDay": 5},
		"nonce": b64.EncodeToString(seq(0x10, 16))})
	g := founded.ID
	ev := func(name string, k key, member string, sq int64, extra map[string]any) gEvent {
		p := map[string]any{"group": g, "signer": k.text(), "member": member, "seq": sq, "date": groupDate + 60*sq}
		for kk, v := range extra {
			p[kk] = v
		}
		return signEvent(name, k, p)
	}
	valid := []gEvent{
		founded,
		ev("A invites B", keyA, a, 2, map[string]any{"type": "joined", "newMember": b, "name": "B", "ownerSeq": 2}),
		ev("A makes B an admin", keyA, a, 3, map[string]any{"type": "admin", "target": b, "on": true, "ownerSeq": 3}),
		ev("B's profile", keyB, b, 1, map[string]any{"type": "profile", "name": "B",
			"encryptionKey":  b64.EncodeToString(mustX25519(sha([]byte("msfp-spec x25519 b"))).PublicKey().Bytes()),
			"nextCommitment": commitment(keyB2.pub)}),
		ev("B invites C", keyB, b, 2, map[string]any{"type": "joined", "newMember": c, "name": "C", "asOf": 3}),
		ev("C's profile", keyGC, c, 1, map[string]any{"type": "profile", "name": "C",
			"encryptionKey": b64.EncodeToString(xC.PublicKey().Bytes()), "nextCommitment": commitment(keyGC.pub)}),
		ev("B invites N", keyB, b, 3, map[string]any{"type": "joined", "newMember": n, "name": "N", "asOf": 3}),
		ev("N's profile", keyGN, n, 1, map[string]any{"type": "profile", "name": "N",
			"encryptionKey": b64.EncodeToString(xN.PublicKey().Bytes()), "nextCommitment": commitment(keyGN.pub)}),
		ev("B invites D", keyB, b, 4, map[string]any{"type": "joined", "newMember": d, "name": "D", "asOf": 3}),
		ev("B bans D, with a reason", keyB, b, 5, map[string]any{"type": "banned", "target": d, "lastSeq": 0,
			"reason": "Not who we thought", "asOf": 3}),
		ev("A names C its heir", keyA, a, 4, map[string]any{"type": "heir", "target": c, "ownerSeq": 4}),
		ev("A sets a 7-day wait", keyA, a, 5, map[string]any{"type": "settings", "name": "Family",
			"settings": map[string]any{"waitDays": 7, "capPerDay": 5}, "ownerSeq": 5}),
	}
	bad := []gEvent{
		ev("C, a member, invites", keyGC, c, 2, map[string]any{"type": "joined", "newMember": keyB2.text(), "name": "X", "asOf": 5}),
		ev("B, an admin, bans the owner", keyB, b, 6, map[string]any{"type": "banned", "target": a, "lastSeq": 5, "asOf": 5}),
		ev("B names an admin", keyB, b, 6, map[string]any{"type": "admin", "target": c, "on": true, "asOf": 5}),
		ev("an owner event that skips an ownerSeq", keyA, a, 6, map[string]any{"type": "heir", "target": b, "ownerSeq": 7}),
		ev("a seq that skips one", keyGN, n, 3, map[string]any{"type": "profile", "name": "N"}),
		ev("the owner leaves without giving the group away", keyA, a, 6, map[string]any{"type": "left", "ownerSeq": 6}),
		func() gEvent {
			e := ev("signed by another key than the member's", keyGN, c, 2, map[string]any{"type": "profile", "name": "C"})
			return e
		}(),
		func() gEvent {
			e := ev("a broken signature", keyGC, c, 2, map[string]any{"type": "profile", "name": "C2"})
			s, _ := b64.DecodeString(e.Signature)
			s[0] ^= 1
			e.Signature = b64.EncodeToString(s)
			return e
		}(),
		func() gEvent {
			e := signEvent("another group's event", keyGC, map[string]any{"group": b64.EncodeToString(sha([]byte("x"))),
				"type": "profile", "signer": c, "member": c, "seq": 2, "date": groupDate + 120, "name": "C"})
			return e
		}(),
		ev("dated an hour ahead of the copy's clock", keyGC, c, 2, map[string]any{"type": "profile", "name": "C", "date": groupDate + 4000}),
		ev("N again, with another seq 1: equivocation", keyGN, n, 1, map[string]any{"type": "profile", "name": "N, again"}),
	}
	return append(valid, bad...), g
}

// groupNow is the copy's clock when it judges the examples.
const groupNow = groupDate + 600

func judgeGroupEvents(events []gEvent) ([]gEvent, gState) {
	s := newState()
	var out []gEvent
	var final gState
	for _, e := range events {
		// Each invalid case is judged on the valid list alone: a copy
		// keeps the valid ones in order, then meets the case.
		err := s.apply(e, groupNow)
		e.Valid, e.Reason = err == nil, ""
		if err != nil {
			e.Reason = err.Error()
		}
		out = append(out, e)
	}
	final = s.out()
	return out, final
}

// ---- the mail (groups section 5), sealed as RFC 9180 says ------------------

func labeledExtract(suite []byte, salt []byte, label string, ikm []byte) []byte {
	in := append(append(append([]byte("HPKE-v1"), suite...), label...), ikm...)
	prk, err := hkdf.Extract(sha256.New, in, salt)
	if err != nil {
		panic(err)
	}
	return prk
}

func labeledExpand(suite []byte, prk []byte, label string, info []byte, n int) []byte {
	l := binary.BigEndian.AppendUint16(nil, uint16(n))
	in := append(append(append(append(l, "HPKE-v1"...), suite...), label...), info...)
	out, err := hkdf.Expand(sha256.New, prk, string(in), n)
	if err != nil {
		panic(err)
	}
	return out
}

// seal is HPKE's base mode, DHKEM(X25519, HKDF-SHA256), HKDF-SHA256,
// AES-128-GCM, one message, with the ephemeral key given: it returns enc
// and the ciphertext.
func seal(eph *ecdh.PrivateKey, pkR *ecdh.PublicKey, info, aad, pt []byte) ([]byte, []byte) {
	dh, err := eph.ECDH(pkR)
	if err != nil {
		panic(err)
	}
	enc := eph.PublicKey().Bytes()
	kemSuite := binary.BigEndian.AppendUint16([]byte("KEM"), 0x0020)
	kemContext := append(slices.Clone(enc), pkR.Bytes()...)
	shared := labeledExpand(kemSuite, labeledExtract(kemSuite, nil, "eae_prk", dh), "shared_secret", kemContext, 32)
	suite := []byte("HPKE")
	for _, id := range []uint16{0x0020, 0x0001, 0x0001} {
		suite = binary.BigEndian.AppendUint16(suite, id)
	}
	ctx := append([]byte{0}, labeledExtract(suite, nil, "psk_id_hash", nil)...)
	ctx = append(ctx, labeledExtract(suite, nil, "info_hash", info)...)
	secret := labeledExtract(suite, shared, "secret", nil)
	k := labeledExpand(suite, secret, "key", ctx, 16)
	nonce := labeledExpand(suite, secret, "base_nonce", ctx, 12)
	blk, _ := aes.NewCipher(k)
	gcm, _ := cipher.NewGCM(blk)
	return enc, gcm.Seal(nil, nonce, pt, aad)
}

// openMail opens a sealed mail with Go's own crypto/hpke: the cross-check of
// seal above.
func openMail(priv *ecdh.PrivateKey, sealed, info, aad []byte) ([]byte, error) {
	if len(sealed) < 32 {
		return nil, errors.New("shorter than an encapsulated key")
	}
	kem := hpke.DHKEM(ecdh.X25519())
	sk, err := kem.NewPrivateKey(priv.Bytes())
	if err != nil {
		return nil, err
	}
	r, err := hpke.NewRecipient(sealed[:32], sk, hpke.HKDFSHA256(), hpke.AES128GCM(), info)
	if err != nil {
		return nil, err
	}
	return r.Open(aad, sealed[32:])
}

type gMail struct {
	Name            string `json:"name"`
	Payload         string `json:"payload"`
	Mail            string `json:"mail"`
	Signature       string `json:"signature"`
	RecipientX25519 string `json:"recipientX25519Private"`
	Info            string `json:"info"`
	AAD             string `json:"aad"`
	Opened          string `json:"opened"`
}

func mailInfo(group, id []byte) []byte {
	return append(append([]byte("msfp-group-mail-1"), group...), id...)
}

func groupMail(group string) gMail {
	g, _ := b64.DecodeString(group)
	id := seq(0x30, 16)
	from, to := keyGN.pub, keyGC.pub
	opened := `{"address":"https://n.example.org","inbound":true,"name":"N","nextCommitment":"` + commitment(keyGN.pub) + `"}`
	info := mailInfo(g, id)
	aad := append(slices.Clone(from), to...)
	enc, ct := seal(xEph, xC.PublicKey(), info, aad, []byte(opened))
	p := map[string]any{"group": group, "id": b64.EncodeToString(id), "kind": "request", "from": keyGN.text(),
		"to": keyGC.text(), "expires": groupDate + 30*86400, "sealed": b64.EncodeToString(append(enc, ct...))}
	b, _ := json.Marshal(p)
	return gMail{Name: "N's request to C", Payload: string(b), Mail: b64.EncodeToString(b),
		Signature: keyGN.sign(groupMailLabel + string(b)), RecipientX25519: fmt.Sprintf("%x", xC.Bytes()),
		Info: fmt.Sprintf("%x", info), AAD: fmt.Sprintf("%x", aad), Opened: opened}
}

// ---- the file ----------------------------------------------------------------

type groupsFile struct {
	About  []string          `json:"about"`
	Keys   map[string]string `json:"keys"`
	Now    int64             `json:"now"`
	Events []gEvent          `json:"events"`
	State  gState            `json:"state"`
	Code   v0Code            `json:"code"`
	Group  string            `json:"group"`
	Name   string            `json:"groupName"`
	Mail   gMail             `json:"mail"`
}

func genV0Groups() []byte {
	events, g := groupEvents()
	judged, state := judgeGroupEvents(events)
	secret := mustHex(secretS)
	gid, _ := b64.DecodeString(g)
	return encode(groupsFile{
		About: []string{
			"The groups part (spec/v0/groups.md). Generated by tools/vectors; no implementation has produced them yet.",
			"keys: the members' Ed25519 keys by name (a and b are keys.json's; seeds are SHA-256 of an ASCII text, see tools/vectors/groups.go). Member IDs are these keys, base64url.",
			"events: in order, as a copy meets them, with now as its clock. The valid ones build the group; each invalid one is judged on the state the valid ones before it built, and changes nothing, except the last: an equivocation, which excludes its signer. payload is the event's bytes as text; event is their base64url; id is base64url of SHA-256 of the payload.",
			"state: what a copy computes once it kept the valid events and met the invalid ones (groups section 3.5): member IDs, sorted.",
			"code: a pairing code for the group (core section 5.1, groups section 2), made by B, with the group's ID and name.",
			"mail: N's request to C (groups section 5), sealed with HPKE base mode, DHKEM(X25519, HKDF-SHA256), HKDF-SHA256, AES-128-GCM, to C's encryption key; recipientX25519Private opens it. info and aad are hex. The generator seals with a fixed ephemeral key, and opens with Go's crypto/hpke.",
		},
		Keys: map[string]string{"a": keyA.text(), "b": keyB.text(), "c": keyGC.text(), "n": keyGN.text(), "d": keyGD.text()},
		Now:  groupNow, Events: judged, State: state, Group: g, Name: "Family",
		Code: v0Code{"b", "https://b.example.org", secretS, expires,
			makeGroupCode(core0.prefix, keyB.pub, secret, expires, gid, "Family", "https://b.example.org"), b64.EncodeToString(sha(secret))},
		Mail: groupMail(g),
	})
}
