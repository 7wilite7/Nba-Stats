"""Turn cached box scores into the CSVs the Google Sheets import.

Two versions ("variants"):
  2627  : 2026-27 games only
  blend : 2nd half of 2025-26 + 2026-27, rolling (each 2026-27 game drops the oldest 25/26 game)

Per variant: PLAYERS_<v>.csv (hit rates), TODAY_<v>.csv (picks), PHONE_<v>.csv, TRACKER_<v>.csv
"""
import csv, datetime as dt, glob, json, os, sys
from collections import defaultdict
from zoneinfo import ZoneInfo
from config import (DATA, OUT, MIN_MPG, YET_TO_PLAY_MIN_PPG, TRUE_K, PICK_MIN_TRUE, SMALL_SAMPLE, LINES, STATS,
                    STD_TO_BREF, NAME_ALIASES)
from common import jload, jsave, norm

UK = ZoneInfo("Europe/London")
NOW = dt.datetime.now(dt.timezone.utc)
SI = {"PTS": 0, "REB": 1, "AST": 2, "3PM": 3}
MARKET = {"PTS": "Points", "REB": "Rebounds", "AST": "Assists", "3PM": "Threes"}
VARIANTS = ("2627", "blend")


def key(name):
    k = norm(name)
    return norm(NAME_ALIASES[k]) if k in NAME_ALIASES else k


def uk(utc):
    return dt.datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone(UK)


def pct(h, n):
    return round(100 * h / n) if n else None


def nz(v):
    return "" if v is None else v


def blank(v):
    return "" if v in (None, 0, 0.0) else v


# ---------------- load ----------------

def load():
    games = sorted((jload(p) for p in glob.glob(os.path.join(DATA, "games", "*.json"))), key=lambda g: (g["date"], g["id"]))
    logs, names = defaultdict(list), {}
    for g in games:
        for p in g["players"]:
            k = key(p["name"])
            names[k] = p["name"]
            logs[k].append({"date": g["date"], "gid": g["id"], "team": p["team"], "min": p["min"],
                            "s": (p["pts"], p["reb"], p["ast"], p["fg3"]), "start": p["start"],
                            "opp": g["home"] if p["team"] == g["away"] else g["away"], "home": p["team"] == g["home"]})
    h2 = {}
    for row in jload(os.path.join(DATA, "h2_2025_26.json"), []):
        seqs = [list(map(int, row[i].split())) for i in range(1, 5)]
        k = key(row[0])
        h2[k] = [tuple(x) for x in zip(*seqs)]           # oldest -> newest, (pts, reb, ast, 3pm)
        names.setdefault(k, row[0])
    rosters = jload(os.path.join(DATA, "rosters.json"), {}) or {}
    roster_team = {}
    for team, ps in rosters.items():
        for n in ps:
            roster_team[key(n)] = team
            names.setdefault(key(n), n)
    inj = {}
    for e in jload(os.path.join(DATA, "injuries.json"), []) or []:
        inj[key(e["name"])] = e
    # Official NBA injury report (game-day status) takes priority; ESPN keeps the injury type and return date
    today_et = NOW.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    off = (jload(os.path.join(DATA, "injuries_official.json"), {}) or {}).get("players", [])
    for o in off:
        if o.get("game_date", "") < today_et:
            continue
        k = key(o["name"])
        e = inj.setdefault(k, {"name": o["name"], "team": o["team"]})
        if "official" not in e or o["game_date"] < e.get("official_date", "9"):
            e.update(official=o["status"], oreason=o["reason"], official_date=o["game_date"], team=o["team"])
    sched = jload(os.path.join(DATA, "schedule.json"), []) or []
    return games, logs, names, h2, roster_team, inj, sched


# ---------------- per-player numbers ----------------

def records(k, variant, logs, h2, before=None):
    """Game records (stat tuple, start flag or None) oldest -> newest for one variant."""
    lg = [r for r in logs.get(k, []) if before is None or r["date"] < before]
    cur = [(r["s"], r["start"]) for r in lg]
    if variant == "2627":
        return cur
    old = h2.get(k, [])
    old = old[min(len(cur), len(old)):]                  # rolling window: drop the oldest 25/26 game per 26/27 game
    return [(s, None) for s in old] + cur


