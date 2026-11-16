"""Master table for the paid tier sheets (2026-27 games only).

One row per listed player. For every line: last 5, last 10, season, true rate, home, away,
second night of a back-to-back, and vs the next opponent. Tier sheets pick the columns they sell.
Writes out/MASTER_2627.csv (rows) and returns them for push_sheets.py.
"""
import datetime as dt, os
import build
from common import jload
from config import DATA
from build import load, base_rates, next_games, pool, records, team_info, status_text, pct, write_csv, nz
from config import LINES, TRUE_K

PRA = [20, 25, 30, 35, 40]
ALL_LINES = [(st, t) for st, t, _ in LINES] + [("PRA", t) for t in PRA]
WINDOWS = ["L5", "L10", "Season", "True", "Home", "Away", "B2B", "vsOpp"]


def val(s, st):
    return s[0] + s[1] + s[2] if st == "PRA" else s[{"PTS": 0, "REB": 1, "AST": 2, "3PM": 3}[st]]


def pra_base(logs):
    n, hits = 0, {t: 0 for t in PRA}
    for lg in logs.values():
        for r in lg:
            n += 1
            for t in PRA:
                hits[t] += val(r["s"], "PRA") >= t
    return {("PRA", t): hits[t] / n for t in PRA} if n else {}


def rows():
    games, logs, names, h2, roster_team, inj, sched = load()
    build.NAMES = names
    base = base_rates(logs, h2)
    base.update(pra_base(logs))
    nxt = next_games(sched)
    keep = sorted(pool(logs, h2, roster_team), key=lambda k: names.get(k, k))
    head = ["Player", "Team", "Status", "Next game", "Next opp", "GP", "MPG", "PPG", "RPG", "APG", "3PM/G", "PRA/G"]
    head += [f"{w}: {st} {t}+" for w in WINDOWS for st, t in ALL_LINES]
    out = [head]
    for k in keep:
        lg = logs.get(k, [])
        cur, team_txt = team_info(k, logs, roster_team)
        e = inj.get(k)
        if e and cur and e.get("team") and e["team"] != cur:
            e = None
        g, ng = nxt.get(cur, (None, "")) if cur else (None, "")
        opp = (g["away"] if g["home"] == cur else g["home"]) if g else ""
        prev = {}
        b2b = []
        for r in lg:
            d = dt.date.fromisoformat(r["date"])
            if prev and (d - prev).days == 1:
                b2b.append(r)
            prev = d
        sets = {"L5": lg[-5:], "L10": lg[-10:], "Season": lg, "Home": [r for r in lg if r["home"]],
                "Away": [r for r in lg if not r["home"]], "B2B": b2b, "vsOpp": [r for r in lg if r["opp"] == opp]}
        n = len(lg)
        avg = [round(sum(val(r["s"], st) for r in lg) / n, 1) if n else "" for st in ("PTS", "REB", "AST", "3PM", "PRA")]
        row = [names.get(k, k), team_txt, status_text(e), ng, opp, n,
               round(sum(r["min"] for r in lg) / n, 1) if n else ""] + avg
        for w in WINDOWS:
            for st, t in ALL_LINES:
                if w == "True":
                    h = sum(val(r["s"], st) >= t for r in lg)
                    v = round(100 * (h + TRUE_K * base[(st, t)]) / (n + TRUE_K)) if n else None
                else:
                    s = sets[w]
                    v = pct(sum(val(r["s"], st) >= t for r in s), len(s))
                row.append("" if v is None else v)
        out.append(row)
    return out


def game_logs():
    """One row per player per 2026-27 game, rebuilt from scratch every run (ESPN-filled games are
    replaced automatically once Basketball Reference posts them)."""
    games, logs, names, h2, roster_team, inj, sched = load()
    source = {g["id"]: ("ESPN" if g.get("source") == "espn" else "BBR") for g in games}
    team_dates = {}
    for g in games:
        for t in (g["home"], g["away"]):
            team_dates.setdefault(t, set()).add(g["date"])
    out = []
    for k, lg in logs.items():
        name = names.get(k, k)
        for r in lg:
            d = dt.date.fromisoformat(r["date"])
            b2b = (d - dt.timedelta(days=1)).isoformat() in team_dates.get(r["team"], ())
            pts, reb, ast, fg3 = r["s"]
            out.append([r["date"], name, r["team"], r["opp"], "H" if r["home"] else "A", "Y" if b2b else "N",
                        r["min"], pts, reb, ast, fg3, pts + reb + ast,
                        "" if r["start"] is None else ("Y" if r["start"] else "N"),
                        nz(r.get("fga")), nz(r.get("fta")), nz(r.get("tov")), nz(r.get("usg")),
                        source.get(r["gid"], "BBR")])
    out.sort(key=lambda x: (x[1], x[0]))
    return [["Date", "Player", "Team", "Opp", "Home/Away", "Back-to-back", "MIN", "PTS", "REB", "AST", "3PM",
             "PRA", "Starter", "FGA", "FTA", "TOV", "USG%", "Source"]] + out


def rosters_tab():
    """Player, Team, Position (G, F, C, G-F, F-C) from Basketball Reference roster pages."""
    rb = jload(os.path.join(DATA, "rosters_bref.json"), {}) or {}
    out = sorted([n, t, p] for t, ps in rb.get("teams", {}).items() for n, p in ps.items())
    return [["Player", "Team", "Position"]] + out


if __name__ == "__main__":
    r = rows()
    write_csv("MASTER_2627.csv", r)
    print(len(r) - 1, "players,", len(r[0]), "columns")
    gl = game_logs()
    write_csv("GAMELOGS_2627.csv", gl)
    print(len(gl) - 1, "game-log rows")
    ro = rosters_tab()
    write_csv("ROSTERS.csv", ro)
    print(len(ro) - 1, "roster rows")
