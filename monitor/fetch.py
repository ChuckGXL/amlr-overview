#!/usr/bin/env python3
"""Daily source check.

Reads the regulators' feeds and open-data APIs, keeps what has not been seen before,
links each new item to a tracked instrument and writes data/digest.js for the page.
Nothing here changes an instrument's status: monitor/changes.py does that from the digest.
Standard library only, so it runs on a bare GitHub Actions runner.
"""
import datetime as dt
import email.utils
import hashlib
import html
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = "AMLR-Monitor/1.0 (private regulatory monitor; one request per source per day)"
KEEP_DAYS = 120      # how long a found item stays in the digest
BACKFILL_DAYS = 30   # on the very first run, show items published this recently
TODAY = dt.date.today()

AML_EN = r"\b(aml|cft|amla|amlr)\b|money laundering|terrorist financing|travel rule|de-risking|financial crime"
AML_NL = r"witwas|\bwwft\b|terrorismefinanciering|sanctiewet|\bamlr\b|\bamla\b"
NOISE = r"privacy[ _-]statement|record[ _-]of[ _-]processing|organisational[ _-]chart|vacanc|procurement|call[ _-]for[ _-]tender|recruitment"

SOURCES = [
    {"id": "amla-news", "label": "AMLA · news & press releases", "kind": "rss", "url": "https://www.amla.europa.eu/node/19/rss_en"},
    {"id": "amla-consultations", "label": "AMLA · public consultations", "kind": "rss", "url": "https://www.amla.europa.eu/node/8/rss_en"},
    {"id": "amla-docs", "label": "AMLA · document library", "kind": "rss", "url": "https://www.amla.europa.eu/node/105/rss_en", "exclude": NOISE},
    {"id": "amla-hearings", "label": "AMLA · public hearings", "kind": "rss", "url": "https://www.amla.europa.eu/node/190/rss_en"},
    {"id": "amla-events", "label": "AMLA · events", "kind": "rss", "url": "https://www.amla.europa.eu/node/4/rss_en"},
    {"id": "amla-reports", "label": "AMLA · reports & notes", "kind": "rss", "url": "https://www.amla.europa.eu/node/267/rss_en"},
    {"id": "eba", "label": "EBA · news (AML items only)", "kind": "rss", "url": "https://www.eba.europa.eu/news-press/news/rss.xml", "require": AML_EN},
    {"id": "eurlex", "label": "EUR-Lex · acts based on AMLR, AMLD6, AMLAR", "kind": "sparql", "url": "https://publications.europa.eu/webapi/rdf/sparql"},
    {"id": "afm", "label": "AFM · news for professionals (AML items only)", "kind": "rss", "url": "https://www.afm.nl/nl-nl/rss-feed/nieuws-professionals", "require": AML_NL},
    {"id": "tk", "label": "Tweede Kamer · parliamentary documents", "kind": "tk", "url": "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Document"},
    {"id": "ob", "label": "Staatsblad & Staatscourant", "kind": "sru", "url": "https://repository.overheid.nl/sru"},
    # These block automated requests or have no feed; the page shows them as "check by hand".
    {"id": "dnb", "label": "DNB · Wwft and the EU AML package", "kind": "manual", "url": "https://www.dnb.nl/voor-de-sector/open-boek-toezicht/wet-regelgeving/wwft/"},
    {"id": "fiu", "label": "FIU-Nederland", "kind": "manual", "url": "https://www.fiu-nederland.nl/"},
]


# ---------- fetching ----------

class Blocked(Exception):
    pass


def get(url, params=None, accept=None):
    if params:
        url += "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)  # %20, not "+": the SRU server reads "+" literally
    headers = {"User-Agent": UA}
    if accept:
        headers["Accept"] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as r:
        body = r.read()
        if r.status != 200 or not body:
            raise Blocked(f"HTTP {r.status}, {len(body)} bytes")
        return body


def clean(text, limit=320):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def rss(src):
    root = ET.fromstring(get(src["url"]))
    for it in root.iter("item"):
        pub = it.findtext("pubDate")
        date = email.utils.parsedate_to_datetime(pub).date().isoformat() if pub else ""
        yield {"title": clean(it.findtext("title"), 300), "link": (it.findtext("link") or "").strip(),
               "date": date, "summary": clean(it.findtext("description"))}