def base_rates(logs, h2):
    hits, n = defaultdict(int), 0
    for k in set(logs) | set(h2):
        for s, _ in records(k, "blend", logs, h2):
            n += 1
            for st, t, _m in LINES:
                hits[(st, t)] += s[SI[st]] >= t
    return {lt: hits[lt] / n for lt in hits} if n else {}


def line_stats(recs, base):
    n = len(recs)
    out = {}
    last5 = recs[-5:]
    starts = [r for r in recs if r[1] is True]
    for st, t, _m in LINES:
        f = lambda r: r[0][SI[st]] >= t  # noqa: E731
        h = sum(1 for r in recs if f(r))
        out[(st, t)] = {
            "season": pct(h, n),
            "true": round(100 * (h + TRUE_K * base[(st, t)]) / (n + TRUE_K)) if n else None,
            "l5": pct(sum(1 for r in last5 if f(r)), len(last5)),
            "start": pct(sum(1 for r in starts if f(r)), len(starts)) if len(starts) >= 3 else None,
            "hits": h, "n": n}
    return out


# ---------------- context: team, status, next game ----------------

def team_info(k, logs, roster_team):
    lg = logs.get(k, [])
    last = lg[-1]["team"] if lg else None
    cur = roster_team.get(k) or last
    frm = None
    if last and cur and cur != last:
        frm = last
    elif lg:
        first = next((r["team"] for r in lg if r["team"] != cur), None)
        frm = first
    return cur, (f"{cur} (from {frm})" if frm else cur or "")


def status_text(e):
    if not e:
        return ""
    if e.get("official"):                       # official NBA report for the next game
        if e["official"] == "Available":
            return ""
        s = e["official"]
        why = e.get("type") or (e.get("oreason") or "").replace("Injury/Illness - ", "").split(";")[0].strip()
        if why:
            s += f" ({why})"
        if e.get("return") and e["official"] == "Out":
            try:
                s += " – est. return " + dt.date.fromisoformat(e["return"][:10]).strftime("%-d %b")
            except Exception:  # noqa: BLE001
                pass
        return s
    s = e.get("status", "")
    fs = (e.get("fs") or "").strip()
    if fs.lower() == "out" and not s.lower().startswith("out"):
        s = "Out"
    elif fs and fs.lower() not in s.lower() and fs.lower() not in ("active",):
        s += f" / {fs}"                  # e.g. Day-To-Day / Questionable
    if e.get("type"):
        s += f" ({e['type']})"
    if e.get("return"):
        try:
            s += " – est. return " + dt.date.fromisoformat(e["return"][:10]).strftime("%-d %b")
        except Exception:  # noqa: BLE001
            pass
    return s


def next_games(sched):
    nxt = {}
    for g in sorted(sched, key=lambda g: g["utc"]):
        if g["state"] == "post" or uk(g["utc"]) < NOW - dt.timedelta(hours=3):
            continue
        for side, opp, at in ((g["home"], g["away"], "v"), (g["away"], g["home"], "@")):
            nxt.setdefault(side, (g, f"{at} {opp} {uk(g['utc']).strftime('%a %d %b %H:%M')}"))
    return nxt


# ---------------- pool ----------------

def pool(logs, h2, roster_team, before=None):
    keep = []
    for k in set(logs) | set(roster_team):
        lg = [r for r in logs.get(k, []) if before is None or r["date"] < before]
        if lg:
            if sum(r["min"] for r in lg) / len(lg) >= MIN_MPG:
                keep.append(k)
        elif before is None and k in roster_team and k in h2:
            if sum(s[0] for s in h2[k]) / len(h2[k]) >= YET_TO_PLAY_MIN_PPG:
                keep.append(k)
    return keep


# ---------------- picks ----------------

def best_picks(ls):
    """Per stat, the highest line with a true rate at or above the pick threshold."""
    out = []
    for st in STATS:
        cands = [(t, ls[(st, t)]) for s2, t, _ in LINES if s2 == st and ls[(st, t)]["true"] is not None
                 and ls[(st, t)]["true"] >= PICK_MIN_TRUE]
        if cands:
            t, v = max(cands, key=lambda x: x[0])
            out.append((st, t, v))
    return out


