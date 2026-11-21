# Proposal 13: Version 0, until MSFP is stable

Status: Decided in principle by the owner (2026-11-20): "MSFP v1 should
not exist yet… we should still be on v0". To be done with the next
protocol changes (proposal 12), every implementation released at once.
Touches: every document of spec/v1, which moves to spec/v0; the vectors;
the conformance suite; [spec/v0.md](../spec/v0.md), which moves to
history.

## Problem

Version 1 says "stable" to anyone reading it, and MSFP isn't: it changes
as its first implementations need (the owner, 2026-11-19), and no server
outside its implementers' runs it. The number should say "draft".

## Proposal

- **The current protocol becomes version 0**: the core and every part
  (`catalog`, `playback`, `media`, `video`, `music`, and `groups` from
  proposal 12) are version 0, on the wire too: `hello` announces
  `"core":[0]` and `0` for each part (core section 10.2).
- **Version 0 means draft**: anything may change, with no promise of
  compatibility between two drafts. Version 1 will be the first stable
  version, after the external review (core section 18, item 3).
- **Labels and prefixes follow**: `msfp-pair-0.` for codes, `msfp-0 …`
  for the labels that carry the core's number today (`msfp-1 pairing\n`
  and the request and answer messages of core section 6); the statement
  labels (`msfp-key-rotation-1`, `msfp-key-revocation-1`,
  `msfp-group-event-1`, `msfp-group-mail-1`) number their own format and
  stay.
- **The test draft of November 2026** (spec/v0.md, "superseded, not to be
  implemented") moves to `spec/history/` as "the test draft of November
  2026", so that two different texts don't both claim to be version 0.
- **spec/v1/ becomes spec/v0/**, with its vectors (vectors/v1 to
  vectors/v0) and the conformance suite's expectations.

## Cost

The spec, the vectors and the conformance suite; msfp-go, msfp-dotnet,
Overfin and the Jellyfin plugin (the numbers they announce and accept,
the labels, the code prefix). Mostly mechanical.

## Compatibility

A server of version 0 and one of today's version 1 have no common core:
they can't talk (core section 10.3). Every implementation is released at
once, and every server running them (zecopter and stream.zecopter) is
updated together.

## Open points

None.
