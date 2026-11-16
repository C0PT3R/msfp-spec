// Command vectors makes and checks MSFP's test vectors.
//
//	go run .          checks every vector file against the specification's rules
//	go run . -write   writes vectors/v0-strict.json and vectors/v1/*.json, then checks
//
// vectors/v0.json is never written: it came from Overfin's code, and
// implementations keep copies of it. The check regenerates it and
// insists on the same bytes.
package main

import (
	"bytes"
	"flag"
	"fmt"
	"os"
	"path/filepath"
)

func main() {
	write := flag.Bool("write", false, "write the generated vector files before checking")
	dir := flag.String("dir", "../../vectors", "the vectors folder")
	flag.Parse()

	generated := []struct {
		path string
		make func() []byte
	}{
		{"v0-strict.json", genV0Strict},
		{"v1/keys.json", genV1Keys},
		{"v1/code.json", genV1Code},
		{"v1/exchanges.json", genV1Exchanges},
		{"v1/rotation.json", genV1Rotation},
		{"v1/revocation.json", genV1Revocation},
		{"v1/strict.json", genV1Strict},
	}

	failed := false
	fail := func(format string, a ...any) {
		fmt.Fprintf(os.Stderr, "FAIL "+format+"\n", a...)
		failed = true
	}

	if *write {
		for _, g := range generated {
			p := filepath.Join(*dir, g.path)
			if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
				fail("%v", err)
				continue
			}
			if err := os.WriteFile(p, g.make(), 0o644); err != nil {
				fail("%v", err)
			}
		}
	}

	// 1. Every file is what this program makes, byte for byte.
	read := func(rel string) []byte {
		b, err := os.ReadFile(filepath.Join(*dir, rel))
		if err != nil {
			fail("%v", err)
		}
		return b
	}
	if !bytes.Equal(read("v0.json"), genV0()) {
		fail("v0.json: not what the version 0 rules give")
	}
	for _, g := range generated {
		if !bytes.Equal(read(g.path), g.make()) {
			fail("%s: differs from what this program makes (run with -write?)", g.path)
		}
	}

	// 2. Every value in the files checks out on its own, read back from
	// the files rather than from the generator's variables.
	for _, err := range verifyAll(read) {
		fail("%v", err)
	}

	if failed {
		os.Exit(1)
	}
	fmt.Println("ok: every vector checks out")
}
