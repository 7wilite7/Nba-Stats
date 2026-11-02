"""Fact-check: compare every Basketball Reference box score with ESPN's for the same game.

Writes data/verify.json (summary shown in the sheets) and out/VERIFY.csv (any differences)."""
import csv, glob, os
from config import DATA, OUT, STD_TO_BREF
from common import jload, jsave
from build import key

STATS = ("pts", "reb", "ast", "fg3")


def main():
    bref = {g["id"]: g for g in (jload(p) for p in glob.glob(os.path.join(DATA, "games", "*.json")))}
    games = checked = same = 0
    missing_games, diffs, unmatched = [], [], set()
    for p in sorted(glob.glob(os.path.join(DATA, "espn", "*.json"))):
        e = jload(p)
        gid = e["us_date"].replace("-", "") + "0" + STD_TO_BREF.get(e["home"], e["home"])
        b = bref.get(gid)
        if not b:
            missing_games.append(gid)
            continue
        games += 1
        bp = {key(x["name"]): x for x in b["players"]}
        for x in e["players"]:
            y = bp.get(key(x["name"]))
            if not y:
                if x["min"] > 0:
                    unmatched.add(x["name"])
                continue
            for s in STATS:
                checked += 1
                if x[s] == y[s]:
                    same += 1
                else:
                    diffs.append([gid, y["name"], s, y[s], x[s]])
    rate = round(100 * same / checked, 2) if checked else None
    summary = f"{rate}% of {checked:,} stats match ({games} games)" if checked else "n/a"
    jsave(os.path.join(DATA, "verify.json"), {"summary": summary, "games": games, "checked": checked, "same": same,
                                              "bref_missing": missing_games[-20:], "unmatched_names": sorted(unmatched)})
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "VERIFY.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"Fact-check vs ESPN: {summary}"])
        w.writerow(["Game", "Player", "Stat", "Basketball Reference", "ESPN"])
        w.writerows(diffs[-500:])
        if unmatched:
            w.writerow([])
            w.writerow(["ESPN names not matched to Basketball Reference:", "; ".join(sorted(unmatched))])
    print("verify:", summary, "| missing B-Ref games:", len(missing_games), "| unmatched names:", len(unmatched))


if __name__ == "__main__":
    main()
