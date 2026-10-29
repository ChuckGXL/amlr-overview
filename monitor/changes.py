#!/usr/bin/env python3
"""Apply status changes automatically and keep a log of every change.

1. Applies the status changes the dates and sources settle:
   - a consultation whose closing date has passed: Consultation closed;
   - an AMLA consultation linked to the instrument: In consultation;
   - an AMLA or EBA final report, or a submission to the Commission: Final, awaiting publication;
   - a delegated or implementing regulation on EUR-Lex: Published.
   A status only moves forward, and only links by article reference or keyword count (never a
   "similar title"). Each change ticks the matching step in the version history and adds the document
   as a source.
2. Compares every instrument with data/snapshot.json, its state at the last run, and logs what changed
   in data/changes.js: the changes from step 1 as automatic, anything else (a push to the data files)
   as edited. A changed instrument's "reviewed" date becomes today.
Standard library only; runs after monitor/fetch.py in the daily workflow.
"""
import datetime as dt
import hashlib
import json
import pathlib
import re

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
INSTRUMENTS, PAGES, DIGEST = DATA / "instruments.js", DATA / "pages.js", DATA / "digest.js"
SNAPSHOT, CHANGES = DATA / "snapshot.json", DATA / "changes.js"
IGNORED = ("reviewed", "kw", "only")  # matching hints are not details a reader sees
RANK = {"ann": 0, "eba": 0, "consult": 1, "closed": 2, "final": 3, "pub": 4}
FIELD = {"name": "Name", "short": "Short name", "art": "Articles", "arts": "Article keys", "by": "Issued by",
         "type": "Type", "last": "Last step", "lastNote": "Last step note"}
KEEP = 1000  # log entries kept


def load_js(path, var):
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"window.{var}=", 1)[1].rstrip().rstrip(";"))


def long_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d:%B} {d.day}, {d.year}"  # the format used in data/pages.js


def parse_date(text):
    try:
        return dt.datetime.strptime(text or "", "%B %d, %Y").date()
    except ValueError:
        return None


def fact(page, key):
    return next((f[1] for f in page.get("f", []) if f[0] == key), None)


# ---------- 1. automatic status changes ----------

def proves(item):
    """The status a linked digest item proves, the step it completes and why; or None."""
    t, src = (item["title"] + " " + item["summary"]).lower(), item["source"]
    if src == "eurlex" and re.search(r"delegated regulation|implementing regulation", t):
        return "pub", ["Published in the Official Journal"], "Published in the Official Journal (EUR-Lex)."
    if src == "amla-consultations":
        return "consult", ["Consultation paper"], "AMLA opened a public consultation."
    if (src.startswith("amla") or src == "eba") and re.search(r"final report|finalis|submitted to the (european )?commission", t):
        steps = ["Final draft"] + (["Submitted to the Commission"] if "submitted" in t else [])
        return "final", steps, "The final text was published" + (" and sent to the Commission." if "submitted" in t else ".")
    return None


def tick(page, stage, iso, label, link):
    """Mark a version-history step done; a new consultation gets its own step if the old one is done."""
    v = page.setdefault("v", [])
    step = next((x for x in v if x[1] == stage and not x[0]), None)
    if step:
        step[:] = [1, stage, long_date(iso), label, link]
    elif stage == "Consultation paper":
        at = next((n for n, x in enumerate(v) if not x[0]), len(v))
        v.insert(at, [1, stage, long_date(iso), label, link])


def apply(insts, pages, items, today):
    """Move statuses forward; returns {instrument id: (why, link)}."""
    applied = {}
    for inst in insts:
        cc = parse_date(fact(pages.get(inst["id"], {}), "Consultation closed"))
        if inst["status"] == "consult" and cc and cc < today:
            inst["status"] = "closed"
            applied[inst["id"]] = (f"The consultation closed on {long_date(cc.isoformat())}.", "")
    by_id = {i["id"]: i for i in insts}
    for item in sorted(items, key=lambda i: i["date"] or i["found"]):  # oldest first, so the latest step wins
        found = proves(item)
        for m in item["matches"] if found else []:
            inst = by_id.get(m["id"])
            if not inst or m["how"].startswith("similar") or RANK[found[0]] <= RANK[inst["status"]]:
                continue
            to, steps, why = found
            iso, page = item["date"] or item["found"], pages.setdefault(inst["id"], {"f": [], "v": [], "s": []})
            if to == "consult":  # an earlier consultation's closing date would close this one at once
                page["f"] = [f for f in page.get("f", []) if f[0] != "Consultation closed"]
            for stage in steps:
                tick(page, stage, iso, item["title"], item["link"])
            if not any(s[0] == item["link"] for s in page.setdefault("s", [])):
                page["s"].insert(0, [item["link"], item["title"]])
            inst["status"] = to
            applied[inst["id"]] = (why, item["link"])
    return applied


# ---------- 2. change log ----------

def snap(inst, page):
    s = {k: v for k, v in inst.items() if k not in IGNORED}
    s.update({k: page.get(k, []) for k in ("f", "v", "s")})
    return json.loads(json.dumps(s))  # a copy: step 1 changes the pages in place


