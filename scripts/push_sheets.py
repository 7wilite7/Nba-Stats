"""Write CSVs from out/ straight into private Google Sheets, so the repo can be private.

Needs the GitHub secret GOOGLE_SA_JSON (a Google service account key, JSON). Share each target
sheet with the service account's email as Editor. Without the secret this script does nothing,
so the workflow keeps working while the secret is being set up.
"""
import csv, datetime as dt, json, os, sys
from zoneinfo import ZoneInfo
from config import OUT

MASTER = "1H74LsbUfLAbgsEJxoyIdvcNHqLsWXJBPys8ugJrNiWo"   # NBA Master (private, never share)
# (csv file in out/, spreadsheet id, tab). Add your personal sheets here before making the repo private.
TARGETS = [("MASTER_2627.csv", MASTER, "Master")]


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
    for name, sid, tab in TARGETS:
        rows = [[cell(v) for v in r] for r in csv.reader(open(os.path.join(OUT, name)))]
        ws = gc.open_by_key(sid).worksheet(tab)
        ws.batch_clear(["A:FZ"])
        ws.update(rows, "A1", value_input_option="RAW")
        print(f"{name} -> {sid}/{tab}: {len(rows)} rows")
    now = dt.datetime.now(ZoneInfo("Europe/London")).strftime("%a %d %b %H:%M")
    games = sorted(f[:8] for f in os.listdir(os.path.join(os.path.dirname(OUT), "data", "games")))
    last = f"{games[-1][:4]}-{games[-1][4:6]}-{games[-1][6:8]}" if games else "n/a"
    gc.open_by_key(MASTER).worksheet("Info").update(
        [[f"Updated {now} UK · box scores to {last}"]], "A1", value_input_option="RAW")


if __name__ == "__main__":
    sys.exit(main())
