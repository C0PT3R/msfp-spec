# Proposal 9: Private servers

Status: Option 1 adopted (2026-11-16); option 2 (the reverse connection) set aside for now. Open points still open.
Touches: sections 3, 5.2, 7.1, 7.4, 9.1, 9.2, 11, 12.4, 12.6 and 13.2 of
[spec/v1/core.md](../spec/v1/core.md), and sections 1, 2 and 4 of
[spec/v1/media.md](../spec/v1/media.md); option 2 adds a part.

A **private server** here is one that can connect out to the internet but
can't be connected to: no public address, no port forwarded, no gateway.
For example a server at home behind a router or a carrier-grade NAT, or a
Jellyfin with the MSFP plugin on a home network. Its **peer** here is a
server that is reachable on the internet. A private server whose public
part is a gateway it runs itself (a backend behind a public gateway) is
not concerned: the gateway is reachable, and is the address its peers
know.

This proposal gives two options, for the owner to decide: adopt one,
both, or option 1 first. Its recommendation is at the end, marked as
such. In the examples, P is the private server and Q its public peer.

## Problem

MSFP assumes that each of two peers can call the other over HTTPS.

- **Both sides call.** Core section 3's table: `hello` is sent by "either
  peer", `libraries` and `titles` by "either paired peer", and `play`,
  `progress` and `stop` by "the viewer's server [calling] the owning
  server". Version 0 has the same table (v0 section 3).