SPARQL = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?celex ?date (SAMPLE(?t) AS ?title) (GROUP_CONCAT(DISTINCT ?name; separator=", ") AS ?bases) WHERE {
  VALUES (?name ?basis) { ("AMLR" "32024R1624"^^xsd:string) ("AMLD6" "32024L1640"^^xsd:string) ("AMLAR" "32024R1620"^^xsd:string) }
  ?b cdm:resource_legal_id_celex ?basis .
  ?w cdm:resource_legal_based_on_resource_legal ?b ; cdm:resource_legal_id_celex ?celex ; cdm:work_date_document ?date .
  OPTIONAL { ?e cdm:expression_belongs_to_work ?w ;
               cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
               cdm:expression_title ?t }
} GROUP BY ?celex ?date ORDER BY DESC(?date) LIMIT 200"""


def sparql(src):
    res = json.loads(get(src["url"], {"query": SPARQL}, "application/sparql-results+json"))
    for b in res["results"]["bindings"]:
        celex = b["celex"]["value"]
        yield {"title": b.get("title", {}).get("value") or f"CELEX {celex}",
               "link": f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
               "date": b["date"]["value"][:10], "summary": f"CELEX {celex} · legal basis: {b['bases']['value']}"}


def tk(src):
    since = (TODAY - dt.timedelta(days=21)).isoformat()
    terms = " or ".join(f"contains({f},'{w}')" for f in ("Onderwerp", "Titel")
                        for w in ("witwas", "terrorismefinanciering", "Wwft", "AMLR", "AMLA"))
    params = {"$filter": f"Verwijderd eq false and Datum ge {since}T00:00:00Z and ({terms})",
              "$orderby": "Datum desc", "$top": "50", "$select": "Id,Datum,Titel,Onderwerp,Soort,DocumentNummer",
              "$expand": "Kamerstukdossier($select=Nummer)"}
    for d in json.loads(get(src["url"], params, "application/json"))["value"]:
        dossiers = ", ".join(str(k["Nummer"]) for k in d.get("Kamerstukdossier") or [])
        yield {"title": f"{d['Soort']}: {d['Onderwerp']}",
               "link": f"https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/Document({d['Id']})/resource",
               "date": d["Datum"][:10], "summary": (d["Titel"] or "") + (f" · dossier {dossiers}" if dossiers else "")}


def sru(src):
    q = ('(dt.title any "witwassen terrorismefinanciering Wwft Sanctiewet anti-witwasverordening") '
         'and (w.publicatienaam="Staatsblad" or w.publicatienaam="Staatscourant") sortBy dt.modified/sort.descending')
    root = ET.fromstring(get(src["url"], {"query": q, "maximumRecords": "25"}))
    for rec in root.iterfind(".//{*}record"):  # iter() does not understand the {*} namespace wildcard
        url = rec.findtext(".//{*}preferredUrl") or ""
        if not url:
            continue
        yield {"title": clean(rec.findtext(".//{*}title"), 300), "link": url,
               "date": (rec.findtext(".//{*}available") or rec.findtext(".//{*}modified") or "")[:10],
               "summary": rec.findtext(".//{*}publicatienaam") or ""}


READERS = {"rss": rss, "sparql": sparql, "tk": tk, "sru": sru}


# ---------- linking items to instruments ----------

def load_js(path, var):
    text = path.read_text(encoding="utf-8")
    return json.loads(text.split(f"window.{var}=", 1)[1].rstrip().rstrip(";"))


REF = re.compile(r"(\d+)(?:\((\d+)\))?\s*(AMLR|AMLAR|AMLD6|AMLD)\b", re.I)
# "Article 12(7) of Regulation (EU) 2024/1620" names the act by number instead of acronym
ACT_NO = [(r"(?:of\s+)?(?:the\s+)?Regulation\s+\(EU\)\s+(?:No\s+)?2024/1624", "AMLR"),
          (r"(?:of\s+)?(?:the\s+)?Regulation\s+\(EU\)\s+(?:No\s+)?2024/1620", "AMLAR"),
          (r"(?:of\s+)?(?:the\s+)?Directive\s+\(EU\)\s+2024/1640", "AMLD6"),
          (r"of\s+(?:the\s+)?(AMLR|AMLAR|AMLD6?)\b", r"\1")]


def refs(text):
    """Article references such as '28(1) AMLR' -> {(28, 1, 'AMLR')}; AMLD means AMLD6 in this package."""
    out = set()
    for pat, name in ACT_NO:
        text = re.sub(pat, name, text or "", flags=re.I)
    for n, p, reg in REF.findall(text):
        reg = reg.upper().replace("AMLD6", "AMLD").replace("AMLD", "AMLD6")
        out.add((int(n), int(p) if p else None, reg))
    return out


def inst_refs(inst, page):
    out = set()
    m = re.search(r"(AMLR|AMLAR|AMLD6)\b", inst["art"])
    if m:  # "Art. 16(4), 17(3) AMLR": every number before the act name belongs to that act
        for n, p in re.findall(r"(\d+)(?:\((\d+)\))?", inst["art"][:m.start()]):
            out.add((int(n), int(p) if p else None, m.group(1)))
    for k, v in (page or {}).get("f", []):
        if k == "Legal basis":
            out |= refs(re.sub(r"(AMLR|AMLAR|AMLD6?)\s+art\.\s*", "", v) + " " + v.split()[0])
    return out


STOP = set("the and for with from that this under into their other draft rts its guidelines guideline on of in to by a an "
           "between obliged entities regulation".split())


def tokens(text):
    return {w for w in re.findall(r"[a-z][a-z/-]{3,}", text.lower()) if w not in STOP}


def kw_hit(kw, text):
    return re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text)


def link(item, src_id, insts, pages):
    text = f"{item['title']} {item['summary']}".lower()
    found, item_refs = {}, refs(item["title"] + " " + item["summary"])
    for inst in insts:
        for (n, p, reg) in inst_refs(inst, pages.get(inst["id"])):
            hit = next((r for r in item_refs if r[0] == n and r[2] == reg and (r[1] is None or p is None or r[1] == p)), None)
            if hit:
                found[inst["id"]] = f"Art. {hit[0]}{f'({hit[1]})' if hit[1] else ''} {hit[2]}"
                break
    for inst in insts:
        if inst["id"] in found or (inst.get("only") and src_id not in inst["only"]):
            continue
        kw = next((k for k in inst.get("kw", []) if kw_hit(k, text)), None)
        if kw:
            found[inst["id"]] = f"keyword “{kw}”"
    if not found:  # weak fallback: most of an instrument's distinctive title words appear in the item title
        it = tokens(item["title"])
        best = max(((len(it & tokens(i["name"])) / max(1, len(tokens(i["name"]))), i) for i in insts if i["type"] != "L1"),
                   key=lambda x: x[0], default=(0, None))
        if best[0] >= 0.6 and len(it & tokens(best[1]["name"])) >= 3:
            found[best[1]["id"]] = "similar title (weak match)"
    return found


def suggest(item, src_id, inst):
    t, st = (item["title"] + " " + item["summary"]).lower(), inst["status"]
    if src_id == "eurlex" and st != "pub" and re.search(r"delegated regulation|implementing regulation", t):
        return "Adopted act: once in the Official Journal, status moves to Published. Add the EUR-Lex link."
    if src_id == "amla-consultations" and st in ("ann", "eba"):
        return "New consultation: status may move to In consultation. Add as a source."
    if src_id in ("amla-hearings", "amla-events"):
        return "Public hearing: add it as a step in the version history."
    if re.search(r"final report|finalis|submitted to the (european )?commission", t) and st in ("consult", "closed", "eba", "ann"):
        return "Final text: status may move to Final, awaiting publication. Add as a source."
    return "Add as a source if relevant."


# ---------- main ----------

def main():
    insts = load_js(DATA / "instruments.js", "INSTRUMENTS")
    by_id = {i["id"]: i for i in insts}
    pages = load_js(DATA / "pages.js", "PAGES")
    seen_path, digest_path = DATA / "seen.json", DATA / "digest.js"
    first_run = not seen_path.exists()
    seen = {} if first_run else json.loads(seen_path.read_text())
    old = load_js(digest_path, "DIGEST")["items"] if digest_path.exists() else []
    items = {i["id"]: i for i in old if (TODAY - dt.date.fromisoformat(i["found"])).days <= KEEP_DAYS}

    status = []
    for src in SOURCES:
        row = {"id": src["id"], "label": src["label"], "url": src["url"], "kind": src["kind"]}
        if src["kind"] == "manual":
            status.append({**row, "state": "manual"})
            continue
        try:
            fetched = new = 0
            for it in READERS[src["kind"]](src):
                text = it["title"] + " " + it["summary"]
                if not it["link"] or (src.get("require") and not re.search(src["require"], text, re.I)) \
                        or (src.get("exclude") and re.search(src["exclude"], text, re.I)):
                    continue
                fetched += 1
                iid = hashlib.sha1(it["link"].encode()).hexdigest()[:12]
                if iid in items and src["label"] not in items[iid]["sources"]:
                    items[iid]["sources"].append(src["label"])
                if iid in seen:
                    continue
                seen[iid] = TODAY.isoformat()
                recent = it["date"] and (TODAY - dt.date.fromisoformat(it["date"])).days <= BACKFILL_DAYS
                if first_run and not recent:
                    continue
                new += 1
                links = link(it, src["id"], insts, pages)
                items[iid] = {"id": iid, "found": TODAY.isoformat(), "backfill": first_run, "sources": [src["label"]],
                              "source": src["id"], **it,
                              "matches": [{"id": k, "how": v, "suggest": suggest(it, src["id"], by_id[k])} for k, v in links.items()]}
            status.append({**row, "state": "ok", "fetched": fetched, "new": new})
        except Exception as e:  # one failing source must not stop the others
            status.append({**row, "state": "error", "error": f"{type(e).__name__}: {e}"[:200]})
            print(f"! {src['id']}: {e}", file=sys.stderr)

    ordered = sorted(items.values(), key=lambda i: (i["found"], i["date"]), reverse=True)
    digest = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "firstRun": first_run,
              "sources": status, "items": ordered}
    digest_path.write_text("// Written by monitor/fetch.py. Do not edit by hand.\nwindow.DIGEST="
                           + json.dumps(digest, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    seen_path.write_text(json.dumps(seen, indent=0, sort_keys=True))
    for s in status:
        print(f"{s['state']:>6}  {s['id']:<19} " + (f"{s.get('fetched', 0)} relevant, {s.get('new', 0)} new" if s["state"] == "ok" else s.get("error", "")))
    print(f"{len(ordered)} items in digest")
    return 1 if all(s["state"] == "error" for s in status if s["kind"] != "manual") else 0


if __name__ == "__main__":
    sys.exit(main())
