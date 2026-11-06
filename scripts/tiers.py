"""Master table for the paid tier sheets (2026-27 games only).

One row per listed player. For every line: last 5, last 10, season, true rate, home, away,
second night of a back-to-back, and vs the next opponent. Tier sheets pick the columns they sell.
Writes out/MASTER_2627.csv (rows) and returns them for push_sheets.py.
"""
import datetime as dt
import build
from build import load, base_rates, next_games, pool, records, team_info, status_text, pct, write_csv
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


if __name__ == "__main__":
    r = rows()
    write_csv("MASTER_2627.csv", r)
    print(len(r) - 1, "players,", len(r[0]), "columns")
