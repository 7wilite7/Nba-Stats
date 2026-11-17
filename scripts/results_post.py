"""Post last night's graded picks and the running live record to the #results Discord channel.

Runs after the morning update. Needs the DISCORD_WEBHOOK_RESULTS secret; without it, prints the card only.
Counts Live picks only (Replay picks and "Did not play" are left out). Posts each slate once.
"""
import datetime as dt, json, os, sys, urllib.request
from config import DATA

PICKS = os.path.join(DATA, "picks", "2627.json")
SENT = os.path.join(DATA, "results_posted.txt")


def pct(h, m):
    return round(100 * h / (h + m)) if h + m else 0


def card():
    picks = [p for p in json.load(open(PICKS)).values() if p.get("source") == "Live"]
    dates = sorted({p["date"] for p in picks})
    graded = [d for d in dates if all(p["result"] for p in picks if p["date"] == d)]
    if not graded:
        return None, None
    day = graded[-1]
    night = [p for p in picks if p["date"] == day and p["result"] in ("Hit", "Miss")]
    hits = sum(p["result"] == "Hit" for p in night)
    misses = [p for p in night if p["result"] == "Miss"]
    allg = [p for p in picks if p["result"] in ("Hit", "Miss") and p["date"] <= day]
    th = sum(p["result"] == "Hit" for p in allg)
    tm = len(allg) - th
    since = min(p["date"] for p in allg)
    label = (dt.date.fromisoformat(day) - dt.timedelta(days=1)).strftime("%a %-d %b")
    start = (dt.date.fromisoformat(since) - dt.timedelta(days=1)).strftime("%-d %b")
    lines = [f"🏀 **NBA results – {label}**",
             f"✅ {hits} hit · ❌ {len(misses)} missed · **{pct(hits, len(misses))}%**",
             f"Running record (live since {start}): {th:,}–{tm:,} · **{pct(th, tm)}%**"]
    if misses:
        names = ", ".join(p["pick"] for p in sorted(misses, key=lambda p: -p.get("true", 0))[:12])
        more = f" +{len(misses) - 12} more" if len(misses) > 12 else ""
        lines.append(f"Misses: {names}{more}")
    lines.append("-# Every pick from the sheet's Today tab, logged before tip-off. Players who didn't play are excluded. 18+.")
    return day, "\n".join(lines)


def main():
    day, text = card()
    if not text:
        print("No fully graded slate yet")
        return
    print(text)
    if os.path.exists(SENT) and open(SENT).read().strip() == day:
        print("Already posted", day)
        return
    hook = os.environ.get("DISCORD_WEBHOOK_RESULTS")
    if not hook:
        print("DISCORD_WEBHOOK_RESULTS not set; not posting")
        return
    body = json.dumps({"content": text, "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(hook, body, {"Content-Type": "application/json", "User-Agent": "HitRateHub"})
    try:
        urllib.request.urlopen(req, timeout=15)
        open(SENT, "w").write(day)
        print("Posted results for", day)
    except Exception as e:  # noqa: BLE001 - never fail the update over Discord
        print("Discord post failed:", e)


if __name__ == "__main__":
    sys.exit(main())
