"""Download what the daily build needs.

- Basketball Reference: every 2026-27 box score (cached, one file per game) -> data/games/
- ESPN: schedule (scoreboards), current rosters, injury report, and box scores for the fact-check.
"""
import datetime as dt, glob, html, json, os, re, sys, time, unicodedata
from zoneinfo import ZoneInfo
from config import DATA, SEASON_START, BREF_DELAY, BREF_TO_STD, ESPN_TO_STD, STD_TO_BREF
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
                            "fg3": num(row, "fg3"), "start": starter,
                            "fga": num(row, "fga"), "fta": num(row, "fta"), "tov": num(row, "tov")})
    if len(teams) != 2 or not players:
        raise ValueError(f"box {gid}: found {len(teams)} team tables, {len(players)} players")
    # USG% from the advanced box score on the same page (blank if the table or value is missing)
    usg = {}
    for m in re.finditer(r'<table[^>]*id="box-([A-Z]{3})-game-advanced"(.*?)</table>', page, re.S):
        for row in re.findall(r"<tr[^>]*>.*?</tr>", m.group(2), re.S):
            pm = re.search(r'data-stat="player"[^>]*>(?:<a[^>]*>)?([^<]+)', row)
            um = re.search(r'data-stat="usg_pct"[^>]*>(-?[\d.]+)<', row)
            if pm and um:
                usg[(BREF_TO_STD.get(m.group(1), m.group(1)), ascii_name(pm.group(1)))] = float(um.group(1))
    for p in players:
        p["usg"] = usg.get((p["team"], p["name"]))
    std = [BREF_TO_STD.get(t, t) for t in teams]
    return {"id": gid, "date": date, "away": std[0] if teams[1] == home else std[1],
            "home": BREF_TO_STD.get(home, home), "players": players}


def needs_upgrade(ds):
    """True if a stored Basketball Reference game that day predates the FGA/FTA/TOV/USG% fields."""
    for p_ in glob.glob(os.path.join(DATA, "games", ds.replace("-", "") + "*.json")):
        g = jload(p_) or {}
        if g.get("source") != "espn" and g.get("players") and "fga" not in g["players"][0]:
            return True
    return False


def fetch_bref(upgrade=True):
    state = jload(os.path.join(DATA, "state.json"), {}) or {}
    done = set(state.get("dates_done", []))
    today_et = dt.datetime.now(ET).date()
    d = dt.date.fromisoformat(SEASON_START)
    new = 0
    espn_by_gid = {}
    for p_ in glob.glob(os.path.join(DATA, "espn", "*.json")):
        e = jload(p_)
        if e:
            espn_by_gid[e["us_date"].replace("-", "") + "0" + STD_TO_BREF.get(e["home"], e["home"])] = e
    while d < today_et:
        ds = d.isoformat()
        recent = (today_et - d).days <= 2          # re-check the last two days for late or corrected box scores
        if ds in done and not recent and not (upgrade and needs_upgrade(ds)):
            d += dt.timedelta(days=1)
            continue
        try:
            page = bref(f"https://www.basketball-reference.com/boxscores/?month={d.month}&day={d.day}&year={d.year}"
                        f"&cb={int(time.time())}")       # cache-buster: B-Ref sometimes serves a stale copy
        except Exception as e:  # noqa: BLE001
            log("WARN box list", ds, e)
            d += dt.timedelta(days=1)
            continue
        ids = sorted(set(i for i in re.findall(r"/boxscores/(\d{9}[A-Z]{3})\.html", page) if i.startswith(d.strftime("%Y%m%d"))))
        # Cross-check with ESPN's finished games for that day; fetch any box score the B-Ref list page missed
        espn_day = jload(os.path.join(DATA, "espn_scoreboards", ds + ".json")) or [
            g for g in (jload(os.path.join(DATA, "schedule.json"), []) or []) if g.get("us_date") == ds]
        expected = {ds.replace("-", "") + "0" + STD_TO_BREF.get(g["home"], g["home"])
                    for g in espn_day if g.get("state") == "post"}
        if expected - set(ids):
            log(f"WARN {ds}: B-Ref list page missing {len(expected - set(ids))} finished games; fetching them directly")
        ids = sorted(set(ids) | expected)
        ok = True
        for gid in ids:
            path = os.path.join(DATA, "games", gid + ".json")
            if os.path.exists(path) and not recent and (not upgrade or "fga" in ((jload(path) or {}).get("players") or [{}])[0]):
                continue                          # (older files without FGA/FTA/TOV/USG% are re-read once)
            try:
                g = parse_box(bref(f"https://www.basketball-reference.com/boxscores/{gid}.html?cb={int(time.time())}"), gid)
                old = jload(path)
                if old != g:
                    jsave(path, g)
                    new += 1
            except Exception as e:  # noqa: BLE001
                ok = False
                log("WARN box", gid, e)
        # Fallback: any finished game Basketball Reference hasn't posted yet is filled from ESPN's box score.
        # It is replaced automatically once B-Ref posts it (the last two days are always re-checked).
        for gid in ids:
            path = os.path.join(DATA, "games", gid + ".json")
            have = jload(path)
            if have and have.get("source") != "espn":
                continue
            e = espn_by_gid.get(gid)
            if e and e.get("players"):
                g = {"id": gid, "date": ds, "away": e["away"], "home": e["home"], "source": "espn",
                     "players": [{**{k: x[k] for k in ("name", "team", "min", "pts", "reb", "ast", "fg3", "start")},
                                  **{k: x.get(k) for k in ("fga", "fta", "tov")}, "usg": None}
                                 for x in e["players"] if x.get("min", 0) > 0]}
                if have != g:
                    jsave(path, g)
                    new += 1
                    log(f"filled {gid} from ESPN (Basketball Reference not posted yet)")
        if ok:
            done.add(ds)
        log(f"Basketball Reference {ds}: {len(ids)} games")
        d += dt.timedelta(days=1)
    state["dates_done"] = sorted(done)
    jsave(os.path.join(DATA, "state.json"), state)
    log("new or changed box scores:", new)


