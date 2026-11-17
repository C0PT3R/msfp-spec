"""Results: each check has an ID, the spec section it tests, a level
(MUST or SHOULD, as the section says), and a result."""

import json
import sys

PASS, FAIL, SKIP = "pass", "fail", "skip"


class Result:
    def __init__(self, cid, section, title, level, status, detail=""):
        self.id, self.section, self.title, self.level = cid, section, title, level
        self.status, self.detail = status, detail

    def as_dict(self):
        return {"id": self.id, "section": self.section, "title": self.title, "level": self.level,
                "result": self.status, "detail": self.detail}


class Report:
    def __init__(self, out=sys.stdout, verbose=False):
        self.results = []
        self.out = out
        self.verbose = verbose
        self._tty = hasattr(out, "isatty") and out.isatty()

    def add(self, r):
        self.results.append(r)
        mark = {PASS: "PASS", FAIL: "FAIL", SKIP: "SKIP"}[r.status]
        if self._tty:
            mark = {PASS: "\033[32mPASS\033[0m", FAIL: "\033[31mFAIL\033[0m", SKIP: "\033[33mSKIP\033[0m"}[r.status]
        line = "%s  %-6s %-9s %s" % (mark, r.id, "§" + r.section, r.title)
        if r.level == "SHOULD":
            line += " (should)"
        if r.detail and (r.status != PASS or self.verbose):
            line += "\n" + "\n".join("        " + x for x in r.detail.splitlines())
        print(line, file=self.out, flush=True)

    def note(self, text):
        print("-- " + text, file=self.out, flush=True)

    def summary(self):
        n = {s: sum(1 for r in self.results if r.status == s) for s in (PASS, FAIL, SKIP)}
        must_fail = sum(1 for r in self.results if r.status == FAIL and r.level == "MUST")
        print("\n%d passed, %d failed (%d of them MUST), %d skipped" % (n[PASS], n[FAIL], must_fail, n[SKIP]),
              file=self.out, flush=True)
        return n, must_fail

    def write_json(self, path, meta):
        with open(path, "w") as f:
            json.dump({"meta": meta, "results": [r.as_dict() for r in self.results]}, f, indent=1)
