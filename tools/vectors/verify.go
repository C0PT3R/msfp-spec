package main

// verifyAll reads the vector files back and re-checks every value from
// the files' own fields: keys from seeds, codes from their parts,
// messages rebuilt from their fields, every signature under the strict
// rules, every verdict against this program's checks.

import (
	"crypto/ed25519"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strconv"
)

type obj = map[string]any

func str(o obj, k string) string { s, _ := o[k].(string); return s }
func num(o obj, k string) int64  { f, _ := o[k].(float64); return int64(f) }

func verifyAll(read func(string) []byte) []error {
	var errs []error
	bad := func(format string, a ...any) { errs = append(errs, fmt.Errorf(format, a...)) }
	load := func(rel string) obj {
		var o obj
		b := read(rel)
		if err := checkIJSON(b); err != nil {
			bad("%s: %v", rel, err)
		}
		if err := json.Unmarshal(b, &o); err != nil {
			bad("%s: %v", rel, err)
		}
		return o
	}

	// Keys: public key and fingerprint from the seed, and the key valid.
	pubs := map[string][]byte{}
	checkKeys := func(file string, keys obj, withCommitment bool) {
		for name, v := range keys {
			k := v.(obj)
			seed, err := hex.DecodeString(str(k, "seed"))
			if err != nil || len(seed) != 32 {
				bad("%s: key %s: bad seed", file, name)
				continue
			}
			pub := ed25519.NewKeyFromSeed(seed).Public().(ed25519.PublicKey)
			if b64.EncodeToString(pub) != str(k, "public") {
				bad("%s: key %s: public key isn't the seed's", file, name)
			}
			if err := checkKey(pub); err != nil {
				bad("%s: key %s: %v", file, name, err)
			}
			if fingerprint(pub) != str(k, "fingerprint") {
				bad("%s: key %s: wrong fingerprint", file, name)
			}
			if withCommitment && commitment(pub) != str(k, "commitment") {
				bad("%s: key %s: wrong commitment", file, name)
			}
			pubs[name] = pub
		}
	}

	checkCode := func(file string, c core, allowHTTP bool, cd, pf obj) {
		got, err := readCode(str(cd, "text"), c.prefix, allowHTTP)
		if err != nil {
			bad("%s: code: %v", file, err)
			return
		}
		secret, _ := hex.DecodeString(str(cd, "secret"))
		if b64.EncodeToString(got.key) != b64.EncodeToString(pubs[str(cd, "key")]) ||
			hex.EncodeToString(got.secret) != str(cd, "secret") ||
			got.expires != num(cd, "expires") || got.address != str(cd, "address") {
			bad("%s: code: its parts differ from the fields", file)
		}
		if b64.EncodeToString(sha(secret)) != str(cd, "secretHash") {
			bad("%s: wrong secretHash", file)
		}
		if err := checkAddress(str(pf, "address"), allowHTTP); err != nil {
			bad("%s: proof address: %v", file, err)
		}
		if c.proof(secret, pubs[str(pf, "redeemer")], str(pf, "address")) != str(pf, "value") {
			bad("%s: wrong proof", file)
		}
	}

	checkSig := func(where, signer, msg, sig string) {
		s, err := checkB64(sig, 64)
		if err != nil {
			bad("%s: signature: %v", where, err)
			return
		}
		if err := verifyStrict(pubs[signer], []byte(msg), s); err != nil {
			bad("%s: signature: %v", where, err)
		}
	}

	checkExchange := func(file string, c core, e obj) {
		where := file + ": " + str(e, "name")
		nonce, err := hex.DecodeString(str(e, "nonce"))
		if err != nil || len(nonce) != 16 || b64.EncodeToString(nonce) != str(e, "nonceText") {
			bad("%s: nonce and nonceText differ", where)
		}
		if err := checkDate(str(e, "date")); err != nil {
			bad("%s: date: %v", where, err)
		}
		for _, k := range []string{"body", "answerBody"} {
			if err := checkIJSON([]byte(str(e, k))); err != nil {
				bad("%s: %s: %v", where, k, err)
			}
		}
		msg := c.requestMessage(str(e, "method"), str(e, "host"), str(e, "target"), str(e, "date"), str(e, "nonceText"), str(e, "body"))
		if msg != str(e, "message") {
			bad("%s: message isn't rebuilt from the fields", where)
		}
		checkSig(where+" request", str(e, "signer"), msg, str(e, "signature"))
		am := c.answerMessage(str(e, "nonceText"), int(num(e, "status")), str(e, "answerContentType"), str(e, "answerBody"))
		if am != str(e, "answerMessage") {
			bad("%s: answerMessage isn't rebuilt from the fields", where)
		}
		checkSig(where+" answer", str(e, "answerer"), am, str(e, "answerSignature"))
	}

	// vectors/v0.json
	v0 := load("v0.json")
	checkKeys("v0.json", v0["keys"].(obj), false)
	checkCode("v0.json", core0, true, v0["code"].(obj), v0["proof"].(obj))
	for _, e := range v0["exchanges"].([]any) {
		checkExchange("v0.json", core0, e.(obj))
	}

	// vectors/v0-strict.json and vectors/v1/strict.json
	verdicts := func(file, list string, f func(obj) error) {
		o := load(file)
		for _, v := range o[list].([]any) {
			x := v.(obj)
			err := f(x)
			if (err == nil) != (x["valid"] == true) {
				bad("%s: %s %q%q: the file says valid=%v, the check says %v", file, list, str(x, "name"), str(x, "text"), x["valid"], err)
			}
		}
	}
	text := func(x obj) []byte {
		if h := str(x, "hex"); h != "" {
			b, _ := hex.DecodeString(h)
			return b
		}
		return []byte(str(x, "text"))
	}
	verdicts("v0-strict.json", "keys", func(x obj) error {
		b, err := b64.DecodeString(str(x, "text"))
		if err != nil {
			return err
		}
		return checkKey(b)
	})
	verdicts("v0-strict.json", "signatures", func(x obj) error {
		pub, _ := b64.DecodeString(str(x, "public"))
		sig, _ := b64.DecodeString(str(x, "signature"))
		return verifyStrict(pub, []byte(str(x, "message")), sig)
	})
	verdicts("v0-strict.json", "base64url", func(x obj) error {
		n := 32
		if len(str(x, "name")) >= 7 && str(x, "name")[:7] == "a nonce" {
			n = 16
		}
		_, err := checkB64(str(x, "text"), n)
		return err
	})
	verdicts("v0-strict.json", "dates", func(x obj) error { return checkDate(str(x, "text")) })
	verdicts("v0-strict.json", "integers", func(x obj) error { return checkInteger(str(x, "text")) })
	verdicts("v0-strict.json", "json", func(x obj) error { return checkIJSON(text(x)) })
	verdicts("v0-strict.json", "addresses", func(x obj) error { return checkAddress(str(x, "text"), true) })
	verdicts("v0-strict.json", "codes", func(x obj) error { _, err := readCode(str(x, "text"), core0.prefix, true); return err })
	verdicts("v1/strict.json", "addresses", func(x obj) error { return checkAddress(str(x, "text"), false) })
	verdicts("v1/strict.json", "codes", func(x obj) error { _, err := readCode(str(x, "text"), core1.prefix, false); return err })
	verdicts("v1/strict.json", "mediaNames", func(x obj) error { return checkMediaName(str(x, "text")) })
	verdicts("v1/strict.json", "bases", func(x obj) error { return checkBase(str(x, "text")) })
	verdicts("v1/strict.json", "destinations", func(x obj) error { return checkDestination(str(x, "text")) })
	verdicts("v1/strict.json", "uncallableAddresses", func(x obj) error { return checkUncallableAddress(str(x, "text")) })
	for _, v := range load("v1/strict.json")["helloVersions"].([]any) {
		x := v.(obj)
		got, err := keptVersions([]byte(str(x, "text")))
		if (err == nil) != (x["valid"] == true) || got != str(x, "output") {
			bad("v1/strict.json: helloVersions %q: the file says valid=%v, output %q; the rules give %v, %q", str(x, "name"), x["valid"], str(x, "output"), err, got)
		}
	}
	verdicts("v1/media.json", "hls", func(x obj) error { return checkPlaylist([]byte(str(x, "text"))) })
	verdicts("v1/media.json", "pgs", func(x obj) error { return checkPGS(text(x)) })
	for _, v := range load("v1/media.json")["webvtt"].([]any) {
		x := v.(obj)
		got, err := rebuildVTT(text(x))
		if (err == nil) != (x["valid"] == true) || string(got) != str(x, "output") {
			bad("v1/media.json: webvtt %q: the file says valid=%v, output %q; the rules give %v, %q", str(x, "name"), x["valid"], str(x, "output"), err, got)
		}
	}

	mf := load("v1/music.json")
	var libs []string
	for _, l := range mf["libraries"].([]any) {
		libs = append(libs, l.(string))
	}
	for _, v := range mf["keys"].([]any) {
		x := v.(obj)
		kind, err := checkMusicKey(str(x, "text"))
		if (err == nil) != (x["valid"] == true) || kind != str(x, "kind") {
			bad("v1/music.json: key %q: the file says valid=%v, kind %q; the rules give %v, %q", str(x, "text"), x["valid"], str(x, "kind"), err, kind)
		}
	}
	for _, v := range mf["titles"].([]any) {
		x := v.(obj)
		got, err := keepMusicTitle([]byte(str(x, "text")), libs)
		if (err == nil) != (x["valid"] == true) || string(got) != str(x, "output") {
			bad("v1/music.json: title %q: the file says valid=%v, output %q; the rules give %v, %q", str(x, "name"), x["valid"], str(x, "output"), err, got)
		}
		if err == nil {
			if e := checkIJSON(got); e != nil {
				bad("v1/music.json: title %q: output: %v", str(x, "name"), e)
			}
		}
	}

	videoFile := load("v1/video.json")
	var vlibs []string
	for _, l := range videoFile["libraries"].([]any) {
		vlibs = append(vlibs, l.(string))
	}
	for _, v := range videoFile["titles"].([]any) {
		x := v.(obj)
		got, err := keepVideoTitle([]byte(str(x, "text")), vlibs)
		if (err == nil) != (x["valid"] == true) || string(got) != str(x, "output") {
			bad("v1/video.json: title %q: the file says valid=%v, output %q; the rules give %v, %q", str(x, "name"), x["valid"], str(x, "output"), err, got)
		}
		if err == nil {
			if e := checkIJSON(got); e != nil {
				bad("v1/video.json: title %q: output: %v", str(x, "name"), e)
			}
		}
	}

	// vectors/v1/
	keys := load("v1/keys.json")
	checkKeys("v1/keys.json", keys["keys"].(obj), true)
	for name, v := range keys["certificates"].(obj) {
		c := v.(obj)
		der, _ := hex.DecodeString(str(c, "spki"))
		if b64.EncodeToString(sha(der)) != str(c, "pin") {
			bad("v1/keys.json: certificate %s: wrong pin", name)
		}
		seed, _ := hex.DecodeString(str(c, "seed"))
		if hex.EncodeToString(spki(newKey(seed))) != str(c, "spki") {
			bad("v1/keys.json: certificate %s: spki isn't the seed's", name)
		}
	}
	cf := load("v1/code.json")
	checkCode("v1/code.json", core1, false, cf["code"].(obj), cf["proof"].(obj))
	for _, e := range load("v1/exchanges.json")["exchanges"].([]any) {
		checkExchange("v1/exchanges.json", core1, e.(obj))
		checkPrivate("v1/exchanges.json: "+str(e.(obj), "name"), e.(obj), pubs, bad)
	}

	rf := load("v1/rotation.json")
	r := rf["rotation"].(obj)
	old, nu := pubs[str(r, "from")], pubs[str(r, "to")]
	if b64.EncodeToString(old) != str(r, "oldKey") || b64.EncodeToString(nu) != str(r, "newKey") ||
		commitment(pubs[str(r, "next")]) != str(r, "nextCommitment") {
		bad("v1/rotation.json: keys or commitment differ from keys.json")
	}
	st := rotationStatement(old, nu, str(r, "nextCommitment"), num(r, "date"))
	if st != str(r, "statement") {
		bad("v1/rotation.json: statement isn't rebuilt from the fields")
	}
	checkSig("v1/rotation.json old", str(r, "from"), st, str(r, "oldSignature"))
	checkSig("v1/rotation.json new", str(r, "to"), st, str(r, "newSignature"))
	re := rf["exchange"].(obj)
	checkExchange("v1/rotation.json", core1, re)
	var rb obj
	_ = json.Unmarshal([]byte(str(re, "body")), &rb)
	if str(rb, "newKey") != str(r, "newKey") || str(rb, "nextCommitment") != str(r, "nextCommitment") ||
		num(rb, "date") != num(r, "date") || str(rb, "oldSignature") != str(r, "oldSignature") ||
		str(rb, "newSignature") != str(r, "newSignature") || str(re, "signer") != str(r, "from") {
		bad("v1/rotation.json: the rotate request doesn't carry the statement")
	}

	vf := load("v1/revocation.json")
	v := vf["revocation"].(obj)
	vs := revocationStatement(pubs[str(v, "key")], num(v, "date"))
	if vs != str(v, "statement") || b64.EncodeToString(pubs[str(v, "key")]) != str(v, "public") {
		bad("v1/revocation.json: statement isn't rebuilt from the fields")
	}
	checkSig("v1/revocation.json", str(v, "key"), vs, str(v, "signature"))
	ve := vf["exchange"].(obj)
	checkExchange("v1/revocation.json", core1, ve)
	var vb obj
	_ = json.Unmarshal([]byte(str(ve, "body")), &vb)
	if strconv.FormatInt(num(vb, "date"), 10) != strconv.FormatInt(num(v, "date"), 10) ||
		str(vb, "signature") != str(v, "signature") || str(ve, "signer") != str(v, "key") {
		bad("v1/revocation.json: the revoke request doesn't carry the statement")
	}
	return errs
}

