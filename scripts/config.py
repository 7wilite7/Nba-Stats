"""Settings shared by fetch.py, build.py and verify.py."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "out")

SEASON_START = "2026-10-20"          # first regular-season game day (US date)
MIN_MPG = 20                         # players averaging this many minutes are listed
YET_TO_PLAY_MIN_PPG = 8              # roster players with no games yet, listed if 25/26 2nd-half PPG >= this
TRUE_K = 3                           # true rate = (hits + K * league rate) / (games + K); K=3 tested best on 25/26 data
PICK_MIN_TRUE = 80                   # Today picks: true rate at least this
SMALL_SAMPLE = 6                     # games below this are flagged yellow

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124 Safari/537.36", "Accept": "*/*"}
BREF_DELAY = 3.6                     # seconds between Basketball Reference requests (their limit is 20/minute)

# stat, column index in a game record, line, market name
LINES = ([("PTS", t, "Points") for t in (10, 15, 20, 25)] +
         [("REB", t, "Rebounds") for t in (3, 5, 7)] +
         [("AST", t, "Assists") for t in (3, 5, 7)] +
         [("3PM", t, "Threes") for t in (1, 2, 3, 4)])
STATS = ["PTS", "REB", "AST", "3PM"]

# Display team codes (standard NBA). Basketball Reference and ESPN use a few different ones.
BREF_TO_STD = {"BRK": "BKN", "CHO": "CHA", "PHO": "PHX"}
STD_TO_BREF = {v: k for k, v in BREF_TO_STD.items()}
ESPN_TO_STD = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}

# ESPN display name -> Basketball Reference name, where normalising isn't enough
NAME_ALIASES = {
    "carlton carrington": "Bub Carrington",
    "herb jones": "Herbert Jones",
    "nicolas claxton": "Nic Claxton",
    "dom barlow": "Dominick Barlow",
    "cam johnson": "Cameron Johnson",
    "moe wagner": "Moritz Wagner",
    "ronald holland": "Ron Holland",
}
