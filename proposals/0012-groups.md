# Proposal 12: Groups

Status: Adopted (2026-11-20). Designed with the owner on 2026-11-20; every
choice marked "decided" below is the owner's; the details the proposal
added were confirmed the same day. Written into [spec/v0/groups.md](../spec/v0/groups.md)
and the core, catalog and playback on 2026-11-20, with proposal 13.
Ships with proposal 13 (version 0), in one release of every
implementation.
Touches: sections 1, 5, 6.5, 7, 9.1, 10.1, 12 and 14 of
[spec/v0/core.md](../spec/v0/core.md); sections 1 and 5 of
[catalog.md](../spec/v0/catalog.md); sections 5 and 6 of
[playback.md](../spec/v0/playback.md); adds a part, `groups`. Replaces
[proposal 10](0010-mesh.md).

A **group** is a set of servers whose operators chose each other, built
so that a few friends can federate together without pairing every pair
of servers by hand. A group has no central authority and no register: it
is a list of signed events that every member keeps and passes on. Nothing
about it is visible from outside: a server that isn't a member gets the
plain `404` of today.

There is no global discoverability, and none is planned (decided): a
server that wants to be known widely publishes itself on the internet,
as anyone can. A wider federation grows through groups: groups get
bigger, and servers in several groups bridge them without mixing them.

In the examples, A is the owner of the group "Family", B an admin, C and
D members, and N a server joining.

## Problem

- **Pairing is one pair at a time.** Core section 1: "Version 1 covers
  manual pairing only: two operators pair their servers by hand".
  Section 7.1: a code made by one operator, sent by hand, pasted by the
  other, and accepted after the fingerprints are compared by phone or
  another channel. Five friends who want to share with each other need
  ten pairings, twenty operator actions and ten fingerprint checks; ten
  friends need forty-five pairings.
- **Each pairing is set up apart.** Offers are per peer (catalog section
  1: "Each server sets its own offers, per peer") and limits per pairing
  (playback section 5). Five friends set five offers and five limits
  each, and redo it for each newcomer.
- **Proposal 10 (the mesh)** answered another question, how servers learn
  that others exist, and was deferred: announcements spread addresses
  along the pairing graph. The owner has since set aside global
  discoverability for good (2026-11-20). The need that stays is the
  friends' one.

What was checked for this proposal: the core, catalog and playback parts
of spec/v1, proposals 3, 9 and 10, and Go 1.26's `crypto/hpke`. Nothing
here was built or run.

## Proposal

### 1. Terms

- **Group**: a set of servers, its **members**, with a name, an owner,
  admins and settings. A server may be in any number of groups; groups
  never learn each other's members.
- **Owner**: the one member that names and removes admins, lifts bans,
  sets the group's name and settings, dissolves the group, names its
  heir, gives the group away or steps down; it also invites and bans, as
  admins do. It can't be banned. Exactly one at a time. The
  server that founds a group is its first owner; "creator" is not a role.
- **Admin**: a member that may invite and ban members. Any number.
- **Member**: any server in the group, the owner and admins included.
- **The list**: the group's signed events (section 3). Each member keeps
  its own copy and passes events on (section 6). The group's state
  (members, roles, settings, bans) is a function of the events: two
  copies holding the same events compute the same state.
- **Link**: a pairing between two servers (core section 7), whatever
  made it. Two servers are linked once, however many groups they share.
  Each server remembers, per link, its **sources**: a pairing by hand,
  and each group through which it was made or would have been.

### 2. Codes: one way in

Pairing with one server and joining a group start the same way (decided):

- **One kind of code**: the pairing code of core section 5, with a group
  attached or not.