// checkPrivate checks the members of a server that can't be called
// (spec/v1/core.md sections 5.2, 7.5, 12.4 and 12.6) in an exchange: an
// inbound false carries an address of the uncallable form, knownKey is a
// test key, and the rotation and revocation an answer carries check out
// under the key that signed the answer.
func checkPrivate(where string, e obj, pubs map[string][]byte, bad func(string, ...any)) {
	var req, ans obj
	_ = json.Unmarshal([]byte(str(e, "body")), &req)
	_ = json.Unmarshal([]byte(str(e, "answerBody")), &ans)
	for _, m := range []obj{req, ans} {
		if v, ok := m["inbound"]; ok {
			if v != false {
				bad("%s: inbound isn't false", where)
			} else if err := checkUncallableAddress(str(m, "address")); err != nil {
				bad("%s: inbound false with address %q: %v", where, str(m, "address"), err)
			}
		}
	}
	if k, ok := req["knownKey"]; ok {
		found := false
		for _, p := range pubs {
			if b64.EncodeToString(p) == k {
				found = true
			}
		}
		if !found {
			bad("%s: knownKey isn't a test key", where)
		}
		if k != b64.EncodeToString(pubs[str(e, "answerer")]) {
			bad("%s: the answer isn't signed with the knownKey", where)
		}
	}
	old := pubs[str(e, "answerer")]
	if r, ok := ans["rotation"].(obj); ok {
		nu, err := checkB64(str(r, "newKey"), 32)
		if err == nil {
			err = checkKey(nu)
		}
		if err != nil {
			bad("%s: rotation newKey: %v", where, err)
			return
		}
		st := rotationStatement(old, nu, str(r, "nextCommitment"), num(r, "date"))
		for _, s := range []struct {
			pub []byte
			sig string
		}{{old, str(r, "oldSignature")}, {nu, str(r, "newSignature")}} {
			sig, err := checkB64(s.sig, 64)
			if err == nil {
				err = verifyStrict(s.pub, []byte(st), sig)
			}
			if err != nil {
				bad("%s: rotation signature: %v", where, err)
			}
		}
		if strconv.FormatInt(num(r, "date"), 10) != str(e, "date") {
			bad("%s: rotation not dated as the exchange", where)
		}
	}
	if v, ok := ans["revocation"].(obj); ok {
		sig, err := checkB64(str(v, "signature"), 64)
		if err == nil {
			err = verifyStrict(old, []byte(revocationStatement(old, num(v, "date"))), sig)
		}
		if err != nil {
			bad("%s: revocation signature: %v", where, err)
		}
	}
}