def bref_id(us_date, home):
    return us_date.replace("-", "") + "0" + STD_TO_BREF.get(home, home)


def grade(entry, games_by_id):
    g = games_by_id.get(entry["bref"])
    if not g:
        return None
    for p in g["players"]:
        if key(p["name"]) == entry["key"]:
            v = (p["pts"], p["reb"], p["ast"], p["fg3"])[SI[entry["stat"]]]
            return "Hit" if v >= entry["line"] else "Miss"
    return "Did not play"


def replay(variant, logs, h2, games, base, start_date):
    """Picks for every past game day before live logging began, using only data from before that day."""
    out = {}
    by_date = defaultdict(list)
    for g in games:
        by_date[g["date"]].append(g)
    for d in sorted(by_date):
        if d >= start_date:
            break
        keep = set(pool(logs, h2, {}, before=d))
        for g in by_date[d]:
            played = {key(p["name"]): p for p in g["players"]}
            for side in (g["home"], g["away"]):
                for k in keep:
                    lg = [r for r in logs.get(k, []) if r["date"] < d]
                    if not lg or lg[-1]["team"] != side:
                        continue
                    ls = line_stats(records(k, variant, logs, h2, before=d), base)
                    for st, t, v in best_picks(ls):
                        p = played.get(k)
                        res = "Did not play" if not p else ("Hit" if (p["pts"], p["reb"], p["ast"], p["fg3"])[SI[st]] >= t else "Miss")
                        name = logs[k][-1] and NAMES.get(k, k)
                        out[f"R|{g['id']}|{k}|{st}|{t}"] = {
                            "date": d, "game": f"{g['away']} @ {g['home']}", "pick": f"{name} {MARKET[st]} {t}+",
                            "key": k, "stat": st, "line": t, "true": v["true"], "season": v["season"], "n": v["n"],
                            "result": res, "source": "Replay"}
    return out


# ---------------- CSV writers ----------------

def write_csv(name, rows):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", newline="") as f:
        csv.writer(f).writerows(rows)


