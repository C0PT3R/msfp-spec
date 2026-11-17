# MSFP version 0 conformance suite

A program that plays a peer against a server you run, and checks that
server against [spec/v0.md](../spec/v0.md) as corrected on 2026-11-16 and
2026-11-17.
It pairs with the server from a pairing code, then checks the pairing,
`hello` in its states, signatures both ways, the strict forms of section
2.1, replay and nonces, `libraries` and `titles` (whole, changes, paging,
`gone`), refusals (signed and unsigned `404`s), and, when asked, rate
limits and ending. Every check names the section it tests, and whether
that section says *must* or *should*. The output is a list of PASS, FAIL
and SKIP.

It needs Python 3 and its standard library, nothing else (tested with
Python 3.13): Ed25519 is bundled, in
pure Python (the reference code of RFC 8032 with section 2.1's point
checks on top). It is test code: slow, not constant-time, never for a key
that matters.

`play`, `progress`, `stop` and the media of section 10 aren't checked yet.

## Running it

The target must be able to reach the suite: the suite puts its own
address in the `pair` request, and the target calls it there (`hello`
when its operator accepts, and `libraries` and `titles` when it reads
the suite's catalog). Section 3.2 lets servers refuse loopback, so run
the suite on another machine, or another container, on a private
network the target reaches.

1. On the target, make a pairing code (it works once: one code per run).
2. Run the suite:

   ```sh
   python3 conformance/run.py \
       --code 'overfin-pair-1.…' \
       --address http://192.0.2.40:8000 \
       --listen 0.0.0.0:8000
   ```

   `--address` is where the target reaches the suite (`http://` only:
   the suite serves no HTTPS); `--listen` is where it listens.
3. When the suite says so, accept the pairing on the target. Check the
   fingerprint it prints against the target's page. The suite waits
   `--accept-timeout` seconds (600 by default).
4. On the target, offer this peer at least one library, ideally with two
   titles or more: the `titles` checks are skipped when nothing is
   offered.

Without `--code`, only the checks a stranger can make run (S1 to S4).

The suite offers the target one library, "Conformance films", with three
films on two pages. To check the target as a reader too (Q1 to Q3), pass
`--reader-timeout 120` and, on the target, want that library. The
suite's first page is short and still has `next`, on purpose, to see
that the target follows it; section 9.4 says a whole-list `next` comes
only after a full page of 5,000, so the suite itself breaks that rule
there.

Options that change the target, or load it, are off by default:

| Option | What it does |
|--------|--------------|
| `--watch-changes SECONDS` | T8: asks you to add one title to an offered library and remove one on the target, then reads `since` until the change shows, and checks that `titles` and `gone` add up to the new whole list. |
| `--load` | R1 and R2: sends `--load-count` (1,000) calls at once over 32 connections, and expects a signed `429` `rate-limited` (or `503` `server-busy`) with `retryAfter` (section 8.3). The numbers are each server's, so a burst that meets no limit is a SKIP unless it was big and fast (1,000 calls at 300 a second or more); a pure-Python client rarely gets there over HTTPS. |
| `--end` | E1 and E2: ends the pairing with `hello` `ended` (section 7.4). Without it, the pairing stays: remove the peer on the target afterwards. |

Other options: `--target` (the target's address, when not given by a
code), `--connect host:port` (connect elsewhere than the address says,
the requests staying signed for the address), `--key FILE` (keep this
peer's key between runs), `--json FILE` (the results as JSON), `-v`
(details of passing checks too). The exit status is 1 when a check
failed.

Over `https`, the suite follows section 3.1: `pair` and `hello` take any
certificate; every other call needs one that is publicly trusted or
whose pin the target named in its latest signed `hello`.

`python3 conformance/selftest.py` runs the suite's own readers over
`vectors/v0-strict.json` and checks key "a" of `vectors/v0.json`; it
needs no server.

## The checks

| ID | Section | What is checked |
|----|---------|-----------------|
| C1 | 5.1 | the pairing code reads as section 5.1 says (prefix, base64url, key, expiry, address) |
| S1 | 6.4 | a stranger's `hello` gets the unsigned `404` |
| S2 | 6.4 | a stranger's `libraries` and `titles` get the unsigned `404` |
| S3 | 3, 14 | the unsigned `404` can't be told from a path that doesn't exist (should) |
| S4 | 3, 14 | a wrong method on a federation path answers like a missing path (should) |
| P1 | 9.1, 6.6 | `pair` with a wrong proof: the unsigned `404`, the code stays live |
| P2 | 2.1, 4.1 | `pair` under the identity key with the forged signature (R the identity, S = 0) is refused |
| P3 | 2.1, 4.1 | `pair` under a small-order key, a key with a small-order part, or a non-canonical key is refused |
| P4 | 6.4 | `pair` dated 400 seconds ago is refused |
| P5 | 5.2, 9.1 | `pair` naming an address that breaks section 5.2 is refused, the code stays live |
| P6 | 9.1, 7.1 | `pair` with the code: `200`, signed by the code's key, with a name |
| P7 | 6.5 | the same `pair` request again (its nonce replayed): the unsigned `404` |
| P8 | 9.1, 7.1 | the used code again, from the now known key: a signed `404` |
| W1 | 9.2, 7.3 | `hello` `waiting`: `200` signed, `waiting` |
| W2 | 7.1, 9.2 | `hello` `paired` from a waiting peer changes nothing |
| W3 | 7.3 | `libraries` before the target's operator accepts: a signed `404` |
| W4 | 7.1, 6.4 | on accepting, the target sends the suite a well-signed `hello` `paired` |
| H1 | 9.2 | `hello` `paired`: `200` signed, `paired`, `certificates` an array if there |
| H2 | 3.1 | over `https`, the target names the pin of the leaf it serves (should) |
| H3 | 3.1 | over `https`, checked calls pass with the certificate trusted or named |
| J1 | 2.1, 9.2 | `hello` bodies that aren't valid get a signed `404`: no or bad `state`, `State`, `certificates` not an array, not an object, a member twice (also escaped, also nested), lone surrogates, a noncharacter, invalid UTF-8, a byte order mark |
| J2 | 2.1, 9.2 | valid bodies pass: white space between tokens, an escaped surrogate pair, unknown members, `null` as absent, an unknown `state` |
| G1 | 2.1, 6.4 | dates (±330 s, `+`, a leading zero, a fraction, `0`, 2^53), nonces (15 bytes, padding, nonzero unused bits, another alphabet), a key text with nonzero unused bits, and requests signed for another host or path get the unsigned `404` |
| G2 | 2.1, 6.4 | a signature header twice, a nonce header twice, a comma in the signature, a tab inside the date: the unsigned `404` |
| G3 | 2.1 | header names in any case, white space around a value, `charset` on `Content-Type`: accepted |
| G4 | 6.2, 6.4 | a call with a query is refused, even when signed so |
| G5 | 6.2 | the target is taken as received: a percent-encoded path signed in its decoded form fails |
| G6 | 3 | no `Content-Type`, or `text/plain`: refused, unsigned (`404`; Overfin's `415` is its version 0 note) |
| G7 | 3 | a cross-site `Sec-Fetch-Site`: refused, unsigned |
| G8 | 3, 6.3 | a `hello` sent with `Accept-Encoding: gzip`: `200` signed, with no `Content-Encoding` (any answer with a content coding counts as unsigned) |
| N1 | 6.5 | a request replayed with its nonce: the unsigned `404` |
| N2 | 6.5 | a nonce used again in a new, validly signed request: the unsigned `404` |
| N3 | 6.3 | the answer's signature is bound to the request's nonce |
| L1 | 9.3 | `libraries`: `200` signed, IDs and kinds in their forms, no ID twice, `limits` in range |
| L2 | 9.3, 12 | library IDs don't look like a media server's (32 hex digits, a GUID); a heuristic (should) |
| L3 | 9.3, 2.1 | a `libraries` body that isn't an I-JSON object: a signed `404` |
| T1 | 9.4, 11 | the whole list: canonical TMDB keys, matching kinds, asked libraries, language tags (form, once, no `und`/`mul`/`zxx`/`mis`, case, shortest code), no languages on series and seasons, ascending order, `next` rules, `seq` |
| T2 | 9.4 | a page starts strictly after `after` |
| T3 | 9.4 | `since` the current `seq`: a changes answer, or the whole list |
| T4 | 9.4 | `since` above the current `seq`: the whole list |
| T5 | 9.4 | a negative `since`: answered like `0` |
| T6 | 9.4, 2.1, 9 | `since` as `"5"`, `1.0`, `1e1`, 2^53 or `-0`, `after` over 512 bytes, a library ID that isn't a string, `libraries` missing or `null`: a signed `404` (for `libraries` missing, by section 9's "required") |
| T7 | 9.4, 12 | a library ID that isn't offered is ignored |
| T8 | 9.4 | (`--watch-changes`) after a change: `titles` and `gone` add up to the new whole list |
| Q1 | 6.4, 9.3, 9.4 | (`--reader-timeout`) the target's calls to the suite: each signature header once, the date in the window, a fresh nonce, a valid signature over the suite's host, JSON, no query, no `Sec-Fetch-*` |
| Q2 | 9.4 | the target's `titles` requests: libraries the suite offers, `after` a string, `since` an integer |
| Q3 | 9.4 | the target follows `next` |
| R1 | 8.3 | (`--load`) past a peer's limit: a signed `429` `rate-limited` or `503` `server-busy`, `retryAfter` from 1 to 3,600 |
| R2 | 8.3 | (`--load`) after `retryAfter`, calls pass again |
| E1 | 7.4, 9.2 | (`--end`) `hello` `ended`: `200` signed, `ended` |
| E2 | 7.4, 6.4 | (`--end`) afterwards the target has deleted the suite: the unsigned `404` (the receiver of `ended` doesn't record the ender as forgotten) |
| A1 | 6.6 | every answer the suite checked was signed by the target's key, by section 2.1's rules |

Every signed answer is also read as I-JSON (section 2.1) and checked for
`null` (section 2: a sender must not send it).

## License

The suite's code is under the [MIT license](LICENSE). The Ed25519
reference code it bundles (`msfpconf/ed25519.py`) is the IETF Trust's,
under the Simplified BSD License, whose notice is at the top of that
file. The specification is under CC BY 4.0 and the vectors under CC0
(see the repository's README).