BREF_TEAMS = ["ATL", "BOS", "BRK", "CHO", "CHI", "CLE", "DAL", "DEN", "DET", "GSW", "HOU", "IND", "LAC", "LAL", "MEM",
              "MIA", "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHO", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"]


def pos_group(p):
    """Basketball Reference position (PG, SG, SF, PF, C, or combos) -> G, F, C, G-F or F-C."""
    out = []
    for part in re.split(r"[-/ ,]+", p.strip().upper()):
        g = {"PG": "G", "SG": "G", "G": "G", "SF": "F", "PF": "F", "F": "F", "C": "C"}.get(part)
        if g and g not in out:
            out.append(g)
    out.sort(key="GFC".index)
    return "-".join(out[:2]) if out else ""


PAGE_CAP = 330


def page_pos(text):
    """'Point Guard and Shooting Guard' -> G; 'Small Forward and Power Forward' -> F; 'Power Forward and Center' -> F-C."""
    out = []
    for part in re.split(r"\s*(?:,|\band\b)\s*", text.strip()):
        p = part.lower()
        g = "G" if "guard" in p else "F" if "forward" in p else "C" if "center" in p or "centre" in p else None
        if g and g not in out:
            out.append(g)
    out = out[:2]
    out.sort(key="GFC".index)
    return "-".join(out)


def fetch_bref_rosters():
    """Positions from each team's Basketball Reference roster page -> data/rosters_bref.json.
    Every team weekly; a single team again (at most once a day) when one of its game-log players is missing."""
    path = os.path.join(DATA, "rosters_bref.json")
    rb = jload(path, {}) or {}
    today = dt.date.today().isoformat()
    teams = rb.setdefault("teams", {})
    fetched = rb.setdefault("fetched", {})
    stale = [t for t in BREF_TEAMS if not fetched.get(t) or
             (dt.date.today() - dt.date.fromisoformat(fetched[t])).days >= 7]
    known = {(p, t) for t, ps in teams.items() for p in ps}
    missing = set()
    year = int(SEASON_START[:4]) + 1
    for p_ in glob.glob(os.path.join(DATA, "games", "*.json")):
        g = jload(p_) or {}
        if g.get("source") == "espn":
            continue
        for pl in g.get("players", []):
            if (pl["name"], pl["team"]) not in known:
                missing.add(STD_TO_BREF.get(pl["team"], pl["team"]))
    todo = sorted(set(stale) | {t for t in missing if fetched.get(t) != today})
    for t in todo:
        try:
            page = bref(f"https://www.basketball-reference.com/teams/{t}/{year}.html?cb={int(time.time())}")
            m = re.search(r'<table[^>]*id="roster"(.*?)</table>', page, re.S)
            if not m:
                raise ValueError("no roster table")
            ps = {}
            for row in re.findall(r"<tr[^>]*>.*?</tr>", m.group(1), re.S):
                pm = re.search(r'data-stat="player"[^>]*>(?:<a[^>]*>)?([^<]+)', row)
                qm = re.search(r'data-stat="pos"[^>]*>([^<]*)<', row)
                im = re.search(r'href="/players/[a-z]/([a-z0-9]+)\.html"', row)
                if pm and qm and pos_group(qm.group(1)):
                    nm = ascii_name(pm.group(1)).replace(" (TW)", "").strip()
                    ps[nm] = pos_group(qm.group(1))
                    if im:
                        rb.setdefault("ids", {})[nm] = im.group(1)
            if not ps:
                raise ValueError("roster table empty")
            teams[BREF_TO_STD.get(t, t)] = ps
            fetched[t] = today
        except Exception as e:  # noqa: BLE001
            log("WARN roster", t, e)
    # Fuller positions from each player's own page ("Shooting Guard and Small Forward" -> G-F), cached forever;
    # at most PAGE_CAP new pages a run (about 20 minutes), so the first fill takes two runs.
    ppath = os.path.join(DATA, "positions_bref.json")
    pcache = jload(ppath, {}) or {}
    ids = rb.get("ids", {})
    todo_p = [pid for t, ps in teams.items() for n in ps for pid in [ids.get(n)] if pid and pid not in pcache]
    for pid in todo_p[:PAGE_CAP]:
        try:
            page = bref(f"https://www.basketball-reference.com/players/{pid[0]}/{pid}.html")
            m = re.search(r"Position:\s*</strong>\s*([^<]+?)\s*(?:&#9642;|\u25aa|<)", page)
            pcache[pid] = page_pos(m.group(1)) if m else ""
        except Exception as e:  # noqa: BLE001
            log("WARN player page", pid, e)
    jsave(ppath, pcache)
    for t, ps in teams.items():
        for n in ps:
            full = pcache.get(ids.get(n) or "")
            if full:
                ps[n] = full
    jsave(path, rb)
    log(f"Basketball Reference rosters: {len(todo)} teams refreshed, {min(len(todo_p), PAGE_CAP)} player pages "
        f"read ({max(0, len(todo_p) - PAGE_CAP)} left)")


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


TEAM_NAMES = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET", "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "LA Clippers": "LAC", "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS"}
STATUSES = "Out|Doubtful|Questionable|Probable|Available"


