"""Context tab for the NBA Master: absences, "without X" splits, projected starters, roles, usage,
matchups (with ranks by position) and schedule for every game on the next slate.

  python scripts/context.py morning        build after the daily update, save the morning statuses, push
  python scripts/context.py status-if-due  pre-tip refresh: runs at first tip minus 60 min (and again before
                                           later games that start 2+ hours after the first), re-reading only
                                           the injury statuses; marks anything changed since the morning
  python scripts/context.py build          build out/CONTEXT.json only (no push)

Reads only box scores already downloaded (data/games), Basketball Reference positions (data/rosters_bref.json)
and the injury statuses used by the Master tab. Blank where a number can't be found.
"""
import datetime as dt, json, os, re, sys
from collections import defaultdict
from zoneinfo import ZoneInfo
import build
from build import load, key, pool, team_info, uk
from common import jload, jsave
from config import DATA, OUT

UK = ZoneInfo("Europe/London")
ET = ZoneInfo("America/New_York")
MASTER = "1H74LsbUfLAbgsEJxoyIdvcNHqLsWXJBPys8ugJrNiWo"
TAB = "Context"
NCOL = 10
MORNING = os.path.join(DATA, "context_morning.json")
RUNS = os.path.join(DATA, "context_status_runs.json")

# colours from the mock
INK, GREY, BAR, BAND, HEAD = "#1d1d1f", "#545454", "#111111", "#f5f5f7", "#e8e8ec"
GOOD_BG, GOOD_FG, BAD_BG, BAD_FG = "#bcebc5", "#0e4d21", "#fbe8e6", "#a40e0e"
RED, ORANGE, UP, DOWN, YELLOW = "#d92f24", "#e87009", "#1e8e3d", "#c0392b", "#fff2cc"


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def f1(x):
    return "" if x is None else f"{x:.1f}"


def short(x):
    """39 / 8 / 5 style: one decimal, dropped when whole."""
    if x is None:
        return ""
    x = round(x, 1)
    return str(int(x)) if x == int(x) else f"{x:.1f}"


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ---------------- slate and statuses ----------------

def pick_slate(sched, now):
    """Games on the current US (Eastern) date, or the next date that has games still to play."""
    today = now.astimezone(ET).date().isoformat()
    dates = sorted({g["us_date"] for g in sched if g["us_date"] >= today})
    for d in dates:
        gs = [g for g in sched if g["us_date"] == d]
        if any(g["state"] != "post" for g in gs):
            return d, sorted(gs, key=lambda g: (g["utc"], g["home"]))
    return None, []


def tip_groups(games):
    """Start times grouped: a new group when a game starts 2+ hours after the group's first tip."""
    groups = []
    for g in games:
        t = uk(g["utc"])
        if not groups or t - groups[-1][0] > dt.timedelta(hours=2):
            groups.append([t, []])
        groups[-1][1].append(g)
    return groups


def reason_text(e):
    raw = (e.get("oreason") or "").replace("Injury/Illness-", "").replace("Injury/Illness - ", "")
    raw = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw).split(";")[0].strip()
    return e.get("type") or raw


def statuses(inj, slate, teams):
    """{player key: (status, label)} for tonight's teams. Teams on the official NBA report for the slate date use
    it; others fall back to ESPN. Out/Doubtful/Questionable (+ ESPN day-to-day). G League assignments left out."""
    off = (jload(os.path.join(DATA, "injuries_official.json"), {}) or {}).get("players", [])
    official_teams = {o["team"] for o in off if o.get("game_date") == slate}
    out = {}
    for k, e in inj.items():
        team = e.get("team")
        if team not in teams:
            continue
        if team in official_teams:
            if e.get("official_date") != slate:
                continue
            st = e.get("official")
            if "gleague" in (e.get("oreason") or "").lower().replace(" ", ""):
                continue
        else:
            s, fs = (e.get("status") or ""), (e.get("fs") or "").lower()
            if s.lower().startswith("out") or fs == "out" or s.lower() == "suspension":
                st = "Out"
            elif fs in ("doubtful", "questionable"):
                st = fs.title()
            elif "day" in s.lower():
                st = "Day-to-day"
            else:
                st = None
        if st not in ("Out", "Doubtful", "Questionable", "Day-to-day"):
            continue
        why = reason_text(e) or ("Suspension" if (e.get("status") or "").lower() == "suspension" else "")
        out[k] = (st, f"{st} ({why})" if why else st, team)
    return out


