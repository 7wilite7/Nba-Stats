"""Download what the daily build needs.

- Basketball Reference: every 2026-27 box score (cached, one file per game) -> data/games/
- ESPN: schedule (scoreboards), current rosters, injury report, and box scores for the fact-check.
"""
import datetime as dt, html, json, os, re, sys, time, unicodedata
from zoneinfo import ZoneInfo
from config import DATA, SEASON_START, BREF_DELAY, BREF_TO_STD, ESPN_TO_STD
from common import get, jload, jsave

ET = ZoneInfo("America/New_York")
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def ascii_name(s):
    s = html.unescape(s).strip()
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


# ---------------- Basketball Reference ----------------

_last = [0.0]


def bref(url):
    wait = BREF_DELAY - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    try:
        return get(url).decode("utf8", "replace")
    finally:
        _last[0] = time.time()


def num(row, stat):
    m = re.search(r'data-stat="%s"[^>]*>(-?\d+)<' % stat, row)
    return int(m.group(1)) if m else 0


def parse_box(page, gid):
    date = f"{gid[:4]}-{gid[4:6]}-{gid[6:8]}"
    home = gid[-3:]
    teams, players = [], []
    for m in re.finditer(r'<table[^>]*id="box-([A-Z]{3})-game-basic"(.*?)</table>', page, re.S):
        team = m.group(1)
        teams.append(team)
        body = re.search(r"<tbody>(.*?)</tbody>", m.group(2), re.S)
        if not body:
            continue
        starter = True
        for row in re.findall(r"<tr[^>]*>.*?</tr>", body.group(1), re.S):
            if 'class="thead"' in row[:60] or "Reserves" in row and 'data-stat="player"' not in row:
                starter = False
                continue
            pm = re.search(r'data-stat="player"[^>]*>(?:<a[^>]*>)?([^<]+)', row)
            if not pm or 'data-stat="reason"' in row:
                continue
            mp = re.search(r'data-stat="mp"[^>]*>(\d+):(\d+)<', row)
            mins = round(int(mp.group(1)) + int(mp.group(2)) / 60, 1) if mp else 0.0
            players.append({"name": ascii_name(pm.group(1)), "team": BREF_TO_STD.get(team, team), "min": mins,
                            "pts": num(row, "pts"), "reb": num(row, "trb"), "ast": num(row, "ast"),
                            "fg3": num(row, "fg3"), "start": starter})
    if len(teams) != 2 or not players:
        raise ValueError(f"box {gid}: found {len(teams)} team tables, {len(players)} players")
    std = [BREF_TO_STD.get(t, t) for t in teams]
    return {"id": gid, "date": date, "away": std[0] if teams[1] == home else std[1],
            "home": BREF_TO_STD.get(home, home), "players": players}


def fetch_bref():
    state = jload(os.path.join(DATA, "state.json"), {}) or {}
    done = set(state.get("dates_done", []))
    today_et = dt.datetime.now(ET).date()
    d = dt.date.fromisoformat(SEASON_START)
    new = 0
    while d < today_et:
        ds = d.isoformat()
        recent = (today_et - d).days <= 2          # re-check the last two days for late or corrected box scores
        if ds in done and not recent:
            d += dt.timedelta(days=1)
            continue
        try:
            page = bref(f"https://www.basketball-reference.com/boxscores/?month={d.month}&day={d.day}&year={d.year}")
        except Exception as e:  # noqa: BLE001
            log("WARN box list", ds, e)
            d += dt.timedelta(days=1)
            continue
        ids = sorted(set(i for i in re.findall(r"/boxscores/(\d{9}[A-Z]{3})\.html", page) if i.startswith(d.strftime("%Y%m%d"))))
        ok = True
        for gid in ids:
            path = os.path.join(DATA, "games", gid + ".json")
            if os.path.exists(path) and not recent:
                continue
            try:
                g = parse_box(bref(f"https://www.basketball-reference.com/boxscores/{gid}.html"), gid)
                old = jload(path)
                if old != g:
                    jsave(path, g)
                    new += 1
            except Exception as e:  # noqa: BLE001
                ok = False
                log("WARN box", gid, e)
        if ok:
            done.add(ds)
        log(f"Basketball Reference {ds}: {len(ids)} games")
        d += dt.timedelta(days=1)
    state["dates_done"] = sorted(done)
    jsave(os.path.join(DATA, "state.json"), state)
    log("new or changed box scores:", new)


# ---------------- ESPN ----------------

E = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


def std(abbr):
    return ESPN_TO_STD.get(abbr, abbr)