- **The owning server is called, and serves media.** The viewer's server
  calls `play` on the owning server ([playback section 2](../spec/v1/playback.md#2-play)),
  and fetches the media from the owning server's stream root, built on
  the owning server's address ([media section 1](../spec/v1/media.md#1-the-urls);
  v0 section 10.1).
- **Calls the private side never receives.** Every call a peer makes of
  its own accord: the `hello` that tells a redeemer its pairing was
  accepted (core 7.1, step 6), the `hello` with `ended` (7.4, step 2),
  `rotate` (9.3, 12.4), `revoke` (9.4, 12.6), the `hello` that confirms an
  address change (13.2, step 2), the `hello` after a refused certificate
  (3.2, "Renewals"), the `hello` after a signed `404` (9.2), the fetch of
  the discovery document after storing a redeemer's address (11).

So for P:

| P as | What happens today |
|------|--------------------|
| a viewer's server | half works. P's calls go out: `pair` (P redeems Q's code), `hello`, `libraries`, `titles`, `play`, `progress`, `stop`, and the media fetches. Everything Q starts fails. |
| an owning server | doesn't work. Q can't call `play` on P, and couldn't fetch P's media. |
| a code maker | doesn't work. Q's `pair` goes to the address in P's code, which can't be reached; Q tells its operator the address can't be reached (core 3.3, "What a refused address means"). |

What "half works" means, call by call, under core 1 as written:

1. **Acceptance.** When Q's operator accepts, Q's `hello` to P fails. Core
   7.1, step 7 covers it: P learns at its next `hello`, and "should ask
   every 20 seconds at most while its panel shows a peer in state
   `theirs`". Overfin does that only while its panel is open on the peer
   (`checkEvery` in `internal/federation/service.go`, read 2026-11-16). A
   private Overfin whose operator closed the panel stays `theirs` until
   the panel is opened again.
2. **Ending.** When Q's operator ends the pairing, Q's `hello` with
   `ended` fails, and "nothing more is done" (7.4, step 2). P learns on its
   next call that gets a signed `404`, then sends a `hello` (9.2). With
   Overfin, which reads a paired peer's titles every 30 minutes
   (`syncEvery`), that is up to half an hour. Harmless: Q refuses
   everything meanwhile.
3. **Q's rotation breaks the pairing after 30 days.** Q sends `rotate` to
   every peer, and again "at each contact and at least daily" (12.4); none
   reaches P. Q keeps signing toward P with its old key O, then deletes O
   after 30 days. From then on Q signs its answers to P with N, P checks
   them against O (6.6), and treats Q as unreachable, for good. P has to
   pair again, and nothing in the protocol tells either operator why.
4. **Q's revocation never reaches P.** Q sends `revoke` "to every peer it
   can reach" (12.6). P is not one. P keeps trusting the revoked key until
   its operator ends the pairing. A thief holding Q's key can't call P
   either, so the harm needs the thief to answer P's calls at Q's address
   too; but revocation is exactly the case where the spec wants every
   peer told.
5. **P's address.** P still has an address (5.2), in its `pair` request,
   bound by the proof (9.1). Q stores it and calls it. Often it is a LAN
   address, in one of the private ranges section 3.3 allows by default: Q then sends its `hello`s to whatever answers at that address
   on **Q's** network. Harmless only because the request is signed for
   P's host and carries nothing secret.
6. **P's address change.** Q confirms a new address by a `hello` there
   (13.2, step 2). It fails; Q keeps the old one and warns its operator
   after a day. Neither address was ever reachable, so the warning is
   noise.
7. **What does work**, because it comes in answers to P's own calls: Q's
   versions and pins (9.2), Q's address change (Q names its new address in
   its `hello` answers, 13.1, step 3, and P confirms it by calling out),
   and P's certificate retries (3.2: P sends a `hello` to Q, which it can).

Two private servers can't pair at all: neither can redeem the other's
code.

## Proposal

### Option 1: a peer that can't be called

A private server says so, its peer stops calling it, and the private
server asks, on a schedule, for what it would otherwise be told. P can
then watch what Q shares, reliably, with rotation and revocation
reaching it. P still shares nothing with Q.

#### 1.1 The `inbound` member

`pair` requests (9.1) and `hello` requests and answers (9.2) gain an
optional member:

| Field | Type | Content |
|-------|------|---------|
| `inbound` | boolean | `false`: the sender can't be called. Absent or `true`: as today |

- A receiver keeps, per peer, the value of the latest signed message that
  carried one, request or answer, latest by arrival, as for pins (3.2).
  A `hello` without `inbound` sets it back to `true`. In `pair`, the maker
  stores it with the new peer.
- A member that isn't a boolean is a bad body (9.2), as for the other
  members.
- A server sends `inbound: false` in every `pair` and `hello` it sends,
  and in every `hello` answer it gives, while its operator says it can't
  be called. A server can't tell by itself that it can't be reached, so
  this is the operator's setting (open point 2).

#### 1.2 What a peer does toward a server that can't be called

Toward a peer whose `inbound` is `false`, a server opens no connection at
all. Each call it would make:

| Call | Normally | Toward a peer that can't be called |
|------|----------|-------------------------------------|
| `hello` on acceptance (7.1, step 6) | sent | not sent; the peer's next `hello` gets `paired` |
| `hello` to check, after a signed `404` (9.2), to recompute versions (10.4), after a refused certificate (3.2) | sent | not sent |
| `hello` with `ended` (7.4, step 2) | sent | not sent; the peer's next `hello` gets the signed `404` of a forgotten key, and the peer marks it `gone` (9.2) |
| `rotate` (9.3, 12.4) | sent at each contact, at least daily | not sent; the statement travels in `hello` answers (1.4) |
| `revoke` (9.4, 12.6) | sent to every peer it can reach | not sent; the statement travels in `hello` answers (1.5) |
| `hello` confirming an address change (13.2, step 2) | sent to the new address | not sent; see 1.6 |
| the discovery document (11) | fetched after storing a redeemer's address | not fetched |
| `libraries`, `titles` | called | not called; the peer's catalog isn't shown |
| `play`, `progress`, `stop`, media | called, fetched | not called; nothing of the peer is offered for playing |

Its panel says what that means: "this server can't be called: it can
watch what you share with it, and can share nothing with you".

When a peer's `inbound` changes from `false` to `true`, the server
confirms the peer's stored address as section 13.2, step 2 does (a
`hello` there, answered under the peer's key) before it makes any other
call to it. Until that `hello` succeeds, it goes on as if `inbound` were
`false`.

#### 1.3 What the server that can't be called does

1. **No codes.** It makes no pairing code: its panel tells its operator to
   ask the other operator for one. It can redeem codes. Two servers that
   both can't be called can't pair.
2. **`hello` on a schedule**, to every peer that isn't suspended, whether
   or not its panel is open:
   - every 20 seconds while the peer is `theirs` (7.1, step 7 becomes a
     "must" for it, for 24 hours after the `pair`, then every 5 minutes);
   - every 5 minutes while it is `paired`;
   - once an hour while it is `gone`, so that a pairing the peer restores
     comes back (9.2);
   - and at once on the occasions where it would send one anyway.

   Each wait varies by a fifth either way. These `hello`s count against
   the peer's limits like any other call (8.3); a signed `retryAfter` is
   obeyed.
3. **Its address** stays in the form of section 5.2, since the pairing
   proof binds it (9.1), but nothing ever connects to it. It should be a
   name that is either its operator's own or can't resolve at all, never a
   LAN address. Recommended: `https://msfp-<26 characters>.invalid`, the
   26 characters being 16 random bytes in lowercase base32 (RFC 4648
   section 6, `a-z2-7`, no padding), made once and kept. `.invalid` never
   resolves (RFC 6761 section 6.4), so a peer that ignores `inbound`
   connects nowhere, and section 3.3 never comes into play.
4. **Pins.** It names none (nothing is served at its address). It keeps
   learning its peers' pins from their answers, as today.

#### 1.4 Rotation by the peer, pulled

When Q rotates from O to N (section 12) and P can't be called:

1. Q's `hello` answers to P carry an optional member `rotation`, an
   object with the members of the `rotate` request (9.3): `newKey`,
   `nextCommitment` (optional), `date`, `oldSignature`, `newSignature`.
   Each answer carries a newly dated statement, as 12.4 already asks of
   repeated `rotate`s. The answer itself is signed with O.
2. P handles it as section 12.3 handles a `rotate` signed with O: the key
   the answer verified under is O. The outcome is what P would have
   answered: rotated, pending, or refused.
3. P's `hello` requests carry an optional member `knownKey`: the key P
   checks Q's answers against, now. After P makes N current, its next
   request to Q is a `hello` with `knownKey` N, sent at once. If the
   rotation is pending or refused, P's `hello`s carry `knownKey` O and an
   optional member `rotation` with the string `pending` or `refused`.
4. Q reads `knownKey` before it answers. N: Q treats P as having answered
   `rotated` (12.4), and signs toward P with N only, that answer
   included. O: nothing changes, and Q's panel shows `pending` or
   `refused` when P sent it.
5. P checks each answer against the key it knew Q by when it **sent** the
   request. So answers to calls already on their way when it made N
   current, still signed with O, verify.
6. Q's 30-day limit (12.4) is unchanged.

`knownKey` and `rotation` are ignored from a peer whose `inbound` isn't
`false`, and `knownKey` is ignored when it is neither of Q's keys. A
`knownKey` can only pick between Q's own two keys, and only P can send it
(the request is signed by P), so it gives nothing to anyone else.

#### 1.5 Revocation by the peer, pulled

When Q revokes its key K (12.6), its `hello` answers to a peer that can't
be called carry, for 30 days, an optional member `revocation`: `date` and
`signature`, as in `revoke` (9.4), the statement newly dated in each
answer. P checks it as section 12.6 says, and suspends Q.

A suspended Q gets no calls from P, except P's scheduled `hello`, kept so
that a rotation can still reach it. Of those answers P reads only
`rotation`, and accepts only one that matches the stored commitment
(12.3, case 2). When Q revokes and rotates in one action (12.7, case 1),
one answer carries both: P applies `revocation`, then `rotation`.

The delay is at most one `hello` period (5 minutes, give or take a fifth),
where a `revoke` sent today takes one call.

#### 1.6 Address changes

- **Q moves.** Unchanged: Q names its new address in its `hello` answers
  (13.1, step 3), and P confirms it by a `hello` there (13.2), which P can
  make.
- **P moves.** Q stores P's new address from P's signed `hello` at once,
  without the confirming call of 13.2, step 2: that call proves the key
  holder answers at the address, which matters only for an address that
  is called. Q drops nothing, since it holds no pins of P's. If P later
  sends `inbound: true`, the confirmation of 1.2 happens then.

#### 1.7 What stays as it is

P's own calls (`pair`, `hello`, `libraries`, `titles`, `play`,
`progress`, `stop`, the media) and everything Q checks about them. P
ending a pairing (it sends `ended`, which it can). Q ending P's playbacks
at once when the pairing ends (playback section 6.3): P's player then gets
`404` on the next fetch, and treats the playback as ended (core 8.4).

