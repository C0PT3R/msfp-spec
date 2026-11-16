# Proposal 1: Strict canonical rules

Status: Adopted (2026-11-16), with the check on R required (open point 1).
Touches: sections 2, 3, 4.1, 5, 6, 9.1 and open question 7 of
[spec/v0.md](../spec/v0.md).

## Problem

Version 0 says what a sender must produce, but not always what a receiver
must refuse. Overfin is lenient where its libraries are lenient. The
plugin is strict where it had to guess. Two honest implementations then
disagree about whether some requests are valid. Nothing an honest sender
writes is affected. But a request that one server accepts and another
refuses is a protocol difference, and differences grow once more
implementations exist.

### Evidence: Ed25519

Section 4.1 says "RFC 8032, pure Ed25519". RFC 8032 section 5.1.7 leaves
choices open (the cofactored or the cofactorless equation; it says
nothing about keys of small order), and libraries choose differently.
The plugin's SPEC-GAPS.md, "4.1 Which Ed25519 verification rules", raises
this.

What was checked for this proposal, on 2026-11-16:

| Case | Go 1.26 `crypto/ed25519` | Node 24 / OpenSSL 3.5.7 | BouncyCastle C# |
|------|--------------------------|-------------------------|-----------------|
| Public key = the identity point (small order), R = identity, S = 0 | **accepted**, for any message | **accepted** | refused |
| Public key in a non-canonical encoding (y = p + 1) | accepted | accepted | refused |
| R in a non-canonical encoding | refused | refused | refused |
| S ≥ L | refused | refused | refused |
| An honest key, R = [r]B + T with T of order 8, S = r + k·a | refused | refused | accepted (see below) |
| Equation | cofactorless | cofactorless | cofactored |

- Go and Node: run here. The torsion signature was built with
  `filippo.io/edwards25519` v1.1.0; a cofactored check accepted it, Go's
  `ed25519.Verify` and Node's `crypto.verify` refused it.
- BouncyCastle: the small-order row is a test in the plugin
  (`KeysTests.RefusesTheIdentityAsPublicKey`, BouncyCastle.Cryptography
  2.7.0). The other rows come from reading `Ed25519.cs` on the master
  branch of bc-csharp: `CheckPointVar(R)` refuses y ≥ p,
  `CheckPointFullVar(A)` refuses y ≥ p and the small-order points, and the
  final check clears the cofactor. They were **not run**, and 2.7.0 is
  assumed to match master.

The first row matters most. Under Go's rules, the identity key with the
signature (R = identity, S = 0) verifies **every** message. A peer that
pairs with that key (its fingerprint looks like any other) can be
impersonated by anyone. Overfin accepts such a key today, in a code and in
`Overfin-Key`.

The last row is a signature a malicious key holder can make with an
honest-looking key. BouncyCastle accepts it, Go refuses it. Today only the
direct receiver checks a signature, so this hurts nobody. It becomes a
problem as soon as a signed statement is checked by more than one server
(key rotation, proposal 3; larger federations).

### Evidence: encodings and parsing

| Value | Overfin today (checked in its code) | Plugin (SPEC-GAPS.md) |
|-------|--------------------------------------|-----------------------|
| base64url | Go's `RawURLEncoding`: ignores CR and LF, accepts non-zero unused bits | strict (gap 2.1) |
| JSON duplicates | keeps the last: `{"state":"paired","state":"ended"}` reads as `ended` (run here) | refuses (gap 2.2) |
| JSON name case | `{"State":"ended"}` sets `state` (run here) | unknown field, ignored (gap 2.2) |
| JSON invalid UTF-8, lone surrogates | replaced by U+FFFD, accepted (run here) | not stated |
| `Overfin-Date` | `strconv.ParseInt`: takes `+1800000000`, leading zeros, `-5` | `0` or `[1-9][0-9]{0,17}` (gap 6.4) |
| A header sent twice | the first is read | refused (gap 3) |
| Address `HTTPS://a.example.org` | accepted, stored as written (run here; Go lowercases the scheme while parsing) | refused (gap 5.2.1) |
| Address port `:0`, `:99999`, `:0443` | accepted (run here) | refused (gap 5.2.2) |
| Address `https://a.example.org?` | accepted (run here) | refused (gap 5.2.4) |
| Address with a trailing `/` | accepted, stored as given | accepted; leads to `//api/v1/stream/` (gap 5.2.6) |
| White space in a code | Go's notion | Unicode, `char.IsWhiteSpace` (gap 5.1) |
| Pairing proof input | "the `address` field's bytes, exactly as sent" | the decoded string (gap 9.1) |

## Proposal

Add a section "Canonical forms" to the specification, after section 2.
Every value below has exactly one valid text. A receiver must refuse any
other text, the same way it refuses a bad signature or a bad body
(section 6.4: an unsigned `404` before the signature checks out, a signed
refusal after). A sender must write the canonical form.

### C1. Ed25519

