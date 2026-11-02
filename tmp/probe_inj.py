import urllib.request, datetime as dt, json
from zoneinfo import ZoneInfo
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
now=dt.datetime.now(ZoneInfo("America/New_York"))
out={}
t=now.replace(minute=(now.minute//15)*15,second=0,microsecond=0)
for i in range(12):
    s=t-dt.timedelta(minutes=15*i)
    u=f"https://ak-static.cms.nba.com/referee/injury/Injury-Report_{s:%Y-%m-%d}_{s:%I_%M%p}.pdf"
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=20); b=r.read()
        out[u]=[r.status,len(b),b[:8].decode("latin1")]; break
    except Exception as e: out[u]=str(e)[:80]
try:
    r=urllib.request.urlopen(urllib.request.Request("https://official.nba.com/nba-injury-report-2026-27/",headers=H),timeout=20); out["page"]=[r.status,len(r.read())]
except Exception as e: out["page"]=str(e)[:80]
json.dump(out,open("tmp/probe_inj.json","w"),indent=1)
