"""Write CSVs from out/ straight into private Google Sheets, so the repo can be private.

Needs the GitHub secret GOOGLE_SA_JSON (a Google service account key, JSON). Share each target
sheet with the service account's email as Editor. Without the secret this script does nothing,
so the workflow keeps working while the secret is being set up.
"""
import csv, datetime as dt, json, os, sys
from zoneinfo import ZoneInfo
from config import OUT

MASTER = "1H74LsbUfLAbgsEJxoyIdvcNHqLsWXJBPys8ugJrNiWo"   # NBA Master (private, never share)
PERSONAL = {"2627": "1OmsjE9qkgA8IAY5TMty4MYfXY4em3Fh47hKgB2OxoIM",    # NBA Hit Rates 2026-27
            "blend": "1aKIjTmT8PYKZuXIWbDUPStX4lW2qaaw-A9Mk0i8ypqk"}   # NBA Hit Rates Blended
TABS = {"PLAYERS": "Hit Rates", "TODAY": "Today", "PHONE": "Phone", "GAMES": "Today games", "TRACKER": "Pick tracker"}
# (csv file in out/, spreadsheet id, tab, raw). Personal sheets are skipped until shared with the service account;
# once shared, their IMPORTDATA formulas are replaced by values written here, so the repo can be private.
TARGETS = [("MASTER_2627.csv", MASTER, "Master", True), ("GAMELOGS_2627.csv", MASTER, "Game logs", True),
           ("ROSTERS.csv", MASTER, "Rosters", True)]
for v, sid in PERSONAL.items():
    TARGETS += [(f"{c}_{v}.csv", sid, tab, False) for c, tab in TABS.items()] + [("VERIFY.csv", sid, "Fact-check", False)]


def cell(v):
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def main():
    key = os.environ.get("GOOGLE_SA_JSON")
    if not key:
        print("GOOGLE_SA_JSON not set; skipping sheet push")
        return
    import gspread
    gc = gspread.service_account_from_dict(json.loads(key))
    failed = 0
    for name, sid, tab, raw in TARGETS:
        try:
            rows = list(csv.reader(open(os.path.join(OUT, name))))
            if raw:
                rows = [[cell(v) for v in r] for r in rows]
            book = gc.open_by_key(sid)
            if tab == "Rosters" and len(rows) < 2:     # positions not downloaded in this checkout: keep the sheet as is
                print(f"{name} -> {tab}: empty, left unchanged")
                continue
            if tab in ("Game logs", "Rosters"):                     # whole tab rebuilt every run, sized to fit, row 1 frozen
                try:
                    ws = book.worksheet(tab)
                except gspread.exceptions.WorksheetNotFound:
                    ws = book.add_worksheet(tab, rows=len(rows) + 10, cols=len(rows[0]))
                ws.resize(rows=len(rows) + 10, cols=max(len(rows[0]), 3))
                ws.batch_clear(["A:Z"])
                ws.update(rows, "A1", value_input_option="RAW")
                ws.freeze(rows=1)
                print(f"{name} -> {tab}: {len(rows)} rows")
                continue
            ws = book.worksheet(tab)
            width = max(len(r) for r in rows)
            if ws.col_count < width:                   # e.g. new lines added: grow the tab instead of failing
                ws.add_cols(width - ws.col_count)
            if ws.row_count < len(rows):
                ws.add_rows(len(rows) - ws.row_count)
            ws.batch_clear(["A:GZ"])
            ws.update(rows, "A1", value_input_option="RAW" if raw else "USER_ENTERED")
            print(f"{name} -> {tab}: {len(rows)} rows")
        except Exception as e:  # noqa: BLE001  - never block the data update
            print(f"{name} -> {tab}: skipped ({type(e).__name__}: {str(e)[:200]})")
            failed += sid == MASTER
    now = dt.datetime.now(ZoneInfo("Europe/London")).strftime("%a %d %b %H:%M")
    games = sorted(f[:8] for f in os.listdir(os.path.join(os.path.dirname(OUT), "data", "games")))
    last = f"{games[-1][:4]}-{games[-1][4:6]}-{games[-1][6:8]}" if games else "n/a"
    if not failed:
        gc.open_by_key(MASTER).worksheet("Info").update(
            [[f"Updated {now} UK · box scores to {last}"]], "A1", value_input_option="RAW")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