def main():
    global NAMES
    games, logs, names, h2, roster_team, inj, sched = load()
    NAMES = names
    if not games:
        sys.exit("no box scores loaded")
    games_by_id = {g["id"]: g for g in games}
    base = base_rates(logs, h2)
    nxt = next_games(sched)
    keep = sorted(pool(logs, h2, roster_team), key=lambda k: names.get(k, k))
    ver = jload(os.path.join(DATA, "verify.json"), {}) or {}
    last_game = games[-1]["date"]
    state = jload(os.path.join(DATA, "state.json"), {}) or {}
    live_start = state.setdefault("tracker_live_since", NOW.astimezone(UK).date().isoformat())
    jsave(os.path.join(DATA, "state.json"), state)

    upcoming = [g for g in sched if g["state"] == "pre" and NOW <= uk(g["utc"]) <= NOW + dt.timedelta(hours=24)]
    team_game = {}
    for g in upcoming:
        team_game[g["home"]] = g
        team_game[g["away"]] = g

    layout = {}
    for v in VARIANTS:
        # ---------- tracker: log new picks, grade old ones ----------
        tpath = os.path.join(DATA, "picks", f"{v}.json")
        log = jload(tpath, {}) or {}
        for e in log.values():
            if e.get("result") is None and uk(e["utc"]) < NOW - dt.timedelta(hours=3):
                r = grade(e, games_by_id)
                if r is None and uk(e["utc"]) < NOW - dt.timedelta(days=3):
                    r = "Void"
                e["result"] = r

        # ---------- players ----------
        head = ["Player", "Team", "Status", "Next game"]
        head += ["GP", "Starts", "MPG"] if v == "2627" else ["GP 26/27", "GP 25/26", "GP total", "MPG 26/27"]
        head += ["PPG", "RPG", "APG", "3PM/G"]
        groups = [("True", ""), ("Season", "S: "), ("Last 5", "L5: ")] + ([("Start", "St: ")] if v == "2627" else [])
        first_pct = len(head)
        for _g, pre in groups:
            head += [f"{pre}{st} {t}+" for st, t, _ in LINES]
        grp_row = [""] * first_pct
        labels = {"True": "TRUE RATE % (record + 3 league-average games) — use this",
                  "Season": "SEASON % (raw)", "Last 5": "LAST 5 GAMES % (info only)",
                  "Start": "WHEN STARTING % (3+ starts)"}
        for gname, _pre in groups:
            grp_row += [labels[gname]] + [""] * (len(LINES) - 1)
        grp_row[0] = "Points 10/15/20/25 · Rebounds 3/5/7 · Assists 3/5/7 · Threes 1/2/3/4"

        rows, picks, game_rows = [], [], []
        for k in keep:
            recs = records(k, v, logs, h2)
            lg = logs.get(k, [])
            cur, team_txt = team_info(k, logs, roster_team)
            e = inj.get(k)
            if e and cur and e.get("team") and e["team"] != cur:
                e = None
            ls = line_stats(recs, base)
            n = len(recs)
            avg = [round(sum(r[0][i] for r in recs) / n, 1) if n else None for i in range(4)]
            mpg = round(sum(r["min"] for r in lg) / len(lg), 1) if lg else None
            ng = nxt.get(cur, (None, ""))[1] if cur else ""
            row = [names.get(k, k), team_txt, status_text(e), ng]
            if v == "2627":
                row += [len(lg), sum(1 for r in lg if r["start"]), blank(mpg)]
            else:
                row += [len(lg), n - len(lg), n, blank(mpg)]
            row += [blank(a) for a in avg]
            for gname, _pre in groups:
                fld = {"True": "true", "Season": "season", "Last 5": "l5", "Start": "start"}[gname]
                row += ["" if ls[(st, t)][fld] is None else ls[(st, t)][fld] for st, t, _ in LINES]  # 0 kept; the sheet hides zeros
            rows.append(row)
            tg = team_game.get(cur)
            if tg:
                order = (tg["utc"], f"{tg['away']} @ {tg['home']}", names.get(k, k))   # by game, then alphabetical
                game_rows.append((order, [f"{tg['away']} @ {tg['home']} · {uk(tg['utc']).strftime('%a %H:%M')} UK",
                                          names.get(k, k), team_txt, n] +
                                  [nz(ls[(st, t)]["season"]) for st, t, _ in LINES] + [status_text(e)]))

            # ---------- today's picks ----------
            g = team_game.get(cur)
            if g and n and not status_text(e).lower().startswith("out"):
                for st, t, val in best_picks(ls):
                    notes = []
                    if e:
                        notes.append(status_text(e))
                    if "(from" in team_txt:
                        notes.append("New team: " + team_txt)
                    if lg and lg[-1]["start"] is False:
                        notes.append("Came off the bench last game")
                    if n < SMALL_SAMPLE:
                        notes.append(f"Only {n} games")
                    gtxt = f"{g['away']} @ {g['home']}"
                    picks.append({"utc": g["utc"], "game": gtxt, "tip": uk(g["utc"]).strftime("%a %H:%M"),
                                  "pick": f"{names.get(k, k)} {MARKET[st]} {t}+", "market": MARKET[st], "player": names.get(k, k),
                                  "team": cur, "status": status_text(e), "true": val["true"], "season": val["season"],
                                  "l5": val["l5"], "start": val["start"], "n": n, "note": "; ".join(notes)})
                    lk = f"{g['id']}|{k}|{st}|{t}"
                    if lk not in log:
                        log[lk] = {"date": uk(g["utc"]).date().isoformat(), "utc": g["utc"], "game": gtxt,
                                   "pick": f"{names.get(k, k)} {MARKET[st]} {t}+", "key": k, "stat": st, "line": t,
                                   "true": val["true"], "season": val["season"], "n": n,
                                   "bref": bref_id(g["us_date"], g["home"]), "result": None, "source": "Live"}
        jsave(tpath, log)

        # ---------- tracker summary ----------
        allp = dict(replay(v, logs, h2, games, base, live_start))
        allp.update(log)
        graded = [e for e in allp.values() if e.get("result") in ("Hit", "Miss")]
        hit = pct(sum(e["result"] == "Hit" for e in graded), len(graded))
        said = round(sum(e["true"] for e in graded) / len(graded)) if graded else None
        tr_line = f"pick tracker: {hit}% hit from {len(graded)} graded picks" if graded else "pick tracker: no graded picks yet"
        upd = (f"Updated {NOW.astimezone(UK).strftime('%a %d %b %H:%M')} UK · box scores to {last_game} · "
               f"fact-check vs ESPN: {ver.get('summary', 'n/a')} · {tr_line}")

        prow = [[upd] + [""] * (len(head) - 2) + [NOW.isoformat(timespec="minutes")], grp_row, head] + rows
        write_csv(f"PLAYERS_{v}.csv", prow)
        game_rows.sort(key=lambda x: x[0])
        gtitle = (f"Every listed player in games over the next 24 hours, by game, A–Z within each game · "
                  f"updated {NOW.astimezone(UK).strftime('%a %d %b %H:%M')} UK")
        ghead = ["Game", "Player", "Team", "GP"] + [f"{st} {t}+" for st, t, _ in LINES] + ["status"]
        write_csv(f"GAMES_{v}.csv", [[gtitle], ghead] +
                  ([r for _o, r in game_rows] or [["No games in the next 24 hours"]]))

        picks.sort(key=lambda p: (p["utc"], p["game"], p["pick"]))   # by game, then alphabetical
        th = ["Pick", "Market", "Hit %", "Games", "Team", "Game", "Tip-off (UK)", "Note", "status"]
        trows = [[p["pick"], p["market"], nz(p["season"]), p["n"], p["team"], p["game"], p["tip"], p["note"], p["status"]]
                 for p in picks]
        title = (f"Today's picks (chosen by true rate {PICK_MIN_TRUE}%+, shown as this season's hit %) · "
                 f"{tr_line} · updated {NOW.astimezone(UK).strftime('%a %H:%M')}")
        write_csv(f"TODAY_{v}.csv", [[title], th] + (trows or [["No games in the next 24 hours"]]))
        write_csv(f"PHONE_{v}.csv", [[f"Picks · {tr_line}"], ["Pick", "Hit %", "Game"]] +
                  ([[p["pick"], nz(p["season"]), f"{p['game']} {p['tip']}"] for p in picks] or [["No games in the next 24 hours"]]))

        # tracker CSV
        def summ(rows_):
            g_ = [e for e in rows_ if e.get("result") in ("Hit", "Miss")]
            return [len(g_), pct(sum(e["result"] == "Hit" for e in g_), len(g_)) or "",
                    round(sum(e["true"] for e in g_) / len(g_)) if g_ else ""]
        out = [[upd], [f"Every Today pick is logged before tip-off and graded after. Live since {live_start}; "
                       f"rows marked Replay are earlier games re-run using only data available before each game. "
                       f"Did not play and Void picks don't count."], [],
               ["By market", "Graded", "Hit %", "True % given"]]
        for m in ("Points", "Rebounds", "Assists", "Threes"):
            out.append([m] + summ([e for e in allp.values() if MARKET[e["stat"]] == m]))
        out += [["All picks"] + summ(list(allp.values())), [], ["By true rate", "Graded", "Hit %", "True % given"]]
        for lo, hi in ((80, 84), (85, 89), (90, 94), (95, 100)):
            out.append([f"{lo}–{hi}%"] + summ([e for e in allp.values() if lo <= (e["true"] or 0) <= hi]))
        out += [[], ["Date", "Game", "Pick", "True %", "Season %", "Games", "Result", "Source"]]
        for e in sorted(allp.values(), key=lambda e: (e["date"], e["pick"]), reverse=True)[:400]:
            out.append([e["date"], e["game"], e["pick"], e["true"], blank(e["season"]), e["n"], e.get("result") or "Pending", e["source"]])
        write_csv(f"TRACKER_{v}.csv", out)

        layout[v] = {"cols": len(head), "first_pct": first_pct, "n_pct": len(groups) * len(LINES),
                     "gp_col": head.index("GP" if v == "2627" else "GP total"), "rows": len(rows),
                     "picks": len(picks), "graded": len(graded), "hit": hit, "true_given": said}
        print(v, layout[v], flush=True)
    jsave(os.path.join(OUT, "LAYOUT.json"), layout)


if __name__ == "__main__":
    main()
