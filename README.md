# NBA Stats

Self-updating NBA hit-rate sheets. Every morning at 08:00 UK, GitHub Actions:

1. `scripts/fetch.py` – downloads new box scores (Basketball Reference) plus the schedule, rosters, injury report and ESPN box scores.
2. `scripts/verify.py` – fact-checks every Basketball Reference box score against ESPN.
3. `scripts/build.py` – writes the CSVs in `out/` that the Google Sheets import:
   `PLAYERS_*`, `TODAY_*`, `PHONE_*`, `TRACKER_*` for `2627` (2026-27 only) and `blend` (2nd half of 2025-26 + 2026-27, rolling).

**True rate** = (hits + 3 × league rate) ÷ (games + 3). It stops tiny samples showing 100%. K=3 tested best on 2025-26 data.
