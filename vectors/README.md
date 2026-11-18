# MSFP test vectors

Values for an implementation's tests to check against. They are under
[CC0 1.0](LICENSE): copy them into any test suite.

| File | Version | Where it comes from |
|------|---------|---------------------|
| [v0.json](v0.json) | 0 | Overfin's own code. Keys, a pairing code, the pairing proof, and three signed exchanges ([v0 section 15](../spec/v0.md#15-test-vectors)). Implementations keep copies of it and check them, so it never changes. |
| [v0-strict.json](v0-strict.json) | 0 | The generator below. Valid and invalid cases for the canonical forms of [v0 section 2.1](../spec/v0.md#21-canonical-forms) and the code and address rules of v0 section 5: keys (the identity, a point of order 8, a key with a small-order part, a non-canonical encoding), signatures (an identity-key forgery, a torsion R, S + L), base64url, dates, integers, JSON bodies, addresses and codes, each with its verdict. They hold for core 1 too, except that core 1 refuses `http`. |
| [v1/](v1/) | core 1 | The generator below. Keys and commitments, a `msfp-pair-1.` code with an `https` address, signed requests and answers under the MSFP labels and headers (with the answer's media type), a rotation statement, a revocation statement, a `hello` carrying `core`, `parts`, `certificates` and `address`, the `hello`s of a server that can't be called (`inbound: false`, `knownKey`, and an answer carrying `rotation` and `revocation`), address and code verdicts under core 1, the addresses of servers that can't be called (`msfp-<26>.invalid`), the destinations a server refuses to connect to, WebVTT, HLS and PGS cases, and music title keys and titles with what a caller keeps of each ([core section 17](../spec/v1/core.md#17-test-vectors)). |

**No implementation produced the files of version 1, nor v0-strict.json.**
The media and destination cases were checked against Overfin's own
sanitizer and checks on 2026-11-16: they agree, except for the HLS cases
that [media section 3.1](../spec/v1/media.md#31-hls-playlists) lists in
its Overfin note.
Overfin's code doesn't implement version 1 yet. Since 2026-11-16 it
follows the stricter rules of version 0's corrections, and runs every case
of v0-strict.json through its own checks. Those files still come from the
generator alone: an independent program written from the specification. When an
implementation disagrees with them, check the specification first; either
may be wrong, and a report is welcome.

In every file, `valid` is what a receiver must decide. `reason` is the
generator's own wording, for people; an implementation needn't give the
same reason, only the same verdict. Bodies and messages are the exact
bytes, as JSON strings; a body that isn't printable ASCII is given as
`hex` instead.

## The generator

[tools/vectors/](../tools/vectors/) is a small Go program, with the
standard library and `filippo.io/edwards25519` (for the point checks of
Ed25519) as its only dependency.

```
cd tools/vectors
go run .          # checks every file in vectors/
go run . -write   # writes v0-strict.json and v1/*.json, then checks
go test ./...     # checks what the files say about common libraries
```

The check:

- regenerates every file it writes and compares the bytes;
- regenerates v0.json from version 0's rules and compares the bytes,
  without ever writing it;
- reads every file back and checks each value on its own: public keys,
  fingerprints and commitments from their seeds, codes from their parts,
  every signed message rebuilt from its fields, every signature under the
  strict rules, every pin from its key, and every verdict against the
  generator's checks.

Its tests confirm the comments in v0-strict.json about common libraries
(Go's `crypto/ed25519` accepts the identity-key forgery and refuses the
torsion R; a cofactored check accepts the torsion R), and check IPv6
addresses, which the vectors leave out.
