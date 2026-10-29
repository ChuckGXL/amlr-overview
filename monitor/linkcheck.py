#!/usr/bin/env python3
"""Monthly check that every source link in data/pages.js still opens.

Sites that refuse scripts (EUR-Lex answers 202 with an empty body, DNB answers 403) are reported
as "not checkable", not as broken. Run with --if-due to skip when the last check is under 28 days old.
"""
import concurrent.futures as cf
import datetime as dt
import json
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "linkcheck.js"
UA = "AMLR-Monitor/1.0 (private regulatory monitor; monthly link check)"


def load_js(path, var):
    return json.loads(path.read_text(encoding="utf-8").split(f"window.{var}=", 1)[1].rstrip().rstrip(";"))


def check(url):
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                if r.status == 202:
                    return "unchecked", 202
                return "ok", r.status
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                return "unchecked", e.code
            if method == "GET" or e.code not in (405, 501):
                if e.code in (404, 410):
                    return "broken", e.code
                if method == "GET":
                    return "error", e.code
        except Exception as e:
            if method == "GET":
                return "error", type(e).__name__
    return "error", "?"


def main():
    if "--if-due" in sys.argv and OUT.exists():
        last = dt.date.fromisoformat(load_js(OUT, "LINKCHECK")["checked"][:10])
        if (dt.date.today() - last).days < 28:
            print(f"link check not due (last run {last})")
            return 0
    pages = load_js(DATA / "pages.js", "PAGES")
    links = {}
    for iid, page in pages.items():
        for url, title in page["s"] + [[v[4], v[3] or v[1]] for v in page["v"] if v[4]]:
            links.setdefault(url, {"url": url, "title": title, "instruments": set()})["instruments"].add(iid)
    with cf.ThreadPoolExecutor(6) as pool:
        for link, (state, code) in zip(links.values(), pool.map(check, links)):
            link.update(state=state, code=code, instruments=sorted(link["instruments"]))
    counts = {s: sum(1 for l in links.values() if l["state"] == s) for s in ("ok", "unchecked", "broken", "error")}
    result = {"checked": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "counts": counts,
              "problems": [l for l in links.values() if l["state"] in ("broken", "error")]}
    OUT.write_text("// Written by monitor/linkcheck.py. Do not edit by hand.\nwindow.LINKCHECK="
                   + json.dumps(result, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    print(f"{len(links)} links: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
