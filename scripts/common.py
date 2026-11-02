"""Small helpers shared by the scripts."""
import json, os, re, time, unicodedata, urllib.request
from config import UA, NAME_ALIASES


def jload(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def jsave(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, path)


def get(url, tries=4, timeout=30):
    """GET with retries; returns bytes. Backs off on 429/5xx."""
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            code = getattr(e, "code", None)
            if code == 404:
                raise
            time.sleep(20 if code == 429 else 4 * (i + 1))
    raise last


def norm(name):
    """Key for matching the same player across sources."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'’`]", "", s)
    s = re.sub(r"[-]", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def canonical(name, known):
    """Map a name from ESPN to the Basketball Reference spelling. `known` = {norm: bref name}."""
    k = norm(name)
    if k in NAME_ALIASES:
        return NAME_ALIASES[k]
    return known.get(k, name)
