# NBA Stats

Self-updating NBA hit-rate sheets. Every morning at 08:00 UK, GitHub Actions:

1. `scripts/fetch.py` – downloads new box scores (Basketball Reference) plus the schedule, rosters, injury report and ESPN box scores.
2. `scripts/verify.py` – fact-checks every Basketball Reference box score against ESPN.
3. `scripts/build.py` – writes the CSVs in `out/` that the Google Sheets import:
   `PLAYERS_*`, `TODAY_*`, `PHONE_*`, `TRACKER_*` for `2627` (2026-27 only) and `blend` (2nd half of 2025-26 + 2026-27, rolling).

**Pick checks** (added 24 Nov 2026, in `build.py`): each Today pick also shows Last 5, Low (last 5) and Fair odds
(1 ÷ hit rate), and the Note flags Cold form (3 or fewer hits in the last 5), Low floor (a last-5 value under half
the line), Back-to-back and injury status. The **Best picks** tab ranks them: the safest 10 unflagged picks on the
slate (one per player) and the top 3 per game. The Pick tracker compares flagged vs unflagged picks.

**True rate** = (hits + 3 × league rate) ÷ (games + 3). It stops tiny samples showing 100%. K=3 tested best on 2025-26 data.