def diff(a, b):
    """What changed between two snapshots of one instrument, as {field, old, new} rows for the page."""
    if not a:
        return [{"field": "Added", "old": "", "new": b["name"]}]
    if not b:
        return [{"field": "Removed", "old": a["name"], "new": ""}]
    out = []
    if a.get("status") != b.get("status"):
        out.append({"field": "status", "old": a.get("status", ""), "new": b.get("status", "")})
    fa, fb = dict(a.get("f", [])), dict(b.get("f", []))
    for k in list(fa) + [k for k in fb if k not in fa]:
        if fa.get(k) != fb.get(k):
            out.append({"field": k, "old": fa.get(k, ""), "new": fb.get(k, "")})
    va = {(x[1], x[2]) for x in a.get("v", []) if x[0]}
    vb = {(x[1], x[2]) for x in b.get("v", []) if x[0]}
    out += [{"field": "Step", "old": "", "new": f"{s}, {d}"} for s, d in sorted(vb - va)]
    out += [{"field": "Step", "old": f"{s}, {d}", "new": ""} for s, d in sorted(va - vb)]
    if va == vb and a.get("v") != b.get("v"):
        out.append({"field": "Version history", "old": "", "new": "details updated"})
    sa, sb = dict(map(tuple, a.get("s", []))), dict(map(tuple, b.get("s", [])))
    out += [{"field": "Source", "old": "", "new": sb[u]} for u in sb if u not in sa]
    out += [{"field": "Source", "old": sa[u], "new": ""} for u in sa if u not in sb]
    for k in [k for k in b if k not in ("status", "f", "v", "s")] + [k for k in a if k not in b]:
        if a.get(k) != b.get(k):
            val = lambda x: ", ".join(x) if isinstance(x, list) else str(x or "")
            out.append({"field": FIELD.get(k, k), "old": val(a.get(k)), "new": val(b.get(k))})
    return out


def write_rows(insts, ids):
    """Rewrite only the given instruments' lines, keeping one instrument per line."""
    by_id = {i["id"]: i for i in insts}
    lines = INSTRUMENTS.read_text(encoding="utf-8").split("\n")
    for n, line in enumerate(lines):
        if not line.startswith('{"id"'):
            continue
        comma = line.endswith(",")
        row = json.loads(line[:-1] if comma else line)
        if row["id"] in ids:
            lines[n] = json.dumps(by_id[row["id"]], separators=(",", ":"), ensure_ascii=False) + ("," if comma else "")
    INSTRUMENTS.write_text("\n".join(lines), encoding="utf-8")


def main(today=None):
    today = today or dt.date.today()
    insts, pages = load_js(INSTRUMENTS, "INSTRUMENTS"), load_js(PAGES, "PAGES")
    items = load_js(DIGEST, "DIGEST")["items"] if DIGEST.exists() else []
    before = {i["id"]: snap(i, pages.get(i["id"], {})) for i in insts}
    old = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else before  # first run: log only step 1

    applied = apply(insts, pages, items, today)
    if applied:
        header = PAGES.read_text(encoding="utf-8").split("window.PAGES=", 1)[0]
        PAGES.write_text(header + "window.PAGES=" + json.dumps(pages, separators=(",", ":"), ensure_ascii=False) + ";\n",
                         encoding="utf-8")

    new = {i["id"]: snap(i, pages.get(i["id"], {})) for i in insts}
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    log = load_js(CHANGES, "CHANGES") if CHANGES.exists() else []
    added = []
    for iid in [i["id"] for i in insts] + [k for k in old if k not in new]:
        rows = diff(old.get(iid), new.get(iid))
        if not rows:
            continue
        why, link = applied.get(iid, ("", ""))
        entry = {"at": now, "date": today.isoformat(), "inst": iid, "short": (new.get(iid) or old[iid]).get("short", iid),
                 "how": "auto" if iid in applied else "edit", "why": why, "link": link, "changes": rows}
        entry = {"id": hashlib.sha1(json.dumps(entry, sort_keys=True).encode()).hexdigest()[:12], **entry}
        added.append(entry)

    changed = {e["inst"] for e in added if e["inst"] in new}
    for inst in insts:
        if inst["id"] in changed:
            inst["reviewed"] = today.isoformat()
    if changed:
        write_rows(insts, changed)
    if added or not CHANGES.exists():
        CHANGES.write_text("// Written by monitor/changes.py. Do not edit by hand. Newest first.\nwindow.CHANGES="
                           + json.dumps((added + log)[:KEEP], ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    SNAPSHOT.write_text(json.dumps(new, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    for e in added:
        print(f"{e['how']:>4}  {e['inst']:<34} " + "; ".join(
            f"{c['field']}: {c['old'] or '-'} -> {c['new'] or '-'}" for c in e["changes"])[:200])
    print(f"{len(added)} instrument(s) changed, {len(applied)} automatically.")


if __name__ == "__main__":
    main()
