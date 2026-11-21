# Proposal 8: Changing a server's address

Status: Adopted (2026-11-16); open points still open.
Touches: sections 5.2, 6.2, 7.2 and 9.2 of [spec/history/test-draft.md](../spec/history/test-draft.md).

## Problem

A peer stores a server's address once: from the code, or from the pair
request (section 7.2). Version 0 has no way to change it. And the address
is not only where to call: section 6.2 puts the receiver's host in every
signed request, and section 10.1 builds media URLs on it. So when a
server's address changes (a new domain name, a new port, a move from
`http` to `https`):

- its peers keep calling the old address, and fail;
- requests its peers sign name the old host; the server rebuilds the
  message from its own, new host (section 6.2), so they fail even if they
  reach it;
- the only fix is a new pairing, with a new code and a fingerprint call,
  for every peer.

This is the same kind of gap as key rotation (proposal 3): something
fixed at pairing that real servers need to change. It also blocks
proposal 7: moving existing pairings from `http` to `https` is an address
change.

Today, an operator who changes the address in Overfin's configuration
has no warning that every pairing will break.

## Proposal

### Announcing a new address

`hello` requests and answers gain an optional member:

| Field | Type | Content |
|-------|------|---------|
| `address` | string | the sender's address now (section 5.2) |

The `hello` is signed with the sender's key, which is the identity, so
the address it names is as trustworthy as anything else the peer says.

What a receiver does with a signed `hello` whose `address` differs from
the one it stores for that peer:

1. It checks the address against section 5.2 (or proposal 1's C6, and
   proposal 7 if taken).
2. It calls `hello` at the **new** address, signed for the new host. If
   the answer verifies under the peer's key, it stores the new address.
   This proves the key holder actually answers there.
3. If that `hello` fails, it keeps the old address and tries again
   later (at most once an hour), and shows its operator a warning after a
   day of failures.
4. It never moves to an address that is only in an unsigned message, or
   in an answer it couldn't verify.

When the stored address changes, pins learnt from the old address are
dropped and learnt again from the new one's `hello` (section 3.1).
Playbacks in progress keep their old URLs until they end.

### The server that moves

A server whose address changes from A1 to A2:

1. accepts requests whose signed host is A1's host or A2's host, for
   30 days, or until every peer has moved (it knows from the `hello`s
   that reach it at A2 with A2's host);
2. sends `hello` with `address` A2 to every peer, at once and then at
   each contact, from A2;
3. names, in `hello` answers given on A1, the address A2 too, so a peer
   that calls first also learns;
4. after the 30 days, accepts A2's host only.

Section 6.2's rule becomes: the receiver rebuilds the message from one
of its own current hosts, never from the `Host` header.

Accepting two hosts for a while doesn't weaken section 6.2's goal: a
request signed for one server still fails at every other server, since
no other server has A1 or A2 as its own.

### What the panel shows

An implementation should tell its operator, when the configured address
changes, that peers will be told and how many have moved, and warn when
a peer hasn't moved after some days.

## Alternatives considered

1. **Re-pair** (version 0). No protocol cost; a phone call per pairing
   per move.
2. **A separate `move` call.** Clearer in logs, but `hello` already
   runs between all peers, in all states, and already carries
   per-server facts (state, pins). One member is less than one call.
3. **Trust the new address without the confirming `hello`.** Saves one
   call. But a stolen key could then redirect a peer to any address
   without answering there. The confirming call makes the key holder
   prove it serves the new address.
4. **Drop the host from the signed message.** Removes the need for the
   double-host period. But the host is what stops a request signed for
   one server from being replayed to another (section 14, "Replay"). Kept.

## Cost

**Specification.** About a page: one member in 9.2, a short section after
7.4, a sentence in 6.2, a sentence in 3.1 about pins. A test vector of a
`hello` with `address`.

**Overfin.**

- `hello` handling: the new member, the confirming call, retries and the
  warning; about 80 lines in `internal/federation/service.go`.
- The `Verifier`'s `Host` becomes a list (one or two hosts) for the
  overlap; Overfin rebuilds Verifiers on settings changes already, which
  makes this simple.
- Remembering the former address and the overlap's end, in the store.
- The panel's warning.

**Plugin.** The same pieces: the `hello` member, the confirming call,
two hosts in its request check during the overlap.

## Compatibility

- `address` is an optional member: a version 0 peer ignores it and keeps
  calling the old address. For such peers, the moving server can keep
  accepting the old host longer, at its operator's choice, or the
  operators pair again.
- No change for servers that never move.

## Open points

1. The 30-day overlap, the same question as in proposal 3. Both could
   share one setting.
2. Whether a server may announce more than one address (for example a
   public name and a LAN address). Not proposed: one address per server
   keeps the signed host simple.
3. If proposal 4's discovery document is taken, whether a change of its
   `base` path is announced the same way.
