#!/usr/bin/env python3
"""Checks an MSFP version 0 server against spec/v0.md, as a peer would.

    python3 conformance/run.py --code '<pairing code from the target>' \
        --address http://<this machine, as the target reaches it>:8000 --listen 0.0.0.0:8000

See conformance/README.md."""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from msfpconf import __version__  # noqa: E402
from msfpconf.checks import Suite  # noqa: E402
from msfpconf.report import Report  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="MSFP version 0 conformance suite (spec/v0.md as corrected on 2026-11-16)")
    ap.add_argument("--target", help="the target's address, http(s)://host[:port]; taken from --code when given")
    ap.add_argument("--code", help="a pairing code the target's operator made (it is used: one code per run)")
    ap.add_argument("--address", help="this suite's own address, as the target reaches it (it is put in the pair request)")
    ap.add_argument("--listen", default="0.0.0.0:8000", help="where this suite listens for the target's calls (default 0.0.0.0:8000)")
    ap.add_argument("--connect", help="connect to this host:port instead of the target address's (requests stay signed for the address)")
    ap.add_argument("--key", help="a file holding this peer's Ed25519 seed (made on first use); default: a new key each run")
    ap.add_argument("--accept-timeout", type=int, default=600, help="seconds to wait for the target's operator to accept (default 600)")
    ap.add_argument("--reader-timeout", type=int, default=0,
                    help="seconds to wait for the target to read this peer's library (0: skip those checks)")
    ap.add_argument("--watch-changes", type=int, default=0,
                    help="seconds to wait for a change made by hand on the target (0: skip that check)")
    ap.add_argument("--load", action="store_true", help="also send a burst of calls to check the rate limits (section 8.3)")
    ap.add_argument("--load-count", type=int, default=1000, help="how many calls the burst sends (default 1000)")
    ap.add_argument("--end", action="store_true", help="end the pairing at the end (section 7.4): the target forgets this peer")
    ap.add_argument("--json", help="also write the results to this file")
    ap.add_argument("-v", "--verbose", action="store_true", help="show the detail of passing checks too")
    a = ap.parse_args()
    if not a.target and not a.code:
        ap.error("give --target, --code, or both")

    report = Report(verbose=a.verbose)
    report.note("MSFP v0 conformance suite %s, %s" % (__version__, time.strftime("%Y-%m-%d %H:%M:%S %Z")))
    suite = Suite(a, report)
    try:
        suite.run()
    except KeyboardInterrupt:
        report.note("interrupted")
    n, must_fail = report.summary()
    if a.json:
        report.write_json(a.json, {"version": __version__, "target": suite.target, "time": time.time()})
    return 1 if n["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
