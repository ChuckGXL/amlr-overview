# AMLR Monitor

Private monitor of the EU AML package rollout: every RTS, ITS and Guideline under the AMLR, AMLD6 and AMLAR,
plus the Dutch implementation, with a daily digest of new publications from the primary sources.

## How it stays current

Every day at 06:17 UTC a GitHub Actions job (`.github/workflows/daily.yml`):

1. runs `monitor/fetch.py`, which reads the sources below, keeps only what it has not seen before
   (`data/seen.json`) and links each item to a tracked instrument by article reference
   ("Art. 28(1) AMLR"), keyword or similar title;
2. runs `monitor/linkcheck.py --if-due` once a month to confirm every source link still opens;
3. commits `data/` and republishes the page.

Nothing changes an instrument's status automatically. The digest suggests a change; you review it on the
page ("Mark reviewed" / "Dismiss", remembered in your browser) and the instrument data in
`data/instruments.js` and `data/pages.js` is updated by hand.

| Source | How it is read |
|---|---|
| AMLA news & press releases, consultations, document library, hearings, events, reports | RSS |
| EBA news (AML items only) | RSS |
| EU acts based on AMLR / AMLD6 / AMLAR | Publications Office SPARQL endpoint (EUR-Lex blocks scripts) |
| AFM news for professionals (AML items only) | RSS |
| Tweede Kamer documents mentioning witwassen / Wwft / AMLR | Open data OData API |
| Staatsblad and Staatscourant | officielebekendmakingen SRU API |
| DNB, FIU-Nederland | Not automatable (DNB blocks scripts, FIU-NL has no feed): listed for a manual check |

## Run locally

```bash
python3 monitor/fetch.py
```

```bash
python3 -m http.server 4317
```

Then open http://localhost:4317.

## Files

- `index.html`: the dashboard
- `data/instruments.js`: tracked instruments, statuses, dates and match keywords
- `data/pages.js`: per-instrument facts, version history, sources and framework blocks
- `data/digest.js`, `data/seen.json`, `data/linkcheck.js`: written by the scripts