A **public key** is valid only when all of these hold:

1. it is 32 bytes;
2. it is the canonical encoding of a point: the 255-bit y is below
   p = 2^255 − 19, the point is on the curve, and the sign bit is 0 when
   x = 0;
3. the point is in the prime-order subgroup: [L]A is the identity, where
   L = 2^252 + 27742317777372353535851937790883648493. This excludes the
   8 points of small order, and every point with a small-order part.

A **signature** (R ‖ S, 64 bytes) is valid for a message M under a valid
key A only when:

1. R satisfies conditions 2 and 3 above;
2. S, read as a little-endian integer, is below L;
3. [S]B = R + [k]A, where k = SHA-512(R ‖ A ‖ M) mod L.

With A and R both in the prime-order subgroup, the cofactored and the
cofactorless equations accept exactly the same signatures. So any
RFC 8032 library may do step 3, once the point checks are done. Every
honest signature passes: R = [r]B and A = [a]B.

A receiver checks a key once, when it first learns it (in a code, or in
`Overfin-Key` on `pair`), and may cache the result. It checks R on every
signature.

### C2. Text encodings

- **base64url**: only the characters `A–Z a–z 0–9 - _`; no padding, no
  white space; the unused bits of the last character are zero. A simple
  test: re-encoding the decoded bytes gives the same text. Lengths are
  fixed where the value is: 43 characters for 32 bytes, 22 for 16, 86 for
  64.
- **hex**: lowercase `0–9 a–f` only. A SHA-256 is 64 characters.
- **Decimal integers** in headers and in signed messages: `0` or
  `[1-9][0-9]*`, no sign, no white space, at most 9,007,199,254,740,991
  (2^53 − 1). `Overfin-Date` is a positive integer in this form.
- **Status** in an answer message: the three digits of the status code.

### C3. JSON

- Bodies are **I-JSON** (RFC 7493): UTF-8 without a byte order mark, no
  invalid code points or lone surrogates (escaped or not), no object with
  the same member name twice.
- Member names match exactly, case included. A name in another case is
  an unknown member.
- Unknown members are ignored. This is not leniency: it is how later
  versions add fields (section 13).
- Integers: a JSON number with no fraction, no exponent, not `-0`, from
  −(2^53 − 1) to 2^53 − 1. This replaces "within int64" in section 9.
  Every integer MSFP sends today fits.
- `null` is not a valid value for any MSFP member. A sender leaves an
  empty optional member out, or sends `[]` or `""` where the field says
  so. (Toward version 0 peers, see Compatibility.)
- String values are compared and signed after JSON decoding. The pairing
  proof covers the UTF-8 bytes of the decoded `address` value. Since an
  address is ASCII, a sender has no reason to escape any of it.
- Insignificant white space between JSON tokens is allowed. Bodies are
  signed as bytes, never rebuilt, so their layout doesn't matter. Senders
  should send none.

### C4. Headers

- Each of the four signature headers must appear exactly once in a
  request, and `Overfin-Signature` exactly once in an answer. Two
  instances, or one value holding a comma, are refused.
- A header value is taken after HTTP removes leading and trailing
  optional white space. Any other white space inside makes it invalid.
- `Content-Type` is compared without its parameters:
  `application/json; charset=utf-8` is `application/json`.

### C5. Case

Header names are case-insensitive, as in HTTP. Everything else is
case-sensitive and has one case:

- scheme and host of an address: lowercase;
- hex: lowercase;
- enumerated values (`paired`, `movies`, `direct`, `hls`…): exactly as
  listed;
- title keys: exactly as section 11 writes them;
- language tags: the case conventions of BCP 47 (RFC 5646 section 2.1.1):
  language lowercase, script title case, region uppercase (`fr-CA`,
  `zh-Hant-TW`). Receivers compare tags case-insensitively, so `fr-ca`
  and `fr-CA` count as one tag, but senders write the conventional form.

### C6. Addresses (replaces the list in section 5.2)

```
address = scheme "://" host [ ":" port ]
scheme  = "https" / "http"
port    = a decimal integer from 1 to 65535, without leading zeros,
          and not the scheme's default (443 for https, 80 for http)
host    = name / ipv4 / "[" ipv6 "]"
name    = labels of 1 to 63 characters of a-z 0-9 -, not starting or
          ending with -, joined by "."; at most 253 characters in all
ipv4    = four decimal numbers 0 to 255 without leading zeros
ipv6    = an IPv6 address in the text form of RFC 5952 (lowercase,
          longest run of zeros compressed); no zone identifier
```

The whole address is at most 512 bytes of ASCII. There is no path, not
even `/`; no `?`, `#` or `@`. A server that has a trailing slash in its own
configuration removes it before it writes its address anywhere.

### C7. The pairing code (replaces the reader's list in section 5.1)

- A reader removes every character with the Unicode `White_Space`
  property, anywhere. A valid code is ASCII, so this can't change one.