### Option 2: a reverse connection, the `transport` part

P keeps a connection open to Q. Over it, Q sends P its MSFP calls, signed
as usual, and fetches P's media. P becomes callable by Q, and only by Q,
and can share with Q.

This is the technique of Overfin's gateway and backend
(Overfin's `docs/link-protocol.md`, sections 2 to 5): the side that can't
be reached dials out, authenticates, and then HTTP/2 runs the other way,
with the dialed side as the HTTP/2 client. What differs here: MSFP's keys
and signatures authenticate the connection instead of a pairing of
certificates, it rides the peer's existing HTTPS address instead of a
listener of its own, and it runs between two servers of different
operators.

Option 2 uses option 1's `inbound` member (1.1) and its rules for codes
and addresses (1.3, items 1 and 3), even if the rest of option 1 isn't
adopted.

#### 2.1 Negotiation

`transport` is a part (core section 10), version 1, announced in `parts`
in `hello`:

```json
{"state":"paired","core":[1],"parts":{"catalog":[1],"playback":[1],"media":[1],"transport":[1]},"inbound":false}
```

- Q lists `transport` to say it accepts reverse connections. P lists it
  to say it can open them.
- `transport` needs only the core. It is on between two servers when both
  list a common version (10.3).
- P opens a reverse connection to a peer when `transport` is on between
  them, the peer is `paired` and not suspended, and the peer's `inbound`
  isn't `false`.
- **The routing rule, for Q:** while a reverse connection from P is open,
  every call to P and every media fetch from P's stream root goes through
  it. While none is open, Q calls P directly if P's `inbound` isn't
  `false`, and otherwise treats P as unreachable (and, with option 1,
  follows 1.2 meanwhile).

Pairing itself doesn't use the connection: P redeems Q's code with an
ordinary `pair`, and learns that Q accepted by its `hello`s (1.3, item 2,
or 7.1, step 7). Only `paired` peers may open one.

#### 2.2 Opening the connection

1. **Connecting.** P connects over TCP to Q's stored address (port 443
   when it names none), under section 3.3's checks, and starts TLS with
   SNI set to Q's host name (none for an IP address). P checks Q's
   certificate as *trusted* or *named* (3.2), as for every call but `pair`
   and `hello`. P offers the ALPN name `http/1.1` only.