def latest_official_report_url():
    """Newest official NBA injury report PDF (published every 15 minutes on game days)."""
    try:
        page = get("https://official.nba.com/nba-injury-report-2026-27/").decode("utf8", "replace")
        links = re.findall(r"https://ak-static\.cms\.nba\.com/referee/injury/Injury-Report_[0-9_\-]+(?:AM|PM)\.pdf", page)
        if links:
            def when(u):
                m = re.search(r"_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)", u)
                return dt.datetime.strptime(" ".join(m.groups()), "%Y-%m-%d %I %M %p")
            return max(set(links), key=when)
    except Exception as e:  # noqa: BLE001
        log("WARN official report page", e)
    now = dt.datetime.now(ET)                       # fall back to guessing the newest 15-minute slot
    t = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    for i in range(96):
        s = t - dt.timedelta(minutes=15 * i)
        u = f"https://ak-static.cms.nba.com/referee/injury/Injury-Report_{s:%Y-%m-%d}_{s:%I_%M%p}.pdf"
        try:
            get(u, tries=1, timeout=15)
            return u
        except Exception:  # noqa: BLE001
            continue
    return None


def flip_name(n):
    """'Jackson Jr., Jaren' / 'NanceJr.,Larry' / 'Udeh,Jr.,Ernest' -> 'Jaren Jackson Jr.' style."""
    parts = [x.strip() for x in n.split(",") if x.strip()]
    if len(parts) < 2:
        return n.strip()
    first = parts[-1]
    last = " ".join(parts[:-1])
    suffix = ""
    m = re.match(r"(.*?)\s*(Jr\.?|Sr\.?|II|III|IV|V)$", last)
    if m and m.group(1):
        last, suffix = m.group(1), " " + m.group(2)
    return f"{first} {last}{suffix}"