# ---------------- numbers ----------------

class Data:
    def __init__(self):
        self.games, self.logs, self.names, self.h2, self.roster_team, self.inj, self.sched = load()
        build.NAMES = self.names
        rb = jload(os.path.join(DATA, "rosters_bref.json"), {}) or {}
        self.pos = {}
        for t, ps in rb.get("teams", {}).items():
            for n, p in ps.items():
                self.pos[key(n)] = p
        self.team_games = defaultdict(list)            # team -> [game] oldest first
        for g in self.games:
            for t in (g["home"], g["away"]):
                self.team_games[t].append(g)
        self.cur = {k: team_info(k, self.logs, self.roster_team)[0] for k in set(self.logs) | set(self.roster_team)}
        self.listed = set(pool(self.logs, self.h2, self.roster_team))

    def tlog(self, k, team=None):
        """Player's games for his current team (or `team`)."""
        team = team or self.cur.get(k)
        return [r for r in self.logs.get(k, []) if r["team"] == team]

    def played(self, k, team):
        return {r["gid"] for r in self.tlog(k, team)}

    # ---- matchup ranks ----
    def defence(self):
        """team -> {stat: (allowed per game, rank)}; 1st = allows the most."""
        tot = defaultdict(lambda: defaultdict(float))
        n = defaultdict(int)
        for g in self.games:
            pts = defaultdict(int)
            for p in g["players"]:
                pts[p["team"]] += p["pts"]
            for t in (g["home"], g["away"]):
                n[t] += 1
                tot[t]["GT"] += pts[g["home"]] + pts[g["away"]]
            for p in g["players"]:
                d = g["home"] if p["team"] == g["away"] else g["away"]
                for st, v in (("PTS", p["pts"]), ("REB", p["reb"]), ("AST", p["ast"]), ("3PM", p["fg3"])):
                    tot[d][st] += v
                pos = self.pos.get(key(p["name"]), "")
                parts = pos.split("-") if pos else []
                for part in parts:
                    w = 1 / len(parts)
                    for st, v in (("PTS", p["pts"]), ("REB", p["reb"]), ("AST", p["ast"])):
                        tot[d][part + st] += w * v
        stats = ["PTS", "REB", "AST", "3PM", "GT"] + [p + s for p in "GFC" for s in ("PTS", "REB", "AST")]
        res = defaultdict(dict)
        for st in stats:
            vals = {t: tot[t][st] / n[t] for t in n if n[t]}
            if st[0] in "GFC" and len(st) > 3 and not self.pos:
                continue                                  # no positions yet -> blank
            for t, v in vals.items():
                res[t][st] = (v, 1 + sum(1 for u in vals.values() if u > v + 1e-9))
        return res

    # ---- per player ----
    def season(self, k, team=None):
        lg = self.tlog(k, team)
        if not lg:
            return None
        return {"n": len(lg), "min": mean([r["min"] for r in lg]), "pts": mean([r["s"][0] for r in lg]),
                "reb": mean([r["s"][1] for r in lg]), "ast": mean([r["s"][2] for r in lg]),
                "fg3": mean([r["s"][3] for r in lg])}

    def games_missed(self, k, team):
        """Team games in a row since the player last played for the team; None = not played for them this season."""
        mine = self.tlog(k, team)
        if not mine:
            return None
        last = mine[-1]["gid"]
        ids = [g["id"] for g in self.team_games[team]]
        return len(ids) - 1 - ids.index(last) if last in ids else None

    def without(self, x, team, out_keys):
        """Teammate splits with / without player x (current team only)."""
        xg = self.played(x, team)
        tg = self.team_games[team]
        other = [r for r in self.logs.get(x, []) if r["team"] != team]
        if other:                                         # joined mid-season: only games since joining
            first = min(r["date"] for r in self.tlog(x, team)) if xg else "9"
            tg = [g for g in tg if g["date"] >= first]
        without_ids = {g["id"] for g in tg} - xg
        if not without_ids:
            return []
        rows = []
        mates = {k for k, c in self.cur.items() if c == team and k != x and k not in out_keys}
        for k in mates:
            lg = [r for r in self.tlog(k, team) if r["gid"] in {g["id"] for g in tg}]
            w = [r for r in lg if r["gid"] in xg]
            wo = [r for r in lg if r["gid"] in without_ids]
            if not w or not wo:
                continue
            a = {s: (mean([f(r) for r in w]), mean([f(r) for r in wo])) for s, f in (
                ("min", lambda r: r["min"]), ("pts", lambda r: r["s"][0]), ("reb", lambda r: r["s"][1]),
                ("ast", lambda r: r["s"][2]), ("fg3", lambda r: r["s"][3]), ("usg", lambda r: r.get("usg")),
                ("pra", lambda r: sum(r["s"][:3])))}
            dmin = a["min"][1] - a["min"][0]
            dpra = a["pra"][1] - a["pra"][0]
            if not (abs(dmin) >= 3 or abs(dpra) >= 5):
                continue
            if max(a["min"]) < 12:
                continue
            st = (sum(1 for r in w if r["start"]), len(w), sum(1 for r in wo if r["start"]), len(wo))
            rows.append((k, len(wo), a, st, dmin))
        rows = sorted(rows, key=lambda r: (r[1] < 3, -abs(r[4])))[:6]     # 3+ game samples first
        return sorted(rows, key=lambda r: (r[1] < 3, -r[4]))

    def projected(self, team, out_keys):
        """Most recent starting five, with anyone out or doubtful swapped for the teammate who started most often
        in games without him (else the bench player with the most minutes)."""
        tg = self.team_games[team]
        if not tg:
            return []
        # Base five = the players who started most of the team's last 5 games (ties: most recent start, then
        # minutes), so one rest-day lineup doesn't decide it. Traded-away players are skipped.
        recent = tg[-5:]
        cnt0 = defaultdict(lambda: [0, "", 0.0])
        for g in recent:
            for p in g["players"]:
                q = key(p["name"])
                if p["team"] == team and p["start"] and self.cur.get(q) == team:
                    cnt0[q][0] += 1
                    cnt0[q][1] = max(cnt0[q][1], g["date"])
                    cnt0[q][2] += p["min"]
        five = sorted(cnt0, key=lambda q: (cnt0[q][0], cnt0[q][1], cnt0[q][2]), reverse=True)[:5]
        res = []
        used = set(five)
        for k in five:
            if k not in out_keys:
                res.append((k, None))
                continue
            xg = self.played(k, team)
            wo = [g for g in tg if g["id"] not in xg]
            cnt = defaultdict(lambda: [0, 0.0])
            for g in wo:
                for p in g["players"]:
                    q = key(p["name"])
                    if p["team"] == team and p["start"] and q not in used and q not in out_keys \
                            and self.cur.get(q) == team:
                        cnt[q][0] += 1
                        cnt[q][1] += p["min"]
            if cnt:
                sub = max(cnt, key=lambda q: (cnt[q][0], cnt[q][1]))
            else:
                bench = [q for q, c in self.cur.items() if c == team and q not in used and q not in out_keys
                         and self.tlog(q, team)]
                sub = max(bench, key=lambda q: self.season(q, team)["min"]) if bench else None
            if sub:
                used.add(sub)
            res.append((sub, k))
        return res


