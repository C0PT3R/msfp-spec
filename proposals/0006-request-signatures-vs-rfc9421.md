# Proposal 6: Request signatures: our scheme or HTTP Message Signatures (RFC 9421)

Status: Adopted (2026-11-16): MSFP keeps its own scheme, and the answer message covers `Content-Type` in core version 1.
Touches: section 6 of [spec/v0.md](../spec/v0.md).

This proposal is a comparison first. Its recommendation is at the end,
marked as such.

## Problem

MSFP signs requests and answers with its own scheme (section 6): four
headers, a seven-line request message, a four-line answer message,
Ed25519. RFC 9421, HTTP Message Signatures (February 2024), is the IETF
standard for the same job, and RFC 9530 (Digest Fields) covers bodies.
Before more implementations exist, the owner should decide whether MSFP
keeps its scheme or moves to the standard. Moving later costs more:
every implementation's signing code, and the test vectors, would change.

## The two side by side

### What each covers

| Need | MSFP section 6 | RFC 9421 (+ RFC 9530) |
|------|----------------|-----------------------|
| Method, host, path, query | fixed lines | components `@method`, `@authority`, `@path`, `@query`, chosen per signature |
| Body | SHA-256 hex in the message | `Content-Digest` header (RFC 9530), itself a covered component; checked separately |
| Date | `Overfin-Date`, ±5 minutes | `created` parameter; window left to the application |
| Replay | `Overfin-Nonce`, stored, required | `nonce` parameter exists; storing it is left to the application |
| Answer bound to request | the answer message holds the request's nonce | components with `;req` let an answer cover request parts; optional |
| Key | `Overfin-Key`, the raw key | `keyid` parameter; how keys are found is left to the application |
| Algorithm | Ed25519 only | a registry: `ed25519`, `ecdsa-p256-sha256`, `rsa-pss-sha512`, `hmac-sha256`… |
| Header syntax | plain values | Structured Fields (RFC 8941 / RFC 9651) |
| Several signatures | no | yes, by label |

Every MSFP property can be expressed in RFC 9421: cover `@method`,
`@authority`, `@path`, `content-digest`; require `created`, `nonce` and
`keyid`; require `alg="ed25519"`; for answers, cover `@status`,
`content-digest` and the request's signature or nonce with `;req`. MSFP
would then be an RFC 9421 **profile**, and still has to specify every one
of these choices, the window, the nonce memory and the restart rule.

### Complexity

- **MSFP's scheme** is about 90 lines of Go in Overfin (`sign.go`
  without the nonce memory). The plugin's `Signing.cs` and
  `RequestCheck.cs` are of the same order. It needs SHA-256, Ed25519,
  base64url and nothing else. The message is fixed: there is no choice to
  get wrong.
- **RFC 9421** needs a Structured Fields parser and serializer (inner
  lists, parameters, byte sequences), the signature base algorithm with
  its component rules, `Content-Digest` creation and checking, and a
  policy check that the right components were covered (a valid signature
  over too few components must be refused). Written by hand, that is
  several hundred lines and a larger test surface. With a library, it is
  less code, but one more dependency in the security path.

### Libraries

What was **verified** on 2026-11-16, and what was **assumed**:

| Language | Library | Verified | Assumed or unknown |
|----------|---------|----------|--------------------|
| Go | `github.com/yaronf/httpsign` v0.6.2 (Apache-2.0) | An Ed25519 request was signed and verified with `@method`, `@authority`, `@path` and `content-digest` (run here). It requires **Go 1.27** (Overfin is on Go 1.26.11) and pulls in 5 more modules, among them `lestrrat-go/jwx/v4` and `lestrrat-go/option/v3 v3.0.0-alpha1` (an alpha). | Quality of its Structured Fields parsing, response `;req` support in practice, maintenance. |
| Go | `github.com/common-fate/httpsig` | Exists, states RFC 9421, has an Ed25519 package (from its documentation). | Not run. |
| C# | NSign (`NSign.Abstractions`, `NSign.SignatureProviders`, `NSign.AspNetCore`, `NSign.Client`, from Unisys on GitHub) | Exists on NuGet; its listing says an Ed25519 provider came in 1.2.5. | Not run: no .NET on the machine used. Whether its Ed25519 uses BouncyCastle or .NET's own; whether it fits a Jellyfin plugin (ASP.NET Core middleware inside Jellyfin's host). |
| C# | `DamianH.Http.HttpSignatures` | Its listing says HMAC-SHA256 only; Ed25519 is a stub. | Not usable for MSFP. |
| Python | `http-message-signatures` (pyauth, Apache-2.0) | Exists, states RFC 9421. | Ed25519: a fork (`http-msg-sig`) says it fixed the Ed25519 key loader, so upstream support is unclear. Another package reports it can't read `;key=` dictionary members and matches header names case-sensitively. |
| JavaScript | `http-message-signatures` (npm), `@misskey-dev/node-http-message-signatures`, `http-message-sig`, `@hellocoop/httpsig`, `fetch-message-signatures` | Exist on npm. The `http-message-signatures` listing still describes the draft. | No clear leader; none run. |

