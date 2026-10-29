#!/usr/bin/env python3
"""Date the instruments whose details changed.

Fingerprints each instrument's row in data/instruments.js plus its facts, versions and
sources in data/pages.js. When a fingerprint differs from the last run, the instrument's
"reviewed" date becomes today. The first run only records fingerprints.
Standard library only; runs before monitor/fetch.py in the daily workflow.
"""
import datetime as dt
import hashlib
import json
import pathlib

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
INSTRUMENTS, FINGERPRINTS = DATA / "instruments.js", DATA / "fingerprints.json"
IGNORED = ("reviewed", "kw", "only")  # matching hints are not details a reader sees


def load_js(path, var):
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"window.{var}=", 1)[1].rstrip().rstrip(";"))


def fingerprint(inst, page):
    tracked = {k: v for k, v in inst.items() if k not in IGNORED}
    tracked.update({k: page.get(k) for k in ("f", "v", "s")})
    return hashlib.sha256(json.dumps(tracked, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def main(today=None):
    today = (today or dt.date.today()).isoformat()
    insts, pages = load_js(INSTRUMENTS, "INSTRUMENTS"), load_js(DATA / "pages.js", "PAGES")
    old = json.loads(FINGERPRINTS.read_text()) if FINGERPRINTS.exists() else None
    new = {i["id"]: fingerprint(i, pages.get(i["id"], {})) for i in insts}
    changed = {k for k, v in new.items() if old is not None and old.get(k) != v}

    if changed:  # rewrite only the changed rows, keeping one instrument per line
        lines = INSTRUMENTS.read_text(encoding="utf-8").split("\n")
        for n, line in enumerate(lines):
            if not line.startswith('{"id"'):
                continue
            comma = line.endswith(",")
            row = json.loads(line[:-1] if comma else line)
            if row["id"] in changed:
                row["reviewed"] = today
                lines[n] = json.dumps(row, separators=(",", ":"), ensure_ascii=False) + ("," if comma else "")
        INSTRUMENTS.write_text("\n".join(lines), encoding="utf-8")

    FINGERPRINTS.write_text(json.dumps(new, indent=0, sort_keys=True) + "\n")
    print(f"{len(changed)} instrument(s) changed: {', '.join(sorted(changed)) or 'none'}"
          if old is not None else f"Recorded fingerprints for {len(new)} instruments.")


if __name__ == "__main__":
    main()
