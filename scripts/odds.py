"""Bookmaker prices for tonight's player props, from OddsPapi (free tier).

  python scripts/odds.py due     fetch once a day, the first injury-check run from ODDS_HOUR UK (props are up by then)
  python scripts/odds.py now     fetch now (manual test)

Writes data/odds/today.json: {"fetched": iso, "fixtures": {...}, "props": {player key: {stat: {line: {book: price}}}}}
"line" is the sheet's line (e.g. 5 for "5+", which the books list as Over 4.5). Only over prices are kept.
Needs the GitHub secret ODDSPAPI_KEY; without it the script does nothing. The key is never printed or saved.
Requests per fetch: 1 (fixtures) + 1 per game, 3 s apart; capped per month by ODDS_MONTHLY_CAP.
"""
import datetime as dt, json, os, sys, time, urllib.parse, urllib.request
from zoneinfo import ZoneInfo
from common import jload, jsave
from config import DATA

BASE = "https://api.oddspapi.io/v4"
KEY = os.environ.get("ODDSPAPI_KEY", "").strip()
NBA = 132                       # OddsPapi tournamentId for the NBA
BOOKS = {"bet365": "bet365", "williamhill": "William Hill", "ladbrokes": "Ladbrokes", "paddypower": "Paddy Power"}
ODDS_HOUR = 17                  # UK hour from which the daily fetch runs
ODDS_MONTHLY_CAP = 240          # free tier may be 250 requests a month; stay under it
STAT = {"Points": "PTS", "Rebounds": "REB", "Assists": "AST", "3 Point FG": "3PM",
        "Points + Rebounds": "PR", "Points + Assists": "PA", "Assists + Rebounds": "RA",
        "Points + Assists + Rebounds": "PRA"}
UK = ZoneInfo("Europe/London")
DIR = os.path.join(DATA, "odds")
USAGE = os.path.join(DIR, "usage.json")


def get(path, **params):
    time.sleep(3)                                    # the free tier answers 429 to quick bursts
    params["apiKey"] = KEY
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "HitRateHub"}), timeout=60) as r:
        return json.loads(r.read())


def count(n):
    u = jload(USAGE, {}) or {}
    m = dt.datetime.now(UK).strftime("%Y-%m")
    u[m] = u.get(m, 0) + n
    jsave(USAGE, u)


def used():
    return (jload(USAGE, {}) or {}).get(dt.datetime.now(UK).strftime("%Y-%m"), 0)


def player_key(name):
    from build import key                            # same matching as the box scores
    last, _, first = name.partition(", ")
    return key(f"{first} {last}".strip() if first else name)


def markets():
    """Player-prop market catalogue (marketId -> stat, line, over outcomeId). Cached; refreshed monthly."""
    path = os.path.join(DIR, "markets.json")
    cache = jload(path, {}) or {}
    if cache.get("month") == dt.datetime.now(UK).strftime("%Y-%m") and cache.get("m"):
        return cache["m"]
    raw = get("markets", sportId=11)
    count(1)
    m = {}
    for x in raw:
        name = x.get("marketName", "")
        if not x.get("playerProp") or not name.startswith("Over Under Player ") or "(incl. overtime)" not in name:
            continue
        st = STAT.get(name[len("Over Under Player "):].replace(" (incl. overtime)", ""))
        over = [o["outcomeId"] for o in x.get("outcomes", []) if o.get("outcomeName") == "Over"]
        if st and over and x.get("handicap") is not None and float(x["handicap"]) % 1 == 0.5:
            m[str(x["marketId"])] = {"stat": st, "line": int(float(x["handicap"]) + 0.5), "over": str(over[0])}
    jsave(path, {"month": dt.datetime.now(UK).strftime("%Y-%m"), "m": m})
    return m


def fetch():
    mk = markets()
    fx = get("fixtures", tournamentId=NBA)
    count(1)
    now = dt.datetime.now(dt.timezone.utc)
    lo, hi = now.strftime("%Y-%m-%dT%H:%M"), (now + dt.timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M")
    games = sorted([f for f in fx if lo <= str(f.get("startTime", "")) <= hi], key=lambda f: f["startTime"])
    if used() + len(games) > ODDS_MONTHLY_CAP:
        print(f"monthly cap: {used()} used, {len(games)} needed, cap {ODDS_MONTHLY_CAP}; skipping")
        return None
    out = {"fetched": now.isoformat(timespec="minutes"), "fixtures": {}, "props": {}}
    for f in games:
        try:
            o = get("odds", fixtureId=f["fixtureId"])
        except Exception as e:  # noqa: BLE001
            print(f"{f.get('participant2Abbr')} @ {f.get('participant1Abbr')}: {type(e).__name__} {getattr(e, 'code', '')}")
            continue
        finally:
            count(1)
        out["fixtures"][f["fixtureId"]] = {"home": f.get("participant1Abbr"), "away": f.get("participant2Abbr"),
                                           "start": f.get("startTime")}
        n = 0
        for slug, book in BOOKS.items():
            for mid, mdata in ((o.get("bookmakerOdds") or {}).get(slug, {}).get("markets") or {}).items():
                info = mk.get(str(mid))
                if not info or not mdata.get("marketActive", True):
                    continue
                for p in ((mdata.get("outcomes") or {}).get(info["over"], {}).get("players") or {}).values():
                    if not p.get("active") or not p.get("price") or not p.get("playerName"):
                        continue
                    k = player_key(p["playerName"])
                    out["props"].setdefault(k, {})["start"] = f["startTime"]     # so prices only match this game
                    (out["props"][k].setdefault(info["stat"], {})
                     .setdefault(str(info["line"]), {}))[book] = round(float(p["price"]), 3)
                    n += 1
        print(f"{f.get('participant2Abbr')} @ {f.get('participant1Abbr')}: {n} prices")
    jsave(os.path.join(DIR, "today.json"), out)
    print(f"{len(out['props'])} players priced; {used()} requests used this month")
    return out


def main():
    if not KEY:
        print("ODDSPAPI_KEY not set; skipping odds")
        return 0
    mode = sys.argv[1] if len(sys.argv) > 1 else "due"
    if mode == "due":
        now = dt.datetime.now(UK)
        last = (jload(os.path.join(DIR, "today.json"), {}) or {}).get("fetched", "")
        last_uk = dt.datetime.fromisoformat(last).astimezone(UK) if last else None
        if now.hour < ODDS_HOUR and now.hour >= 7:
            print("odds: not due yet")
            return 0
        if last_uk and last_uk.date() == now.date() and last_uk.hour >= ODDS_HOUR:
            print("odds: already fetched today")
            return 0
        if last_uk and now.hour < 7 and (now - last_uk) < dt.timedelta(hours=12):
            print("odds: already fetched this evening")
            return 0
    try:
        fetch()
    except Exception as e:  # noqa: BLE001  - never block the update; never echo the URL (it holds the key)
        print(f"odds fetch failed: {type(e).__name__} {getattr(e, 'code', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