# ---------------- sheet layout ----------------

class Sheet:
    def __init__(self):
        self.rows, self.fmt, self.merges = [], [], []

    def add(self, vals, **f):
        r = len(self.rows)
        self.rows.append([("" if v is None else v) for v in vals] + [""] * (NCOL - len(vals)))
        if f:
            self.style(r, 0, NCOL, **f)
        return r

    def style(self, r, c0, c1, **f):
        self.fmt.append((r, c0, c1, f))

    def merge(self, r, c0, c1):
        self.merges.append((r, c0, c1))

    def header(self, title, cols):
        r = self.add([title] + cols, bg=HEAD, bold=True)
        return r


def build_context(mode="morning", now=None):
    now = now or dt.datetime.now(UK)
    D = Data()
    slate, games = pick_slate(D.sched, now)
    S = Sheet()
    last_box = max((g["date"] for g in D.games), default=None)
    day = dt.date.fromisoformat(slate).strftime("%a %-d %b") if slate else ""
    S.add([f"HitRateHub - Tonight's context ({day})"], bold=True, size=15)
    S.add([f"Absences, who gains minutes, roles, usage, matchups and schedule for every game on the slate. "
           f"Box scores up to {dt.date.fromisoformat(last_box).strftime('%-d %b') if last_box else 'n/a'}. "
           f"Statuses updated {now.strftime('%H:%M')} UK. Times are UK."], fg=GREY)
    S.add(["Ranks: 1st = allows the most in the NBA (good for overs); 1st-5th green, 26th-30th red. Role: starts in "
           "the last 5. Trend: last-5 minutes vs season (3+ = rising/falling). Usage = USG% (Basketball Reference). "
           "Without tables: grey rows come from under 3 games. Projected starters (most starts in the last 5, minus anyone out "
           "or doubtful) are not confirmed."], fg=GREY)
    for r in range(3):
        S.merge(r, 0, NCOL)
    if not games:
        S.add(["No games on the schedule."])
        return S, {}, slate
    teams = {t for g in games for t in (g["home"], g["away"])}
    st = statuses(D.inj, slate, teams)
    morning = jload(MORNING, {}) or {}
    morning = morning if morning.get("slate") == slate and mode != "morning" else None
    out_keys = {k for k, v in st.items() if v[0] in ("Out", "Doubtful")}
    really_out = {k for k, v in st.items() if v[0] == "Out"}
    dfn = D.defence()
    snap = {"slate": slate, "status": {D.names.get(k, k): v[1] for k, v in st.items()}, "projected": {}}
    slate_date = dt.date.fromisoformat(slate)

    def rank_cell(r, c, team, stat, digits=1):
        v = dfn.get(team, {}).get(stat)
        if not v:
            return ""
        val, rk = v
        txt = f"{val:.0f} ({ordinal(rk)})" if stat == "GT" else f"{val:.{digits}f} ({ordinal(rk)})"
        if rk <= 5:
            S.style(r, c, c + 1, bg=GOOD_BG, fg=GOOD_FG, bold=True)
        elif rk >= 26:
            S.style(r, c, c + 1, bg=BAD_BG, fg=BAD_FG)
        return txt

    for g in games:
        away, home = g["away"], g["home"]
        S.add([])
        r = S.add([f"{away} @ {home}  -  {uk(g['utc']).strftime('%H:%M')} UK"], bg=BAR, fg="#ffffff", bold=True)
        S.merge(r, 0, NCOL)

        # schedule
        def rest(t):
            prev = [x["date"] for x in D.team_games[t] if x["date"] < slate]
            if not prev:
                return "first game"
            d = (slate_date - dt.date.fromisoformat(prev[-1])).days - 1
            return "back-to-back" if d == 0 else f"{d} day{'s' if d != 1 else ''} rest"
        r = S.add(["Schedule", f"{away}: {rest(away)} (away)  ·  {home}: {rest(home)} (home)"], bg=BAND, bold=True)
        S.merge(r, 1, NCOL)

        # matchup
        S.header("Matchup", ["Opponent allows", "Points", "Rebounds", "Assists", "Threes", "Game total (avg)"])
        for att, dfd in ((away, home), (home, away)):
            r = S.add([f"{att} attack", f"{dfd} defence"])
            S.rows[r][2:7] = [rank_cell(r, c, dfd, s) for c, s in ((2, "PTS"), (3, "REB"), (4, "AST"), (5, "3PM"), (6, "GT"))]
        S.header("By position", ["Opponent allows", "Points", "Rebounds", "Assists"])
        for att, dfd in ((away, home), (home, away)):
            for p, nm in (("G", "guards"), ("F", "forwards"), ("C", "centres")):
                r = S.add([f"{att} {nm}", f"{dfd} defence"])
                S.rows[r][2:5] = [rank_cell(r, c, dfd, p + s) for c, s in ((2, "PTS"), (3, "REB"), (4, "AST"))]

        # absences
        ab = [(k, v) for k, v in st.items() if v[2] in (away, home)]
        gone = []
        if morning:
            names_now = {D.names.get(k, k) for k, _ in ab}
            gone = [n for n, lab in morning["status"].items() if n not in names_now
                    and D.cur.get(key(n)) in (away, home)]
        S.header("Absences", ["Team", "Status", "Games missed", "Season min", "Season pts", "Since morning"])
        def sk(item):
            s = D.season(item[0], item[1][2])
            return -(s["min"] if s else -1)
        for k, (stt, lab, team) in sorted(ab, key=sk):
            s = D.season(k, team)
            gm = D.games_missed(k, team)
            col = RED if stt == "Out" else ORANGE
            name = D.names.get(k, k)
            gm_txt = "all season" if gm is None else (f"{gm} (news)" if gm <= 2 else str(gm))
            r = S.add([name, team, lab, gm_txt, f1(s["min"]) if s else "-", f1(s["pts"]) if s else "-"])
            S.style(r, 0, 3, fg=col, bold=True)
            if gm is not None and gm <= 2:
                S.style(r, 3, 4, fg=RED, bold=True)
            was = morning["status"].get(name) if morning else None
            if morning and (was or "").split(" (")[0] != lab.split(" (")[0]:     # status change, not wording
                S.rows[r][6] = "changed" + ("" if name in morning["status"] else " (new)")
                S.style(r, 6, 7, bg=YELLOW, bold=True)
        for n in gone:
            r = S.add([n, D.cur.get(key(n)), "Not on report now", "", "", "", f"changed (was {morning['status'][n]})"])
            S.style(r, 6, 7, bg=YELLOW, bold=True)
        if not ab and not gone:
            S.add(["None listed"])

        # projected starters
        S.header("Projected starters", ["Team", "Lineup (projected - not confirmed)"])
        for t in (away, home):
            pj = D.projected(t, out_keys)
            txt = "  ·  ".join(D.names.get(k, k) + (f" (for {D.names.get(was, was)})" if was else "")
                               if k else f"? (for {D.names.get(was, was)})" for k, was in pj)
            snap["projected"][t] = txt
            r = S.add(["Projected", t, txt])
            S.merge(r, 2, NCOL)
            if morning and morning.get("projected", {}).get(t) not in (None, txt):
                S.rows[r][0] = "Projected - changed"
                S.style(r, 0, 1, bg=YELLOW, bold=True)

        # without X
        for k, (stt, lab, team) in sorted(ab, key=sk):
            s = D.season(k, team)
            if stt not in ("Out", "Doubtful") or not s or s["min"] < 20:
                continue
            rows = D.without(k, team, really_out)
            S.header(f"Without {D.names.get(k, k)}", ["Games", "Minutes", "Points", "Rebounds", "Assists", "Threes",
                                                       "Starts", "Usage"])
            if not rows:
                S.add(["No teammate changes past the thresholds (or no games without him)"], fg=GREY)
                continue
            for q, n, a, sts, dmin in rows:
                arrow = "▲" if dmin > 0 else "▼"
                r = S.add([f"{D.names.get(q, q)} {arrow}", n] +
                          [f"{f1(a[s][0])} → {f1(a[s][1])}" for s in ("min", "pts", "reb", "ast", "fg3")] +
                          [f"{sts[0]}/{sts[1]} → {sts[2]}/{sts[3]}",
                           f"{f1(a['usg'][0])} → {f1(a['usg'][1])}" if a["usg"][0] is not None and a["usg"][1] is not None else ""])
                if n < 3:                               # small sample: greyed out
                    S.style(r, 0, NCOL, fg="#9a9a9f")
                else:
                    S.style(r, 0, 1, fg=UP if dmin > 0 else DOWN, bold=True)

        # players
        S.header("Players", ["Team", "Role", "Min season", "Min last 5", "Trend", "Usage season", "Usage last 5",
                             "vs opp (games)", "vs opp pts/reb/ast"])
        for t, opp in ((away, home), (home, away)):
            ks = [k for k in D.listed if D.cur.get(k) == t and k not in really_out and D.tlog(k, t)]
            ks.sort(key=lambda k: -D.season(k, t)["min"])
            for k in ks:
                lg = D.tlog(k, t)
                l5 = lg[-5:]
                if all(r["start"] is not None for r in l5):
                    n5 = sum(1 for r in l5 if r["start"])
                    role = f"{'Starter' if n5 * 2 > len(l5) else 'Bench'} {n5}/{len(l5)}"
                else:
                    m = mean([r["min"] for r in l5])
                    role = "Starter" if m >= 28 else "Rotation" if m >= 18 else "Bench"
                ms, m5 = mean([r["min"] for r in lg]), mean([r["min"] for r in l5])
                trend = "Rising" if m5 - ms >= 3 else "Falling" if m5 - ms <= -3 else "Stable"
                vs = [r for r in lg if r["opp"] == opp]
                tag = {"Doubtful": " (D)", "Questionable": " (Q)", "Day-to-day": " (DTD)"}.get(st.get(k, ("",))[0], "")
                r = S.add([D.names.get(k, k) + tag, t, role, f1(ms), f1(m5), trend,
                           f1(mean([x.get("usg") for x in lg])), f1(mean([x.get("usg") for x in l5])), len(vs),
                           " / ".join(short(mean([x["s"][i] for x in vs])) for i in range(3)) if vs else "-"])
                if trend != "Stable":
                    S.style(r, 5, 6, fg=UP if trend == "Rising" else DOWN, bold=True)
    return S, snap, slate