def fetch_official_injuries():
    import io
    import pdfplumber
    url = latest_official_report_url()
    if not url:
        raise RuntimeError("no official injury report found")
    pdf = pdfplumber.open(io.BytesIO(get(url)))
    teams = {n.replace(" ", ""): c for n, c in TEAM_NAMES.items()}
    stat = set(STATUSES.split("|"))
    out, date, team = [], None, None
    for page in pdf.pages:
        toks = [w["text"] for w in page.extract_words()]
        for i, t in enumerate(toks):
            if re.fullmatch(r"\d{2}/\d{2}/\d{4}", t):
                date = dt.datetime.strptime(t, "%m/%d/%Y").date().isoformat()
            elif t in teams:
                team = teams[t]
            elif "," in t and i + 1 < len(toks) and toks[i + 1] in stat and team and date:
                nxt = toks[i + 2] if i + 2 < len(toks) else ""
                reason = nxt if re.match(r"(Injury|GLeague|League|Rest|Personal|Not|Health)", nxt) else ""
                out.append({"name": ascii_name(flip_name(t)), "team": team, "status": toks[i + 1],
                            "reason": reason, "game_date": date})
    if not out:
        with open(os.path.join(DATA, "official_debug.txt"), "w") as f:
            f.write(url + "\n")
            for page in pdf.pages[:2]:
                f.write((page.extract_text() or "") + "\n=====\n")
                f.write(json.dumps([w["text"] for w in page.extract_words()][:200]) + "\n=====\n")
        # Normal overnight: once the night's games are over, the report can list nobody. Not an error;
        # keep the last good list (old game dates are ignored by build.py) and fall back to ESPN.
        log("official report lists no players for upcoming games yet:", url.rsplit("/", 1)[-1])
        return
    out.sort(key=lambda o: (o["game_date"], o["team"], o["name"]))
    jsave(os.path.join(DATA, "injuries_official.json"), {"players": out})   # only changes when a status changes
    with open(os.path.join(DATA, "injuries_official_source.txt"), "w") as f:
        f.write(url + "\n")
    log("official injury report:", url.rsplit("/", 1)[-1], len(out), "players")


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
                    def i(x, part=0):
                        try: return int(str(x).split("-")[part])
                        except Exception: return 0
                    players.append({"name": ascii_name(a["athlete"]["displayName"]), "team": code,
                                    "min": i(v.get("minutes")), "pts": i(v.get("points")), "reb": i(v.get("rebounds")),
                                    "ast": i(v.get("assists")),
                                    "fg3": i(v.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted")),
                                    "start": bool(a.get("starter")),
                                    "fga": i(v.get("fieldGoalsMade-fieldGoalsAttempted"), 1),
                                    "fta": i(v.get("freeThrowsMade-freeThrowsAttempted"), 1),
                                    "tov": i(v.get("turnovers"))})
            jsave(path, {"id": g["id"], "us_date": g["us_date"], "home": g["home"], "away": g["away"], "players": players})
            n += 1
        except Exception as e:  # noqa: BLE001
            log("WARN espn box", g["id"], e)
    log("new ESPN box scores:", n)


if __name__ == "__main__":
    steps = sys.argv[1:] or ["bref", "espn"]
    failed = []
    if "inj" in steps:                      # quick injury check (every 15 minutes in the afternoon/evening)
        for name, fn in (("injuries", fetch_injuries), ("official injuries", fetch_official_injuries),
                         ("schedule", fetch_schedule)):
            try: fn()
            except Exception as e:  # noqa: BLE001
                log("ERROR", name, e); failed.append(name)
    if "missing" in steps:                  # injury runs: pull box scores for any finished game not loaded yet
        try:
            today = dt.datetime.now(ET).date().isoformat()
            sched = jload(os.path.join(DATA, "schedule.json"), []) or []
            want = {g["us_date"].replace("-", "") + "0" + STD_TO_BREF.get(g["home"], g["home"])
                    for g in sched if g.get("state") == "post" and SEASON_START <= g["us_date"] <= today}
            have = {f[:-5] for f in os.listdir(os.path.join(DATA, "games"))}
            if want - have:
                log("finished games not loaded yet:", len(want - have), "- fetching box scores")
                fetch_espn_boxes(sched)
                fetch_bref(upgrade=False)          # the one-off re-read of older games is left to the daily run
            else:
                log("all finished games loaded")
        except Exception as e:  # noqa: BLE001
            log("ERROR missing games", e); failed.append("missing games")
    if "espn" in steps:
        for name, fn in (("rosters", fetch_rosters), ("injuries", fetch_injuries),
                         ("official injuries", fetch_official_injuries)):
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
        try: fetch_bref_rosters()
        except Exception as e:  # noqa: BLE001
            log("ERROR bref rosters", e); failed.append("bref rosters")
    with open(os.path.join(DATA, "last_fetch_log.txt"), "w") as f:
        f.write("\n".join(LOG) + "\n")
    if failed:
        sys.exit("failed: " + ", ".join(failed))