2. **The opening request.** P sends one HTTP/1.1 request:

   ```
   GET /api/v1/federation/transport HTTP/1.1
   Host: q.example.org
   Connection: Upgrade
   Upgrade: msfp-transport/1
   MSFP-Key: <P's current key>
   MSFP-Date: <now>
   MSFP-Nonce: <16 random bytes>
   MSFP-Signature: <P's signature>
   ```

   - The path is `transport` under Q's base path (11).
   - It is signed as section 6.2 says, with `<method>` `GET` and the body
     hash of the empty body. It has no body, no `Content-Type` and no
     `Content-Length`: core section 3's `Content-Type` rule and section
     8.1's `POST` don't apply to it. An upgrade without a body is the form
     servers and proxies know from WebSocket (RFC 6455); a body would leave
     each one to decide where it ends and the new protocol starts.
   - The `Upgrade` token's `1` is `transport`'s version.
3. **What Q checks.** Q checks the request as section 6.4 says, for its
   own host, then that P is `paired`, not suspended, and that `transport`
   is on between them. Refusals are the usual ones, and the connection
   stays HTTP/1.1 and is then closed:
   - an unsigned `404` for a failed check (6.4);
   - a signed `404` `not-found` for a forgotten, suspended or unpaired key
     (6.4, 6.6);
   - a signed `404` `not-supported` when `transport` is off (10.4);
   - a signed `429` `rate-limited` or `503` `server-busy`, with
     `retryAfter`, over a limit of 2.6.
4. **The answer.** Q answers `101 Switching Protocols`, with
   `Connection: Upgrade`, `Upgrade: msfp-transport/1`, and
   `MSFP-Signature`: Q's signature, with the key it uses toward P, of the
   answer message of section 6.3 with `<status>` `101`, `<media type>`
   `-`, and the body hash of the empty body. The 101 has no body.
5. **What P checks.** P checks the 101's signature against Q's current
   key, as for any answer (6.6). Unsigned or badly signed: P closes the
   connection and treats Q as unreachable. This is what tells P that Q's
   key holder took the connection, and not only whoever holds Q's TLS
   certificate.
6. **The switch.** The bytes after the 101's empty line are HTTP/2. P
   reads the 101's head byte by byte or keeps what it read past the empty
   line: those bytes belong to HTTP/2. The head is at most 16 KiB.

The whole opening (TCP, TLS, request, 101) takes at most 15 seconds,
core section 3's timeout for a call.

#### 2.3 HTTP/2 the other way

- **Roles.** Q is the HTTP/2 client, P the server, over the TLS
  connection P opened, with prior knowledge (RFC 9113 section 3.3): Q
  sends the client connection preface right after the 101, P its
  `SETTINGS`. No TLS inside: the connection's TLS covers it. Requests go
  one way only, Q to P. P's own calls to Q go as ordinary HTTPS calls, as
  today.
- **Settings.** Q sends `SETTINGS_ENABLE_PUSH` 0. P sets
  `SETTINGS_MAX_CONCURRENT_STREAMS` to at least 100, so that Q's media
  bounds (media section 2.4; Overfin: 64 fetches at once per peer) and its
  calls fit. Each side sets its own flow-control windows; each stream has
  its own window, so a response nobody reads (a paused player) holds only
  its own stream.
- **A request on the connection** is exactly the request Q would send
  over HTTPS: method, path (the base path or the stream root, as sent),
  headers, body, signed for P's host (6.2). `:authority` is P's host, with
  its port if its address has one; `:scheme` is `https`. P ignores both
  `:authority` and `:scheme` (it rebuilds the signed message from its own
  host, 6.2, never from the request), so a client library that writes
  `http` there, as some do for HTTP/2 without TLS of its own, still works.
- **What P serves on the connection:** its federation calls under its
  base path, and its stream root. Nothing else: its site, its panel, its
  media server get `404`. P checks every call as on a listener of its
  own (6.4), applies the same limits (8.3), and also refuses, with an
  unsigned `404`, a call whose `MSFP-Key` isn't Q's current key, or Q's
  previous key within the 10 minutes of 12.4: requests of other servers
  never travel on Q's connection.
- **Answers** are signed by P, and checked by Q, as today (6.6).
- **Cancellation.** A stream Q resets ends P's work for that request, as
  a closed HTTPS request would.

#### 2.4 The host the signatures name

Q signs every request for P's host, the host of P's address as Q stores
it (6.2), as it would over HTTPS. P checks against its own host (or two,
during a move, 13.1). P's address is never dialed, so it only needs to
be P's own: the recommended `.invalid` form of 1.3, item 3, or a name P's
operator holds. It must not be another server's address, which section
6.2's host exists to tell apart.

When P's address changes, Q stores it as 1.6 says, and signs for the new
host from then on; P accepts both hosts for the overlap of 13.1.

#### 2.5 Media URLs and tickets

- P's `play` answers name URLs under P's stream root,
  `<P's address><prefix>/api/v1/stream/` (media section 1), as today. Q
  checks them against that root, as today.