- **One way to use it**: the other operator pastes it; its panel says
  what it leads to ("pair with A", or "join the group Family, invited by
  A").
- **One acceptance**: the code's maker accepts, after the fingerprint
  check, as in core section 7.1, step 6. Using a code is never enough on
  its own (decided).
- **Uses and validity**, for every code: a number of uses (1 by default)
  and an expiry (24 hours by default, at most 30 days), set by the maker
  (decided). The code doesn't carry the number of uses: the maker counts
  them, and refuses a `pair` once they are used up, as for an expired
  code. Each use is a separate `pair` from a separate key; core section
  9.1 is otherwise unchanged.

**The code's bytes** (replacing the table of core section 5.1):

| Bytes | Content |
|-------|---------|
| 32 | the maker's public key |
| 32 | the secret |
| 8 | the expiry: Unix seconds, unsigned, big-endian |
| 1 | `0`: no group; `1`: a group follows |
| 32 | the group's ID (section 3.1), only with `1` |
| 1 | the group name's length in bytes, 1 to 255, only with `1` |
| that many | the group's name, UTF-8, cleaned as core section 9.1 cleans names, only with `1` |
| 1 or more | the maker's address (core section 5.2) |

A reader refuses a flag byte other than `0` and `1`, a group name that
isn't valid UTF-8 or is longer than 80 code points after cleaning, and a
remainder too short for what the flag announces. The prefix is the one
of proposal 13 (`msfp-pair-0.`). The maximum length grows to 1,164
characters of base64url (873 bytes: 105 fixed, 256 for the group, 512 for
the address).

**After the maker's operator accepts** a server that used a group code
(it becomes `paired`, core section 7.1, step 6), the maker signs a
`joined` event for it (section 3.3), if the maker still holds the right
to invite and its daily cap allows; otherwise the pairing stands, and the
panel says the server couldn't be added to the group. A group code made
by an admin stops working when the admin loses its role or is banned.

The newcomer N is then paired with its inviter, and through that link
receives the list (section 6). Until then it is nothing to the group.

### 3. Events

#### 3.1 The envelope

An event travels as a JSON object:

| Member | Type | Content |
|--------|------|---------|
| `event` | string | base64url of the event's payload: a JSON object, I-JSON (core section 2.3), at most 4,096 bytes |
| `signature` | string | base64url of the Ed25519 signature (core section 2.1) of the bytes `msfp-group-event-1\n` followed by the payload's bytes |

The payload is signed as bytes and never rebuilt; every member keeps and
passes on the exact bytes. An event's **ID** is SHA-256 of its payload's
bytes. A **group's ID** is the ID of its `founded` event.

Every payload has:

| Member | Type | Content |
|--------|------|---------|
| `group` | string | the group's ID, base64url of 32 bytes; absent in `founded` only |
| `type` | string | one of section 3.3 |
| `signer` | string | the key that signed, base64url of 32 bytes |
| `member` | string | the signer's member ID: the key it joined with (section 3.4) |
| `seq` | integer | the signer's own count of its events in this group, from 1, without gaps |
| `date` | integer | Unix seconds when signed |

Owner events (section 3.3) also carry `ownerSeq`, an integer: the
group's count of owner events, from 1 (`founded`), whoever the owner is.
Admin events also carry `asOf`, the highest `ownerSeq` the admin had when
it signed.

#### 3.2 Keeping an event

A member keeps an event when:

1. the envelope and payload are well formed, the signature verifies
   under `signer`, and `signer` is `member`'s key in force at that `seq`:
   its member ID until its first `rotated` event, then each rotation's
   new key from the `seq` of that `rotated` event on (section 3.4);
2. its `group` is the group's ID;
3. its `seq` follows the last kept event of that member (an event whose
   predecessors are missing waits until they arrive);
4. its `date` is at most 5 minutes in the future of the member's clock;
5. its type's own rules hold (section 3.3), on the state computed from
   the events kept before it.

**Equivocation.** Two different payloads from one member with the same
`seq` are proof of misbehaviour: both are dropped, and every later event
of that member is refused, as if it were banned. The panel says so.
Owner events with the same `ownerSeq` keep the one with the lowest ID and
drop the other.

#### 3.3 The types

| Type | Signed by | Members | Rules |
|------|-----------|---------|-------|
| `founded` | the founder, who becomes owner | `name`, `settings`, `nonce` (16 random bytes, base64url), `ownerSeq` 1 | the first event; its ID is the group's |
| `profile` | the member itself | `name`, `encryptionKey` (X25519 public key, 32 bytes, base64url), `nextCommitment` (core section 12.5) | its latest `profile` is in force |
| `joined` | the owner or an admin (the inviter) | `newMember` (key), `name`, `asOf` for an admin | the inviter holds the right (section 3.5); within its daily cap; `newMember` isn't banned |
| `admin` | the owner | `target`, `on` (boolean), `lastSeq` (when `on` is false: the last of the target's events that counts), `ownerSeq` | `target` is a member |
| `heir` | the owner | `target` (absent: none), `ownerSeq` | `target` is a member |
| `owner` | the owner | `target`, `ownerSeq` | `target` is a member; it becomes owner from the next `ownerSeq` |
| `settings` | the owner | `name`, `settings`, `ownerSeq` | |
| `banned` | the owner, or an admin | `target`, `lastSeq` (the last of the target's events that counts), `reason` (optional, at most 280 code points), `asOf` for an admin | the target isn't the owner; for an admin, the target isn't an admin as of `asOf` nor now (section 3.5) |
| `unbanned` | the owner | `ban` (the `banned` event's ID), `ownerSeq` | |
| `left` | the member itself | | the owner leaves only after giving the group away |
| `dissolved` | the owner | `keepPairings` (boolean), `ownerSeq` | the last event; nothing after it is kept |
| `rotated` | the member, with its new key | `statement`: the rotation statement and both signatures of core section 12.2 | O is the member's current key; when the member's `profile` holds a commitment, SHA-256(N) matches it |
| `revoked` | the member | `statement`: the revocation statement and its signature of core section 12.6, `lastSeq` | events of that member after `lastSeq` don't count; with two, the lower `lastSeq` holds |

`settings` is an object: `waitDays` (integer, 0 to 30, default 3) and
`capPerDay` (integer, 1 to 100, default 5). `name` is cleaned as core
section 9.1 cleans names.

Stepping down is `owner` toward the successor, which the stepping-down
owner's server computes and names itself (decided): its heir if it named
one and the heir is still a member; otherwise the oldest admin (named at
the lowest `ownerSeq`); otherwise the oldest member (the lowest `joined`
`date`, then the lowest event ID). The successor is in the event, so no
copy has to compute it.

#### 3.4 Member IDs and keys

A member is known by the key it joined with, its **member ID** (the
founder's: the key of `founded`). Its current key follows its `rotated`
events. Events name members by member ID (`member`, `target`,
`newMember`), never by a later key. A member that pairs with another
member uses its current key, as in core section 12.

#### 3.5 Rights

The state is computed from the kept events. The rules, all deterministic:

- **The owner** at `ownerSeq` k is the founder, changed by each `owner`
  event before k. An owner event whose signer isn't the owner at its
  `ownerSeq` is refused.
- **An admin, as of `ownerSeq` k**, is a member named by an `admin` event
  with `on` true and an `ownerSeq` at most k, not removed by a later one
  at most k.
- **An admin event** (`joined`, `banned`) counts when its signer was an
  admin as of its `asOf`, and, if the owner later removed it, its `seq` is
  at most the removal's `lastSeq`. An `asOf` higher than any kept owner
  event waits until that owner event arrives.
- **A ban by an admin** counts only when its target is neither an admin as
  of its `asOf` nor an admin in the current state: the owner removes an
  admin's role before that admin can be banned (decided). The owner's
  bans count always, except on itself.
- **Conflicts**: the owner's event wins over an admin's (an `unbanned`
  lifts any ban, earlier or later in `seq`, that it names); between
  equals, a removal wins; anything else, the lowest event ID.
- **The daily cap**: an inviter's `joined` events are counted per UTC day
  of their `date`; beyond `capPerDay` in force, the extra ones (latest
  `date`, then highest ID) don't count.
- **Bans** take a member out of the group: its own later events don't
  count, it is no longer a member, and a `joined` naming it doesn't count
  until an `unbanned` lifts the ban.
- **A vanished owner** (its key lost, its server gone, without giving the
  group away) can't be replaced: nobody can tell for every member that it
  is gone (decided). Its powers freeze; admins keep inviting and banning,
  pairings go on.

#### 3.6 What each member keeps

The events, as received (bytes and signatures), and the state computed
from them. A member that left keeps nothing. Events of a member that left
or was banned stay in the list: they explain the state, and the list is
how later members check it.

### 4. Joining, step by step

1. **A code.** B, an admin of "Family", makes a code for the group
   (section 2), and sends it to N's operator.
2. **Pairing with the inviter.** N's operator pastes it; N calls `pair` on
   B (core section 9.1). B's operator accepts after the fingerprint check
   (core section 7.1, step 6): B and N are `paired`, by hand as today.
3. **Joined.** B signs `joined` for N and passes it on (section 6).
4. **The list.** N calls `group-sync` on B (section 6) and gets the list.
5. **Profile.** N signs its `profile`: its name, its encryption key and
   its next key commitment, and passes it to B.
6. **Requests.** N sends, through B, a **request** (section 5) to every
   member it isn't linked with: one message each, encrypted for that
   member. Members joining later send N theirs.
7. **Answers.** Each member answers for itself (section 4.1). A member
   that accepts makes the link (section 4.2). A member that refuses sends
   nothing.

#### 4.1 Answering

Each member chooses, per group (decided):

- **ask me** (the default): requests wait in its panel;
- **accept members**: its server accepts by itself, once the requester
  has been in the group for the group's `waitDays` (counted from its
  `joined` `date`). Before that, requests wait in the panel as with
  "ask me".

Accepting by hand is possible at any time. **A refusal is final** until
the refusing member changes its mind (it lifts it, or sends a request
itself) and private: nothing is sent; the requester sees no answer, the
others never know (decided). A request from a member the receiver has
blocked (section 7) is dropped without a trace.

#### 4.2 Making the link

When C accepts N's request:

- If N can be called (its request says so), C calls `group-pair` on N's
  address, from N's request.
- If N can't be called (core section 7.5), C sends N an **answer**
  (section 5) carrying C's address, and N calls `group-pair` on C.
- If neither can be called, they can't be linked, as today.

`group-pair` (section 8.3) proves that its caller is a member of the
group, and answers a request or an answer the receiver sent. Both
servers have consented: one by sending the request, the other by
accepting it. Both store each other as `paired` at once, and the caller
sends `hello` (core section 9.2) for versions and pins, as after an
operator's acceptance. A link that already exists (by hand, or through
another group) isn't made twice: the group is added to its sources.

### 5. Requests and answers: the mail

A **mail** is a message from one member to another, carried by the
members between them like the list, and readable only by its recipient.
It holds what pairing needs that the list mustn't show: an address. With
it, a member's address reaches only members it accepted (decided).

| Member | Type | Content |
|--------|------|---------|
| `mail` | string | base64url of the payload, a JSON object of at most 2,048 bytes |
| `signature` | string | the sender's Ed25519 signature of `msfp-group-mail-1\n` followed by the payload's bytes |

The payload:

| Member | Type | Content |
|--------|------|---------|
| `group` | string | the group's ID |
| `id` | string | 16 random bytes, base64url |
| `kind` | string | `request` or `answer` |
| `from` | string | the sender's member ID |
| `to` | string | the recipient's member ID |
| `answers` | string | for `answer`: the `id` of the request it answers |
| `expires` | integer | Unix seconds, at most 30 days after it was made |
| `sealed` | string | base64url of the HPKE encapsulated key followed by the ciphertext |

What `sealed` holds, once opened, is a JSON object: `address` (core
section 5.2), `name`, `nextCommitment`, and `inbound` (core section 7.5).

**Encryption**: HPKE (RFC 9180), mode base, with DHKEM(X25519,
HKDF-SHA256), HKDF-SHA256 and AES-128-GCM, to the recipient's
`encryptionKey` (its latest `profile`). The `info` is the bytes
`msfp-group-mail-1` followed by the group's ID and the mail's `id`
(decoded); the associated data is `from` and `to`, decoded, in that
order. Go has it in its standard library (`crypto/hpke`, Go 1.26); in
.NET it is built from BouncyCastle's X25519 and .NET's HKDF and AES-GCM,
and checked against RFC 9180's test vectors.

A member keeps a mail when its signature verifies under `from`'s current
key, `from` and `to` are members (not banned, not left), and it hasn't
expired; it passes it on until it expires; it keeps at most 1,000 mails
per group, dropping the soonest to expire first. Only `to` opens it.

### 6. Passing the list on

Events and mail travel along the links inside the group: each member
exchanges them with the members it is paired with in that group.

- **`group-push`** (section 8.2), at once, to every paired member of the
  group, when a member signs an event or a mail, or keeps one it didn't
  have.
- **`group-sync`** (section 8.1), every 10 minutes give or take a fifth,
  with one paired member of the group chosen at random; at once after a
  link is made; and, for a member that can't be called, as its only way
  to receive (it is never pushed to: core section 7.5), every 5 minutes.
- **The newcomer** is paired with its inviter from the start (section
  4, step 2): every member has at least one way in.
- **A ban or a dissolution** is passed on before anything else is done
  with it (section 7).

### 7. Leaving, blocking, banning, dissolving

- **Leaving**: the member signs `left` and passes it on. Its panel lists
  the links made through this group, nothing ticked; one click ticks them
  all (decided). A ticked link ends (core section 7.4), whatever its other
  sources. An unticked link loses this group as a source and keeps the
  others; one whose only source was this group becomes a pairing by hand,
  keeping what the group gave it, its offers and limits now its own
  (decided). The owner gives the group away before leaving.
- **Blocking** is private and covers everything (decided): the member ends
  its link with that server (core section 7.4), whatever its sources, and
  drops its requests in every group. Nobody else learns of it: a count
  others could check would name who blocked; one they couldn't check
  could be faked. Blocking offers to block the members it invited too, and
  theirs, nothing ticked, one click for all (decided).
- **Banning**: a `banned` event (section 3.3). Every member removes the
  group from the banned server's link sources; a link with no other
  source ends. The banned server learns it like any event, through any
  member still paired with it: its server removes the group, ends the
  links that had no other source, and its panel says it was banned, with
  the reason if one was given (decided). If that is missed, the members'
  `ended` give the same result.
- **Dissolving**: a `dissolved` event (the owner only). Each member passes
  it on first, then removes the group. With `keepPairings` false, links
  whose only source was the group end; with true, they become pairings by
  hand as when leaving. A member offline at the time learns it from a
  link's `ended`, or from its next `group-sync` (answered with the
  dissolution).

### 8. The calls

Part `groups`. Each call is signed and answered as core sections 6 and 8
say. A call about a group the receiver isn't in, or from a caller the
receiver doesn't hear for that group, gets the `404` of core section 6.4.

**Who is heard** (added to core section 6.5): on `group-sync` and
`group-push`, a peer in state `paired` that is a member of the group in
the receiver's copy; on `group-pair`, a member of the group in the
receiver's copy (not banned, not left, not blocked), with a request or
an answer it can match (section 8.3). Requests from members heard on
`group-pair` only go in a nonce memory of their own (at most 1,000
entries), and count against limits of their own (core section 8.3).

#### 8.1 group-sync

Request:

| Field | Type | Required | Content |
|-------|------|----------|---------|
| `group` | string | yes | the group's ID |
| `have` | object | yes | per member ID, the highest `seq` the caller keeps of it |
| `mail` | array of string | no | the `id`s of the mails the caller keeps, at most 1,000 |

Answer `200`: `events` (array of envelopes the caller lacks, in `seq`
order per member, at most 500), `mail` (array of mails the caller lacks),
`have` (the receiver's own, as in the request), `more` (boolean: call
again). The caller then pushes what the receiver lacks (`group-push`).

#### 8.2 group-push

Request: `group`, `events` (at most 500), `mail` (at most 100). Answer
`200` with an empty object. The receiver keeps what section 3.2 and
section 5 allow, and ignores the rest.

#### 8.3 group-pair

Request:

| Field | Type | Required | Content |
|-------|------|----------|---------|
| `group` | string | yes | the group's ID |
| `answers` | string | yes | the `id` of the request (when the caller accepted one) or of the answer (when the caller is the requester) |
| `address` | string | yes | the caller's address |
| `name` | string | no | the caller's name |
| `nextCommitment` | string | yes | as in `pair` (core section 9.1) |
| `inbound` | boolean | no | as in `pair` |

The receiver checks that the caller's key is the current key of a member
of the group, and that `answers` names a request it sent to that member,
or an answer that member sent it for a request of its own, not used
before. Then it stores the caller as `paired` (or adds the group to an
existing link's sources) and answers `200`, signed: `name`,
`nextCommitment`, `inbound`. Refusals: `404` as above; `409` when the
mail was already used.

### 9. Sharing and limits

- **Offers to the group** (decided): a member chooses, per group, the
  libraries it offers that group, as if the group were one server. Every
  member it is linked with through that group gets them. A link shares
  what each of its sources offers (their union). On the wire nothing
  changes: `libraries` answers what the caller is offered (catalog
  section 2). Catalog section 1's "Each server sets its own offers, per
  peer" becomes "per peer, or per group, a peer then getting what each of
  its sources offers".
- **Limits for the group as a whole** (decided): a member sets, per group,
  a pool of streams, transcodes and a bitrate cap it lends that group,
  shared by all the group's other members. A playback counts against the
  **first pool with room**: a pairing by hand's own limits first, then
  its groups' pools; it is refused only when all are full, and counts
  against exactly one (decided). The `limits` member of `libraries`
  (playback section 5) gives the most generous source's limits; playback
  section 6 says that a peer may be refused (`409`
  `stream-limit-reached`) before reaching them, its pool being shared.
  A server's own users are never refused for a peer.

### 10. What members see

Each member's name, fingerprint and role, whether they are linked, who
invited it and when it joined (decided). What a server offers stays
between linked servers; addresses too.

### 11. Changes to the core

- **Section 1**: the core covers pairing by hand and through groups; the
  part `groups` says how trust passes through a group.
- **Section 5.1**: the code's new bytes (section 2); uses and expiry set
  by the maker.
- **Section 6.5**: who is heard on the `groups` calls (section 8).
- **Section 7**: a pairing can also be made by `group-pair`; a link's
  sources; a refused group request sends nothing (unlike refusing a
  waiting pairing, which sends `ended`).
- **Section 10.1**: the part `groups`, needing the core.
- **Section 12**: rotation and revocation statements also travel in a
  group's list (`rotated`, `revoked`), so members not linked with a
  server follow its key.
- **Section 14**: in a group, the signatures of the inviter and of the
  owner stand in for the fingerprint check between members that pair
  through it; what a hacked member, admin or owner can do (below).

### 12. Security considerations

- **Trust passes through the inviter.** Members that pair through a group
  compare no fingerprints: each trusts that the inviter checked the
  newcomer's, and that the owner chose the admins. A group is as careful
  as its least careful admin.
- **A hacked member** sees names and keys, never an address it wasn't
  given, and gets no link without a yes.
- **A hacked admin** can invite (each newcomer still asks every member,
  and waits `waitDays` before any automatic acceptance) and ban members,
  until the owner lifts the bans and removes it. Its invitations are
  capped per day.
- **A hacked owner** can do anything the owner does, including dissolving
  the group. The members' exit: block it, leave, make a new group.
- **Forging rights** is impossible without the right key: every member
  checks every event against its own copy. Hiding events from a copy
  delays it, but the numbering shows the gap.
- **Equivocation** (two events with one `seq`) is detected by any member
  that sees both, and excludes the signer.
- **Mail** is readable only by its recipient; the members carrying it see
  who writes to whom in the group, and when.
- **Outside the group**, nothing changes: no call of the part is answered
  to a stranger, and the plain `404` stays.
- **Encryption** is new to MSFP; its use here goes to the external review
  core section 18, item 3 asks for, before the protocol is called stable.

### Amendment, 2026-11-20: joining when already paired

Found while building Overfin's panel: a server already paired with a
group code's maker can't use the code, since `pair` answers `409` to a
known key. It now calls `group-join` on the maker through their pairing
(groups section 8.4): the code's secret hash and a proof bound to its key
(label `msfp-group-join-1\n`). The code's use counts, the maker's
operator accepts as for any code, and the list follows through the
pairing. Chosen by the owner over an "add to the group" action for paired
servers, which would have been a second way in.

### Amendment, 2026-11-20: one state from the same events

Found by msfp-dotnet's port: both engines applied events in the order
they arrived, so two copies could disagree. A member now keeps every
well-formed, signed event of the group and passes it on; the state is a
replay of all of them in one order (section 3.5: ready events, those that
can count first, the lowest ID first, cuts applied from the start). The
same events give the same state, whatever order they came in. The
vectors judge their events as one set.

## Alternatives considered

1. **Proposal 10, the mesh**: servers announce themselves along
   pairings, or to anyone. Set aside: the owner's goal is friends
   federating, not finding strangers, and announcements spread addresses.
2. **A hosted network**: a host program that admits members and carries
   their messages. Dropped by the owner (2026-11-20): it is a central
   authority.
3. **A shared group key** that every member holds: any member could admit
   anyone, a leaked key lets strangers in, and removing someone means a
   new key for everyone.
4. **Any member invites**: chosen first, then replaced by owner and
   admins (decided): an owner that wants everyone to invite makes everyone
   admin.
5. **Votes** to remove an admin or a member: they need every concerned
   operator in their panel, and are unreliable (owner). Replaced by the
   owner's role.
6. **An officer** acting while the owner is down: "down" can't be decided
   for every member without an authority. Dropped.
7. **Shared block counts** ("blocked by 2 members"): a checkable count
   names who blocked; an uncheckable one can be faked to get innocent
   servers blocked. Dropped (decided).
8. **Invitation links** instead of codes: a link to the inviter's server
   would expose it to strangers. Codes kept (decided).
9. **The join event as the request**, carrying the newcomer's address:
   simpler (no mail, no encryption), but every member would learn every
   member's address. Kept the mail (decided).

## Cost

- **Specification**: the part `groups` (about the length of
  `playback`), the core sections of section 11, a line each in catalog
  and playback, vectors (events, the code with a group, the mail with
  RFC 9180's suite), and conformance checks (a third server for the
  suite).
- **msfp-go and msfp-dotnet**: the part: events and state, mail, the
  three calls, the code's new bytes; HPKE (Go's standard library; .NET
  from primitives).
- **Overfin and the Jellyfin plugin**: groups in the panel (create, codes,
  members, requests, offers and pools per group, leave, block, ban,
  dissolve), link sources, pools in playback. Overfin also sends codes by
  email, when its email is set up (decided; not part of the protocol).
- **Testing**: at least three servers.

## Compatibility

None needed: no server runs MSFP outside its implementers' own, and this
ships with proposal 13 (version 0), every implementation at once.

## Open points

1. **Large groups.** The design was thought out for friends. With hundreds
   of members: the list's size over years (a snapshot to start from,
   signed by the owner?), the mail per newcomer (one per member), and
   whether pools, `waitDays` and the cap still make sense. To check when
   building.
2. **The limits on sizes** (4,096-byte events, 2,048-byte mail, 1,000
   mails, 500 events a call) are first guesses, to check against the
   first implementation.
3. **Catching up after a long absence**: a member offline for weeks
   misses expired mail. Requests to it are sent again by the newcomer
   when its own copy shows them unanswered and expired?
