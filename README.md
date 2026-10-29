# AMLR Monitor

Private monitor of the EU AML package rollout: every RTS, ITS and Guideline under the AMLR, AMLD6 and AMLAR,
plus the Dutch implementation, with a daily digest of new publications from the primary sources.

## How it stays current

Every day at 06:17 UTC a GitHub Actions job (`.github/workflows/daily.yml`):

1. runs `monitor/fetch.py`, which reads the sources below, keeps only what it has not seen before
   (`data/seen.json`) and links each item to a tracked instrument by article reference
   ("Art. 28(1) AMLR"), keyword or similar title;
2. runs `monitor/changes.py`, which applies status changes automatically and logs every change (below);
3. runs `monitor/linkcheck.py --if-due` once a month to confirm every source link still opens;
4. commits `data/` and republishes the page.

### Automatic status changes

| What the check finds | New status |
|---|---|
| The "Consultation closed" date has passed | Consultation closed, being finalised |
| An AMLA consultation linked to the instrument | In consultation |
| An AMLA or EBA final report, or a submission to the Commission | Final, awaiting publication |
| A delegated or implementing regulation on EUR-Lex | Published |

A status only moves forward, and only links by article reference or keyword count, never a "similar
title". Each change also ticks the step in the version history (date, title, link) and adds the document
as a source, so "Last step" and "Next date" follow. A consultation's closing date is not in the feeds, so
an instrument found in consultation stays there until its final text appears.

### Change log and notifications

`monitor/changes.py` compares every instrument with `data/snapshot.json`, its state at the last run, and
writes what changed (old and new values) to `data/changes.js`: **Automatic** for the changes above,
**Edited** for anything pushed to the data files. The changed instrument's `reviewed` date becomes today.

On the page, the bell next to Sign out counts new changes and new digest publications; its panel also
lists what needs attention (an expected date that has passed, a source that failed, a broken link).
"Mark all as seen" clears the count, remembered per browser. The Changes section lists the last 90 days,
the table marks a changed instrument for two weeks, and each instrument page keeps its full history.

To correct a wrong change, edit `data/instruments.js` / `data/pages.js` and push; it is logged as Edited.
A status that the check moved forward is not moved back by it.

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
python3 monitor/fetch.py && python3 monitor/changes.py
```

```bash
python3 -m http.server 4317
```

Then open http://localhost:4317.

## Files

- `index.html`: the dashboard
- `data/instruments.js`: tracked instruments, statuses, last-updated dates and match keywords
- `data/pages.js`: per-instrument facts, version history, sources and framework blocks
- `data/digest.js`, `data/seen.json`, `data/linkcheck.js`, `data/changes.js`, `data/snapshot.json`: written by the scripts
