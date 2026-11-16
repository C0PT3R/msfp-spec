# MSFP: Media Server Federation Protocol

MSFP lets media servers share their libraries with each other: one
server's people browse and play titles another server holds, through
their own server.

**Version 0 is a draft and may change.** It covers manual pairing only:
two operators pair their servers by hand, and each trusts only the servers
it paired with. Larger federations are planned, not specified.

- [The version 0 specification](spec/v0.md)
- [Test vectors](vectors/v0.json): signed sample requests and answers, for
  an implementation's tests

## Implementations

- [Overfin](https://github.com/Overfin/server), the first one. Version 0
  describes what it does.

Questions and gaps in the specification are welcome as issues.

## License

- The specification and this README: [CC BY 4.0](LICENSE). Copy, translate
  or adapt them, with credit. Implementing the protocol needs no permission
  and carries no condition.
- The test vectors (`vectors/`): [CC0 1.0](vectors/LICENSE), no conditions.
  Copy them into any test suite.
