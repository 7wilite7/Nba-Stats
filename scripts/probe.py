import urllib.request, json, time
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36","Accept":"*/*"}
U={
 "espn_scoreboard":"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261101",
 "espn_injuries":"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
 "espn_teams":"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams",
 "nba_cdn_schedule":"https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json",
 "bref_box":"https://www.basketball-reference.com/boxscores/?month=11&day=1&year=2026",
 "cbs_injuries":"https://www.cbssports.com/nba/injuries/",
}
out={}
for k,u in U.items():
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=20); b=r.read()
        out[k]=[r.status,len(b),b[:150].decode("utf8","replace")]
    except Exception as e: out[k]=["ERR",str(e)[:200]]
# one espn summary + nba boxscore sample
try:
    sb=json.load(urllib.request.urlopen(urllib.request.Request(U["espn_scoreboard"],headers=H),timeout=20))
    ev=sb["events"][0]; eid=ev["id"]
    s=json.load(urllib.request.urlopen(urllib.request.Request("https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event="+eid,headers=H),timeout=20))
    bp=s["boxscore"]["players"][0]
    out["espn_summary_sample"]={"event":ev["name"],"season":ev.get("season"),"team":bp["team"].get("abbreviation"),"labels":bp["statistics"][0].get("labels"),"keys":bp["statistics"][0].get("keys"),"ath0":bp["statistics"][0]["athletes"][0]}
except Exception as e: out["espn_summary_sample"]=str(e)[:300]
try:
    sc=json.load(urllib.request.urlopen(urllib.request.Request(U["nba_cdn_schedule"],headers=H),timeout=30))
    g=[g for d in sc["leagueSchedule"]["gameDates"] for g in d["games"] if g["gameStatus"]==3][-1]
    out["nba_game"]={k:g[k] for k in ("gameId","gameDateTimeUTC")}
    b=json.load(urllib.request.urlopen(urllib.request.Request(f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{g['gameId']}.json",headers=H),timeout=20))
    p=b["game"]["homeTeam"]["players"][0]; out["nba_box_sample"]={"name":p["name"],"stats":{k:p["statistics"].get(k) for k in ("minutes","points","reboundsTotal","assists","threePointersMade")}}
except Exception as e: out["nba_box"]=str(e)[:300]
json.dump(out,open("probe.json","w"),indent=1,default=str)