# ---------------- push ----------------

def rgb(h):
    return {"red": int(h[1:3], 16) / 255, "green": int(h[3:5], 16) / 255, "blue": int(h[5:7], 16) / 255}


def push(S):
    key_ = os.environ.get("GOOGLE_SA_JSON")
    if not key_:
        print("GOOGLE_SA_JSON not set; skipping Context push")
        return
    import gspread
    gc = gspread.service_account_from_dict(json.loads(key_))
    book = gc.open_by_key(MASTER)
    n = len(S.rows) + 20
    try:
        ws = book.worksheet(TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws = book.add_worksheet(TAB, rows=n, cols=NCOL)
    sid = ws.id
    widths = [220, 118, 175, 118, 118, 118, 118, 118, 100, 130]
    reqs = [
        {"unmergeCells": {"range": {"sheetId": sid}}},
        {"updateCells": {"range": {"sheetId": sid}, "fields": "userEnteredValue,userEnteredFormat"}},
        {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {
            "rowCount": n, "columnCount": NCOL, "frozenRowCount": 3, "hideGridlines": True}},
            "fields": "gridProperties(rowCount,columnCount,frozenRowCount,hideGridlines)"}},
    ]
    reqs += [{"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": i,
              "endIndex": i + 1}, "properties": {"pixelSize": w}, "fields": "pixelSize"}} for i, w in enumerate(widths)]
    book.batch_update({"requests": reqs})
    ws.update(S.rows, "A1", value_input_option="RAW")
    reqs = [{"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": len(S.rows),
             "startColumnIndex": 0, "endColumnIndex": NCOL},
             "cell": {"userEnteredFormat": {"textFormat": {"foregroundColor": rgb(INK), "fontSize": 10},
                                            "verticalAlignment": "MIDDLE"}},
             "fields": "userEnteredFormat(textFormat,verticalAlignment)"}},
            {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 3, "endRowIndex": len(S.rows),
             "startColumnIndex": 1, "endColumnIndex": NCOL},
             "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
             "fields": "userEnteredFormat.horizontalAlignment"}}]
    for r, c0, c1, f in S.fmt:
        uf, fields, tf, tfields = {}, [], {}, []
        if "bg" in f:
            uf["backgroundColor"] = rgb(f["bg"]); fields.append("backgroundColor")
        if "fg" in f:
            tf["foregroundColor"] = rgb(f["fg"]); tfields.append("foregroundColor")
        if f.get("bold"):
            tf["bold"] = True; tfields.append("bold")
        if "size" in f:
            tf["fontSize"] = f["size"]; tfields.append("fontSize")
        if tf:
            uf["textFormat"] = tf
            fields += [f"textFormat.{x}" for x in tfields]
        reqs.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": r, "endRowIndex": r + 1,
                     "startColumnIndex": c0, "endColumnIndex": c1}, "cell": {"userEnteredFormat": uf},
                     "fields": "userEnteredFormat(" + ",".join(fields) + ")"}})
    for r, c0, c1 in S.merges:
        reqs.append({"mergeCells": {"range": {"sheetId": sid, "startRowIndex": r, "endRowIndex": r + 1,
                     "startColumnIndex": c0, "endColumnIndex": c1}, "mergeType": "MERGE_ALL"}})
    for i in range(0, len(reqs), 400):
        book.batch_update({"requests": reqs[i:i + 400]})
    print(f"Context -> {len(S.rows)} rows, {len(S.fmt)} formats")