- Q fetches every URL under that root as a `GET` on the connection, with
  `:path` the URL's path as sent. Q never dials P's stream root. No name is
  looked up, so section 3.3's check doesn't apply to it; and P's
  certificate isn't checked, since P serves none: the connection was
  authenticated by P's signed opening, and its TLS by P's check of Q's
  certificate (2.2).
- Media sections 2 to 4 apply unchanged: methods, ranges and their
  checks, statuses, bounds, what is fetched.
- P serves a ticket on a connection only when it gave that ticket to the
  connection's peer: media section 4 already says a ticket works only for
  its pairing, and here P knows the pairing from the connection.
- A ticket isn't bound to a connection. It works on the next one, for as
  long as its playback is live (2.8).

#### 2.6 Limits and keepalive

- **One connection per peer.** Q keeps at most one reverse connection per
  peer key. The newest connection that passes 2.2 replaces the older: Q
  sends `GOAWAY` on the old one, sends no new request there, and closes it
  after its streams end, or after one minute. A peer whose connections
  keep replacing each other (more than a few an hour) may be two holders
  of one key: Q's panel should say so.
- **Opening rate.** An opening counts as a call under 8.3. Q also allows
  at most one opening per peer per 10 seconds, and answers a signed `429`
  `rate-limited` with `retryAfter` beyond it.
- **In all.** Q bounds the number of reverse connections it holds; beyond
  it, a signed `503` `server-busy` with `retryAfter`. The number is each
  implementation's (open point 6).
- **Header time.** Q reads the opening's head within the bounds it uses
  for any request (Overfin's gateway: 10 seconds to read request headers,
  `link-protocol.md` section 13).
- **Keepalive.** Each side sends an HTTP/2 `PING` when it has received
  nothing for 15 seconds, and closes the connection when a `PING` isn't
  answered within 10 seconds (the link's numbers, `link-protocol.md`
  section 5). That keeps the connection alive through NATs and through
  reverse proxies that close idle connections, and finds a dead one
  within about half a minute. Not measured against real routers for this
  proposal.
- **No length limit** on the connection, and none on a stream beyond
  media section 2.4's.
- **Proxies in front of Q** must let the upgraded connection live past
  their idle timeouts (the pings keep it busy), and must give it a
  connection of its own to Q, as they do for WebSocket.

#### 2.7 Reconnecting

P keeps a connection open to every peer of 2.1 at all times.

- It opens one at once when such a peer becomes `paired`, when a `hello`
  turns `transport` on, after a confirmed address change of the peer (to
  the new address), and after its own rotation took effect at the peer
  (signed with its new key; Q's newest-wins rule retires the old one).
- When the peer's pins change and P closes the connection (3.2, "When a
  peer's pins change"), it opens another at once.
- After a connection ends, or an opening fails without a signed refusal:
  it waits 1 second, then twice as long at each failure, up to 60
  seconds; back to 1 second after a connection that lasted over a
  minute. Each wait varies by a fifth either way, so private servers
  coming back after their peer restarted don't keep in step.
- An unsigned `404`: once more after a second, with a new nonce (6.5,
  "Retrying"), then as above.
- A signed `429` or `503`: it waits `retryAfter`.
- A signed `404` `not-found`: it stops, and sends a `hello`, which marks
  the peer `gone` if it was ended (9.2). It opens again only once the
  peer is `paired`.
- A signed `404` `not-supported`: it stops until a newer `hello` lists
  `transport`.

Q, while P is unconnected, treats P as unreachable (2.1), and the calls it
makes by itself wait as section 8.3 says for no answer. Then:

- `rotate` and `revoke` (12.4, 12.6) go first on each new connection, as
  "at each contact" already asks;
- a pairing Q ended while P was away is ended for P at P's next opening
  (the signed `404`) or `hello`;
- with option 1 too, Q's `hello` answers also carry `rotation` and
  `revocation` (1.4, 1.5), so they reach P even while the connection
  can't be opened.

#### 2.8 When the connection drops during a playback

**P owns, Q's viewer watches** (the case option 2 is for):

- The connection's streams end. Q cuts the media responses it was
  relaying to its viewer; the player asks again (with a `Range` for a
  file).
- A fetch that got no status line before the drop may be sent again, once,
  on the next connection, if one opens within 10 seconds. Media section
  2.3's rule ("doesn't retry a failed fetch by itself") gains this
  exception. Otherwise Q answers its viewer `503`, so that the player
  waits and tries again (core 8.4), and **not** `404`, which would end the
  playback.
- Q doesn't send `stop`. A `progress` that fails waits for its next turn
  (8.3).
- P keeps the playback live: a dropped connection is not one of the
  endings of playback section 6.3. P stops the work of the reset streams
  (2.3), not the playback. If nothing of the playback arrives for 2
  minutes, it expires as usual, and Q's next fetch gets `404`; the viewer
  starts again with `play`.

So an outage shorter than the player's buffer isn't seen, and one under 2
minutes costs a wait, if the player waits on `503`. Overfin's player does
since site v0.99.5: it holds its place and asks again every 3 seconds
while the server answers no answer, `502`, `503` or `504`
(`link-protocol.md` section 15, tested in Firefox with a 40-second
outage of its gateway).

**P watches, Q owns:** P's calls and fetches don't use the reverse
connection, so a drop changes nothing for them.

#### 2.9 Trust

The connection runs directly between the two paired servers: P's TLS
ends at Q's TLS endpoint (Q itself, or Q's own reverse proxy, which
already sees every call made to Q), and nothing else is in the path.

