# AMLR Monitor

Private monitor of the EU AML package rollout: every RTS, ITS and Guideline under the AMLR, AMLD6 and AMLAR,
plus the Dutch implementation, with a daily digest of new publications from the primary sources.

## How it stays current

Every day at 06:17 UTC a GitHub Actions job (`.github/workflows/daily.yml`):

1. runs `monitor/stamp.py`, which sets an instrument's `reviewed` date to today when its details
   changed since the last run (`data/fingerprints.json`);
2. runs `monitor/fetch.py`, which reads the sources below, keeps only what it has not seen before
   (`data/seen.json`) and links each item to a tracked instrument by article reference
   ("Art. 28(1) AMLR"), keyword or similar title;
3. runs `monitor/linkcheck.py --if-due` once a month to confirm every source link still opens;
4. commits `data/` and republishes the page.

Nothing changes an instrument's status automatically. The digest suggests a change; you review it on the
page ("Mark reviewed" / "Dismiss", remembered in your browser) and the instrument data is updated by hand.
The digest also lists any instrument whose dates say its status is out of date (a consultation that has
closed, or an expected date that has passed).

### Updating an instrument

1. `data/instruments.js`: change `status`.
2. `data/pages.js`, the instrument's entry: tick the stage in `v` (versions) and give its date, label and
   link; update the facts in `f` ("Consultation closed", "Expected"); add the document to `s` (sources).
3. Push. "Last step" and "Next date" are worked out from the versions and facts, and the next run of
   `monitor/stamp.py` dates the change. Counts, the framework and the deadline cards follow on their own.

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
- `data/instruments.js`: tracked instruments, statuses, last-updated dates and match keywords
- `data/pages.js`: per-instrument facts, version history, sources and framework blocks
- `data/digest.js`, `data/seen.json`, `data/linkcheck.js`, `data/fingerprints.json`: written by the scripts