def fetch_schedule():
    """Scoreboards from the season start to 7 days ahead. Past days are cached once every game is final."""
    today_et = dt.datetime.now(ET).date()
    d = dt.date.fromisoformat(SEASON_START)
    games = []
    while d <= today_et + dt.timedelta(days=7):
        path = os.path.join(DATA, "espn_scoreboards", d.isoformat() + ".json")
        day = jload(path)
        if day is None or (today_et - d).days <= 1:
            try:
                sb = json.loads(get(f"{E}/scoreboard?dates={d.strftime('%Y%m%d')}"))
                day = []
                for ev in sb.get("events", []):
                    if (ev.get("season") or {}).get("type") not in (2, 3, 5, None):
                        continue
                    c = ev["competitions"][0]
                    side = {x["homeAway"]: std(x["team"]["abbreviation"]) for x in c["competitors"]}
                    day.append({"id": ev["id"], "utc": ev["date"], "home": side.get("home"), "away": side.get("away"),
                                "state": ev["status"]["type"]["state"], "us_date": d.isoformat()})
                if d < today_et and day and all(g["state"] == "post" for g in day):
                    jsave(path, day)
                elif d < today_et and not day:
                    jsave(path, day)
            except Exception as e:  # noqa: BLE001
                log("WARN scoreboard", d, e)
                day = day or []
        games += day
        d += dt.timedelta(days=1)
    jsave(os.path.join(DATA, "schedule.json"), games)
    log("ESPN schedule entries:", len(games))
    return games


def fetch_rosters():
    teams = json.loads(get(f"{E}/teams"))["sports"][0]["leagues"][0]["teams"]
    out = {}
    for t in teams:
        t = t["team"]
        try:
            r = json.loads(get(f"{E}/teams/{t['id']}/roster"))
            ath = r.get("athletes", [])
            if ath and isinstance(ath[0], dict) and "items" in ath[0]:
                ath = [a for grp in ath for a in grp["items"]]
            out[std(t["abbreviation"])] = [ascii_name(a["displayName"]) for a in ath]
        except Exception as e:  # noqa: BLE001
            log("WARN roster", t["abbreviation"], e)
    if len(out) >= 28:
        jsave(os.path.join(DATA, "rosters.json"), out)
    log("rosters:", len(out), "teams,", sum(len(v) for v in out.values()), "players")


def fetch_injuries():
    j = json.loads(get(f"{E}/injuries"))
    out = []
    for team in j.get("injuries", []):
        for inj in team.get("injuries", []):
            a = inj.get("athlete") or {}
            det = inj.get("details") or {}
            out.append({"name": ascii_name(a.get("displayName", "")),
                        "team": std(((a.get("team") or {}).get("abbreviation")) or ""),
                        "status": inj.get("status", ""), "type": det.get("type", ""),
                        "return": det.get("returnDate", ""), "comment": inj.get("shortComment", ""),
                        "fs": ((det.get("fantasyStatus") or {}).get("description") or "")})
    jsave(os.path.join(DATA, "injuries.json"), out)
    log("injury report entries:", len(out))


def fetch_espn_boxes(schedule):
    """ESPN box scores for finished games, used only by verify.py."""
    n = 0
    for g in schedule:
        if g["state"] != "post":
            continue
        path = os.path.join(DATA, "espn", g["id"] + ".json")
        if os.path.exists(path):
            continue
        try:
            s = json.loads(get(f"https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={g['id']}"))
            players = []
            for tm in s["boxscore"]["players"]:
                code = std(tm["team"]["abbreviation"])
                st = tm["statistics"][0]
                keys = st["keys"]
                for a in st["athletes"]:
                    if a.get("didNotPlay") or not a.get("stats"):
                        continue
                    v = dict(zip(keys, a["stats"]))
                    def i(x):
                        try: return int(str(x).split("-")[0])
                        except Exception: return 0
                    players.append({"name": ascii_name(a["athlete"]["displayName"]), "team": code,
                                    "min": i(v.get("minutes")), "pts": i(v.get("points")), "reb": i(v.get("rebounds")),
                                    "ast": i(v.get("assists")),
                                    "fg3": i(v.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted")),
                                    "start": bool(a.get("starter"))})
            jsave(path, {"id": g["id"], "us_date": g["us_date"], "home": g["home"], "away": g["away"], "players": players})
            n += 1
        except Exception as e:  # noqa: BLE001
            log("WARN espn box", g["id"], e)
    log("new ESPN box scores:", n)


if __name__ == "__main__":
    steps = sys.argv[1:] or ["bref", "espn"]
    failed = []
    if "inj" in steps:                      # quick injury check (every 15 minutes in the afternoon/evening)
        for name, fn in (("injuries", fetch_injuries), ("schedule", fetch_schedule)):
            try: fn()
            except Exception as e:  # noqa: BLE001
                log("ERROR", name, e); failed.append(name)
    if "espn" in steps:
        for name, fn in (("rosters", fetch_rosters), ("injuries", fetch_injuries)):
            try: fn()
            except Exception as e:  # noqa: BLE001
                log("ERROR", name, e); failed.append(name)
        try:
            sched = fetch_schedule()
            fetch_espn_boxes(sched)
        except Exception as e:  # noqa: BLE001
            log("ERROR schedule", e); failed.append("schedule")
    if "bref" in steps:
        try: fetch_bref()
        except Exception as e:  # noqa: BLE001
            log("ERROR bref", e); failed.append("bref")
    with open(os.path.join(DATA, "last_fetch_log.txt"), "w") as f:
        f.write("\n".join(LOG) + "\n")
    if failed:
        sys.exit("failed: " + ", ".join(failed))