What holds, checked against the core's rules:

- **Calls are signed end to end**, as today: Q signs, P checks under
  section 6.4 with its own host; P signs answers, Q checks them under
  6.6. Nonces, dates and the host stop replays (14, "Replay"). Nothing
  between them can forge or replay a call.
- **The connection is bound to the two keys.** P authenticates Q's TLS
  endpoint by its certificate (*trusted* or *named*), and Q's key by the
  signed 101. Q authenticates P's key by the signed opening, whose nonce
  can't be replayed. Everything after the 101 travels inside that one TLS
  connection, so only P can have sent it, and only Q's endpoint can read
  it.
- **The media and the ticket have TLS only**, as today (media section 5).
  Today Q checks P's certificate before it fetches; here P checks Q's
  certificate, and the connection is P's by its signature. An observer on
  the path reads no ticket either way.
- **Q learns what a peer learns anyway**, with one change below: the
  titles, start positions, languages, coarsened capabilities and progress
  of Q's own viewers watching P's titles (playback section 6), which Q
  knows as the viewer's server in any case. Nothing about P's own people:
  their viewing of P's library never touches the connection, and their
  viewing of Q's titles goes by P's ordinary calls, as today.
- **P is less exposed** than a reachable server: only Q can call it, and
  only through the connection P chose to open. A compromised Q can do
  over it what a compromised peer can do anyway (14, "A compromised
  peer"): make calls within P's limits, fetch with the tickets it was
  given. It can't reach P's site, panel or media server (2.3), nor P's
  network: P serves its own routes and connects nowhere for Q.

What changes:

- **P's network address and its hours online.** Q sees P's public IP
  address and when P is up, continuously, for as long as the connection
  lasts. Today Q sees P's address at each of P's calls, and would see it
  for good if P were reachable; continuously is new. P's operator who
  wants it hidden connects out through a proxy or a VPN of their own
  (allowed by 3.3 when it makes the same checks).
- **That P can't be reached** (`inbound`).
- **Q holds a long-lived inbound connection per private peer**: a file
  descriptor, TLS and HTTP/2 state, and whatever its flow-control windows
  allow to be buffered. Only a paired peer gets one (the signature is
  checked before the switch); one per peer; openings rate-limited; a
  bound in all (2.6). Strangers still meet only the unsigned `404` and
  the limits by network address.
- **A stolen key of P's** is easier to use: its holder can open a
  connection as P from anywhere, and Q routes P's calls to the newest
  connection (2.6). Today the holder must also answer at P's address, or
  announce a new one, which section 14 ("A stolen key") already allows
  ("a stolen key can redirect a peer, until it is revoked"). The same
  class, a little easier; the real P and the thief replacing each other's
  connections shows on Q's panel (2.6), and revocation stops it.
- **Q's TLS key** (not its MSFP key), if stolen, lets its holder read
  what P sends Q on the connection, tickets to P's media included: the
  same as today, where the holder of P's TLS key could read Q's fetches
  from P. It can't make calls: it doesn't hold Q's MSFP key, and the 101
  must be signed.
- **One TCP connection** carries all of P's answers and media to Q, so a
  lost packet holds up every stream at once (head-of-line blocking).
  HTTP/2's per-stream windows keep a stalled stream from holding the
  others; TCP's loss recovery still does. Fine at home upload speeds; a
  QUIC version could come later.

## Alternatives considered

1. **Leave it to the operator: make the server reachable.** A forwarded
   port, UPnP or PCP on the router, or an IPv6 address with a firewall
   pinhole. No protocol cost, and MSFP works as it is. Fails behind a
   carrier-grade NAT, without access to the router, or where the provider
   blocks incoming connections; and asks an amateur for network work.
2. **Generic tunnels, left to the operator.** All stay allowed; none needs
   the specification.
   - **WireGuard, Tailscale** (or another mesh): P gets an address Q can
     reach inside the mesh (Tailscale's are in `100.64.0.0/10`, which
     section 3.3 allows by default), and MSFP runs as usual, with a
     self-signed certificate and pins. End to end; but both operators must
     join one network (or share a node), for each pairing, and a hosted
     coordination service learns who talks to whom. Good between friends
     who already share one, not as the general answer.
   - **Cloudflare Tunnel** and similar hosted tunnels: P gets a public
     name, simply. But the service terminates TLS, so it sees every call,
     every ticket and the media in the clear: it could fetch P's media with
     a ticket it read. Section 14's model ("trust is the key, nothing
     else") would then rest on a third party for media. And its terms of
     service on video through its proxy need checking (not checked for
     this proposal).
   - **frp, a reverse SSH tunnel, or a small proxy on a VPS** the operator
     runs: can pass TLS through untouched, so end to end. Needs a VPS and
     its setup; at that point the operator has a public gateway, the case
     this proposal leaves out.
3. **A relay in the protocol** (a third server both reach). If it
   terminates TLS it sees everything, as Cloudflare Tunnel does. If it
   only copies TLS bytes (as Overfin's gateway does for its backend's
   egress, `link-protocol.md` section 11), it sees who talks to whom, how
   much and when, and someone has to run it, keep it up, and be trusted
   with that. For P and a public Q it adds nothing: Q is already
   reachable, and option 2 makes Q its own relay. It matters only for two
   private servers, left out here (open point 7).
4. **NAT hole punching** (STUN and ICE, or QUIC through the NAT). Between
   P and a public Q there is no hole to punch: P can simply dial Q. Between
   two private servers, it needs a rendezvous, fails behind symmetric NATs
   and carrier-grade NATs, needs UDP, and needs a relay as a fallback,
   which brings back alternative 3. Much more machinery for the one case
   left out.
5. **A listener of its own, chosen by ALPN, with a preamble**, as
   Overfin's link does (`link-protocol.md` sections 2 and 3). Clean, and
   no HTTP/1.1 upgrade. But Q must see the TLS handshake to route by ALPN:
   a Q behind a reverse proxy that terminates TLS (the usual Jellyfin
   setup, and section 3's "Proxies" assumes one) would need TLS
   passthrough, or a second port. Overfin can do it because it holds both
   ends and its own TLS. Option 2's upgrade rides Q's existing address and
   proxy.
6. **WebSocket** (RFC 6455) instead of an `Upgrade` token of MSFP's own.
   More proxies and hosted front ends pass WebSocket than an unknown
   token. Costs a framing layer under HTTP/2, and WebSocket masks every
   frame from client to server: here the client is P, and what it sends
   is the media. Open point 4.
7. **Polling for calls** (Q queues its calls, P fetches them). Works for
   `hello`, `rotate` and `revoke` (option 1 does the useful part of it in
   `hello` answers), not for media, and adds latency to every `play`.
   Option 2 is the same idea done with a real connection.
8. **P's own calls through the same connection.** HTTP/2 carries
   requests one way per connection, so it would need a second HTTP/2
   session on it. P's calls work directly anyway. Not proposed.

## Cost

**Specification.**

- Option 1: about two pages. The `inbound` member in 9.1 and 9.2; a short
  section "A peer that can't be called" after 7.4 (the table of 1.2, the
  schedule of 1.3); the `rotation`, `knownKey` and `revocation` members in
  9.2, with a paragraph each in 12.4 and 12.6; a sentence in 13.2; a
  sentence in 5 (no codes) and the address recommendation in 5.2. Test
  vectors: a `hello` answer carrying `rotation`, signed with O, and P's
  `hello` with `knownKey`.
- Option 2: a new part, `transport.md`, of some five pages (sections 2.1
  to 2.9 above); the `transport` row in core section 3's table and in
  10.1; the `101` in 6.3 and 6.6; a sentence in media sections 1 and 2.3;
  a row or two in 8.3's table. Test vectors: an opening request and its
  signed 101.

**Overfin.**

- Option 1, as Q: skip every call to a peer that can't be called
  (`Accept` and `End` call `hello`, `SyncAll` reads paired peers' titles,
  in `internal/federation/service.go`); carry `rotation` and
  `revocation` in `hello` answers once rotation is built (version 1 isn't
  implemented yet); store P's address without confirming it. As P: an
  operator setting, `inbound: false` in `pair` and `hello`, the scheduled
  `hello`s whether or not the panel is open (today `CheckSoon` asks only
  while the panel is open), no codes, the `.invalid` address. Small.
- Option 2, as P: dial, upgrade, and serve HTTP/2 the other way over the
  connection. `internal/link` does nearly this already (Go's HTTP/2
  server on a connection the backend dialed, `h2.go`; reconnecting with
  jitter, `backend.go`). Serve only the federation and stream routes on
  it.
- Option 2, as Q: a single Overfin takes over the HTTP/1.1 connection of
  the opening (Go's `http.Hijacker`) and runs an HTTP/2 client over it; its
  calls and media fetches to such a peer go through that connection (a
  dialer per peer that returns it, where `internal/outbound` dials today).
  **Behind Overfin's gateway** this is more work: the gateway drops a
  visitor's `Upgrade` today (`link-protocol.md` section 15), and carries
  visitors to the backend over HTTP/2, where an HTTP/1.1 upgrade can't
  pass. The gateway would have to hand such connections to the backend
  through a new link mode, as egress does the other way (section 11). The
  biggest single cost of option 2 for Overfin.

**Plugin.** Read, not tried: the plugin builds no `play` and no media yet
(its README, read 2026-11-16).

- Option 1: the setting, the members, the scheduled `hello`s (it already
  reads paired peers' catalogs every 30 minutes, so it has a schedule),
  skipping calls. Small. Rotation pulls come with rotation.
- Option 2, as Q: ASP.NET Core exposes HTTP/1.1 upgrades
  (`IHttpUpgradeFeature`), and .NET's `SocketsHttpHandler` can run HTTP/2
  with prior knowledge over a stream a `ConnectCallback` returns (an
  `http` URI, version 2.0 exact); hence 2.3's rule that P ignores
  `:scheme`. One handler per reverse connection, its callback returning
  that one stream.
- Option 2, as P: the plugin would need an HTTP/2 **server** on a stream
  it dialed. Jellyfin hosts its own Kestrel; the plugin would run a small
  server of its own over the connection (Kestrel accepts custom
  transports), routed straight to its federation and stream code. The
  hardest part for a C# implementer, and the reason not to require
  `transport` of anyone.

## Compatibility

- **With version 0.** Every member of option 1 is optional; a version 0
  peer ignores `inbound` and keeps calling P, and its calls fail as they
  do today. A version 0 Q has no rotation or revocation to pull. A server
  that speaks core 1 should send and read `inbound` in core 0 `hello`s too,
  with peers that list core 1, as section 16.5 does for `address`.
  `transport` is not offered in core 0: its opening is signed under core 1.
- **With core 1.** Option 1 adds optional members whose absence keeps
  today's behaviour, so it needs no new core version
  ([README, Versioning](../spec/v1/README.md#versioning)). Option 2 is a
  new part, negotiated in `hello`; off, nothing changes. Neither changes
  keys, signatures, the code or pairing.
- **Servers that can be called** see no change unless a peer of theirs
  can't be.
- **Private servers behind a public gateway** of their own (Overfin's
  gateway and backend) are reachable at the gateway, and need neither
  option.
- **Existing pairings of a private server** keep working; its operator
  sets `inbound: false`, and its peers stop calling it from its next
  `hello`. No new pairing is needed.

## Open points

1. **The `hello` period** of 1.3 (5 minutes): it is the delay before a
   pairing Q ended, a rotation or a revocation reaches P. Shorter costs a
   call a peer a minute or so; longer delays revocation.
2. **Knowing that one can't be called.** This draft leaves it to the
   operator. A peer could help: a `hello` answer could say whether the
   peer's last call to the sender failed to connect. Not proposed: it
   would let a peer claim anything, and a failed connection has many
   causes.
3. **The address of a server that can't be called.** Whether section 5.2
   should reserve the `https://msfp-<26>.invalid` form, or only recommend
   it.
4. **The upgrade's form**: an `Upgrade` token of MSFP's own (this draft),
   WebSocket (alternative 6), or HTTP/2's extended `CONNECT` (RFC 8441),
   which works on a Q reached over HTTP/2 but is less supported. And `GET`
   (this draft) or `POST` for the opening. Worth trying behind Caddy,
   nginx and a hosted front end before deciding.
5. **Reverse connections from reachable peers.** This draft lets any
   `paired` peer open one, and Q uses it while it is open. Only peers that
   can't be called would be simpler; allowing all lets a server that is
   reachable only sometimes use it.
6. **The numbers**: 15 and 10 seconds for pings, 1 to 60 seconds between
   openings, one opening per 10 seconds, 100 streams, a bound on
   connections in all with no default.
7. **Two private servers.** Neither option pairs them. A relay, or hole
   punching with a relay behind it (alternatives 3 and 4), would; both are
   out of scope here.
8. **Reporting a pulled rotation's outcome.** 1.4 has P send `pending` or
   `refused`; Q could do without, at the price of a panel that can't tell
   why a peer hasn't moved.
9. **Overfin behind its gateway, as Q**: whether reverse connections end
   at the gateway, with the backend's signed calls and P's answers
   carried between them, or are handed whole to the backend through the
   link (Cost), which then holds the HTTP/2 client itself. The second
   keeps the gateway to copying bytes, as egress does; the first keeps
   one fewer link mode.

## Recommendation

> **Recommendation: adopt option 1 now; adopt option 2 as the optional
> part `transport` 1 later, once Overfin has built it.**
>
> Option 1 is small, and fixes what is broken today for a server that is
> already used this way: a peer's revocation never reaches it, a peer's
> rotation silently ends the pairing after 30 days, and its peers send
> calls to an address that may be a LAN address on their own network. It
> is also what option 2 builds on (`inbound`, no codes, the address), and
> its pulled rotation and revocation remain the fallback while a reverse
> connection is down.
>
> Option 2 is the only way, short of tunnels, for a private server to
> share, and it keeps MSFP's model: two servers, end-to-end signatures,
> no third party. But it is a real piece of work on both sides, the
> hardest of it on the private side in C#, and on Overfin's gateway. Let
> Overfin build it first, as both sides, try the upgrade behind the usual
> proxies (open point 4), and write `transport.md` from what was built;
> keep it optional, so that no implementation must carry it.
>
> Keep tunnels as the operator's choice, and leave relays and hole
> punching, which only two private servers would need, for later.