def save_out(S):
    os.makedirs(OUT, exist_ok=True)
    jsave(os.path.join(OUT, "CONTEXT.json"), {"rows": S.rows, "fmt": S.fmt, "merges": S.merges})


def due_targets(now):
    """Pre-tip refresh targets for the slate (UK times): first tip - 60 min, plus each later group 2+ h after."""
    D_sched = jload(os.path.join(DATA, "schedule.json"), []) or []
    slate, games = pick_slate(D_sched, now)
    return slate, [(t - dt.timedelta(minutes=60), t) for t, _ in tip_groups(games)]


def main():
    mode = (sys.argv[1:] or ["build"])[0]
    now = dt.datetime.now(UK)
    if mode == "status-if-due":
        slate, targets = due_targets(now)
        runs = jload(RUNS, {}) or {}
        done = runs.get(slate, [])
        due = [a for a, tip in targets if a - dt.timedelta(minutes=15) <= now < tip and a.strftime("%H:%M") not in done]
        if not due:
            print("No pre-tip status refresh due", [(a.strftime("%H:%M"), t.strftime("%H:%M")) for a, t in targets])
            return
        S, snap, slate = build_context("status", now)
        save_out(S)
        push(S)
        runs = {slate: done + [a.strftime("%H:%M") for a in due]}
        jsave(RUNS, runs)
        print("Pre-tip status refresh done for", [a.strftime("%H:%M") for a in due])
        return
    S, snap, slate = build_context("morning" if mode == "morning" else "status", now)
    save_out(S)
    if mode == "morning":
        jsave(MORNING, snap)
        push(S)
    print(f"Context built for {slate}: {len(S.rows)} rows")


if __name__ == "__main__":
    main()
