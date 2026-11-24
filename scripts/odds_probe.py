"""One-off check of what OddsPapi returns for NBA (bet365 player props in particular).

Needs the GitHub secret ODDSPAPI_KEY. Uses about 5 requests. Writes data/odds_probe/*.json
(the key is never written or printed). Run from the "odds-test" workflow.
"""
import datetime as dt, json, os, sys, urllib.parse, urllib.request

BASE = "https://api.oddspapi.io/v4"
KEY = os.environ.get("ODDSPAPI_KEY", "").strip()
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "odds_probe")


def get(path, **params):
    params["apiKey"] = KEY
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "HitRateHub"}), timeout=60) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001  - never echo the URL (it holds the key)
        body = getattr(e, "read", lambda: b"")()[:500].decode(errors="ignore")
        return {"_error": f"{type(e).__name__} {getattr(e, 'code', '')}", "_body": body}


def save(name, obj):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    print("saved", name)


def main():
    if not KEY:
        print("ODDSPAPI_KEY not set")
        return 0
    tours = get("tournaments", sportId=11)
    save("tournaments.json", tours if isinstance(tours, dict) else tours[:400])
    lst = tours if isinstance(tours, list) else tours.get("data", tours.get("tournaments", []))
    nba = [t for t in lst if isinstance(t, dict) and "nba" in json.dumps(t).lower()
           and "g league" not in json.dumps(t).lower()]
    if not nba:
        print("NBA tournament not found")
        return 0
    tid = nba[0].get("tournamentId") or nba[0].get("id")
    fx = get("fixtures", tournamentId=tid)
    save("fixtures.json", fx if isinstance(fx, dict) else fx[:30])
    fl = fx if isinstance(fx, list) else fx.get("data", fx.get("fixtures", []))
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    upcoming = [f for f in fl if isinstance(f, dict) and str(f.get("startTime") or f.get("trueStartTime") or "") >= now[:10]]
    summary = {"nba_tournament": nba[0], "fixtures_found": len(fl), "upcoming": len(upcoming), "games": []}
    for f in (upcoming or fl)[:2]:
        fid = f.get("fixtureId") or f.get("id")
        odds = get("odds", fixtureId=fid)
        books = (odds.get("bookmakerOdds") or {}) if isinstance(odds, dict) else {}
        b365 = books.get("bet365", {})
        markets = b365.get("markets", {}) if isinstance(b365, dict) else {}
        summary["games"].append({"fixture": f, "bookmakers": sorted(books), "bet365_markets": len(markets),
                                 "error": odds.get("_error") if isinstance(odds, dict) else None})
        trimmed = dict(list(markets.items())[:60])
        save(f"bet365_{fid}.json", {"fixture": f, "markets": trimmed})
    try:
        mk = get("markets", sportId=11)
        save("markets.json", mk if isinstance(mk, dict) else mk[:600])
    except Exception:  # noqa: BLE001
        pass
    save("summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "nba_tournament"}, default=str)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