- The prefix must match exactly, case included.
- The rest is base64url as in C2, at most 779 characters (584 bytes:
  72 plus a 512-byte address), decoding to more than 72 bytes.
- The address bytes are ASCII and satisfy C6.
- The expiry is at most 2^53 − 1. A larger value makes the code invalid.

## Alternatives considered

1. **Name a library's behaviour** ("as Go's `crypto/ed25519`"). Simple
   for Go. But Go's rules accept the identity key, which allows universal
   forgery under that key, and a C# or Python implementation can't
   reproduce Go's exact behaviour without reimplementing it.
2. **Cofactorless, plus a block list of the 8 small-order encodings for
   A and R.** Go, OpenSSL and libsodium need only the list. But
   BouncyCastle's `Verify` is cofactored and accepts the torsion row
   above; a C# implementation would need its own curve arithmetic to
   match. Rejected for that reason.
3. **ZIP-215** (cofactored, non-canonical A and R allowed). Built for
   consensus with batch verification. No common library does it by
   default: Go refuses non-canonical R, BouncyCastle refuses
   non-canonical A. Every implementation would need a special library.
4. **Say edge cases are out of scope.** Cheapest. Harmless while only the
   direct receiver checks a signature. It leaves the identity-key forgery
   in place, and it would have to be revisited for proposal 3.
5. **Canonical JSON (RFC 8785, JCS) for bodies.** Not needed: the
   signature covers the body bytes, which are never rebuilt. It would
   force every receiver to re-serialize and compare. Rejected.
6. **Keep "accept leniently, send strictly"** (Postel). This is what
   created the table above.

## Cost

**Specification.** One new section (about two pages), replacing parts of
sections 2, 4.1, 5.1 and 5.2; open question 7 closes. New test vectors:
the identity key; a non-canonical key; a torsion R; S + L; a base64url
text with non-zero unused bits; a duplicate member; an address list with
the expected verdicts.

**Overfin** (from reading `internal/federation`):

- `sign.go`: strict base64url (decode, re-encode, compare: Go's
  `Strict()` mode still ignores CR and LF); the date grammar; one
  instance of each header (`r.Header.Values`). About 40 lines.
- Ed25519 point checks: Go's standard library doesn't expose curve
  arithmetic. `filippo.io/edwards25519` (the code the standard library
  uses inside) does. The subgroup test is [L − 1]P + P = identity,
  about 20 lines; it was tried here and tells the torsion R apart. It
  adds one dependency. Keys are checked once and cached; R costs about
  one more scalar multiplication per request.
- JSON: Go's `encoding/json` can't refuse duplicates, case variants or
  invalid UTF-8. `encoding/json/v2` does all three (checked here), but in
  Go 1.26 it still needs `GOEXPERIMENT=jsonv2`. Until it is standard, a
  pre-pass with the v1 `json.Decoder` token stream (duplicates, UTF-8,
  number forms) is about 80 lines.
- `code.go`: `checkAddress` follows C6 (scheme case, port, trailing
  slash, empty query).
- Answers: send `[]` or leave out, never `null` (nil slices marshal as
  `null` in Go).

**Plugin.** Most of C2 to C7 is what it already assumes. Changes: refuse
a trailing slash in addresses (it accepts one now); call BouncyCastle's
`Ed25519.ValidatePublicKeyFull` on A when a key is learnt and on R for
each signature (it checks the encoding, small order and the subgroup,
according to the source; not run here); check integer ranges.

## Compatibility

- **Honest senders are unaffected.** Overfin and the plugin already
  write canonical keys, nonces, signatures, dates and addresses, and
  their keys are honest. So C1 to C7 can apply to version 0 itself, as
  errata, without a version change.
- **`null`.** Overfin version 0 may send `null` for empty arrays, and
  section 2 tells receivers to accept it. A receiver keeps treating
  `null` as absent toward a peer that speaks version 0 (proposal 4), or
  for one release cycle if proposal 4 isn't taken. Overfin stops sending
  it in the same release.
- **Stored state.** A pairing whose stored address breaks C6 (an
  uppercase scheme, a trailing slash) is kept, normalized once on
  upgrade. A stored key that breaks C1 is marked unusable and shown to
  the operator; no honest key does.
- **Order of rollout.** Senders first (Overfin's `null`), then
  receivers. Each implementation turns on strict receiving in its next
  release.

## Open points

1. Should the point check on R be required, or only recommended? Without
   it, the torsion case stays a disagreement, but only the key's holder
   can produce it. Required is proposed, because proposal 3's statements
   are meant to be checked by more than one server.
2. Python and JavaScript: PyNaCl's `crypto_core_ed25519_is_valid_point`
   and `@noble/curves` (`isTorsionFree`) are believed to cover C1's point
   checks. Not verified here.
3. Whether a refusal for a non-canonical form, after the signature
   checked out, should carry a specific problem `type`
   (`invalid-request`) to help implementers debug, or stay a plain `404`
   as today.