Summary: one Go library works, at the cost of a newer Go and an alpha
dependency; C# has one serious candidate, untested here; Python and
JavaScript have libraries of uncertain completeness. Every one of them
uses its language's Ed25519, so the verification differences of
proposal 1 come along unchanged.

### How proposal 1 changes the picture

- **Ed25519 rules (C1)** apply to both schemes the same way. RFC 9421
  says "Ed25519 as defined in RFC 8032" and has the same gap. A library
  would have to accept a pre-check hook, or MSFP would check points
  before calling it. Neither scheme wins here.
- **Canonical forms (C2 to C4)**: for MSFP's scheme, proposal 1 is a
  short list (base64url, decimal, one header each). For RFC 9421, the
  equivalent is "parse Structured Fields strictly", which RFC 8941
  defines as an algorithm, and which libraries may or may not follow
  exactly (the Python report above is an example). Strictness is easier
  to state and to test for the small scheme.
- **What proposal 1 can't fix in MSFP's scheme**: unsigned answer
  headers (open question 5) and no algorithm agility. RFC 9421 covers
  headers when listed, and has an algorithm registry. For MSFP, the core
  version (proposal 4) is the agility mechanism: a new algorithm means a
  new label.

### Other considerations

- **Recognition.** Reviewers, auditors and tooling know RFC 9421. A
  custom scheme must be reviewed from scratch. MSFP's is short enough
  that this is feasible, and its test vectors (section 15) are complete.
- **Interoperability beyond MSFP.** RFC 9421 is being taken up by other
  federated systems (some ActivityPub servers, as far as known; not
  checked for this proposal). MSFP servers don't
  talk to those, so this is no direct gain.
- **Proxies.** Both need the path and body kept byte for byte (section
  3). RFC 9421 lets a signer cover fewer components, which a profile
  would forbid anyway.
- **Pairing proof and codes** are outside RFC 9421 in either case.

## Recommendation

> **Recommendation: keep MSFP's own scheme.** Adopt proposal 1 to make
> it strict, rename its labels and headers with core version 1
> (proposal 4) if that is chosen, and add the answer's `Content-Type` to
> the answer message in that same core version (closing open question
> 5). Revisit RFC 9421 if MSFP opens to larger federations, or if mature,
> strict libraries exist in at least Go, C# and one more language.
>
> Reasons: the scheme is small, fully specified, already has test
> vectors and two independent implementations that agree; RFC 9421
> would still need an MSFP profile as long as section 6, plus a
> Structured Fields parser or a library in the security path; the
> libraries checked are uneven, and the only one run needs a newer Go
> and an alpha dependency.

## Alternatives considered

1. **Move to RFC 9421 now, with a strict profile.** The best moment, if
   ever, is before more implementations. Costs both implementations a
   rewrite of signing and every test vector.
2. **Move later**, at a core version change. Possible: core versions
   (proposal 4) allow two schemes side by side for a time. Costs more
   then, but nothing now.
3. **Align names only**: borrow RFC 9421's words (`created`, `nonce`,
   `keyid`) for MSFP's headers. Cosmetic; no interoperability gained.

## Cost

**If the recommendation is taken.** Specification: a paragraph in
section 6 saying why the scheme is its own. If `Content-Type` is added to
the answer message: one line in section 6.3 and new vectors, with core
version 1. Overfin and the plugin: a few lines each, with core version 1.

**If RFC 9421 is chosen.** Specification: section 6 replaced by an RFC
9421 profile (components, parameters, window, nonce memory, answer
binding), new vectors. Overfin: a library (and Go 1.27) or a
Structured Fields implementation; the verifier, nonce memory and answer
checks rewritten around it. Plugin: NSign or its own implementation; the
same rewrite.

## Compatibility

Keeping the scheme: none needed. Moving to RFC 9421: only through a new
core version (proposal 4), with servers speaking both during a
transition, since a version 0 server can't verify RFC 9421 signatures.

## Open points

1. Whether to add `Content-Type` to the answer message (part of the
   recommendation, but it could be decided on its own).
2. Whether the owner wants an external review of the scheme either way.
   It would settle the "custom crypto protocol" concern more directly
   than switching formats.
