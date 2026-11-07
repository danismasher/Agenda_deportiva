#!/usr/bin/env python3
"""Genera events.json con los eventos deportivos. Solo usa la libreria estandar."""
import json, sys, time, unicodedata, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "events.json"
MANUAL = ROOT / "manual.json"
UA = {"User-Agent": "agenda-deportiva/1.0 (uso personal)"}
NOW = datetime.now(timezone.utc)
TODAY = NOW.date()
ESPN = "https://site.api.espn.com/apis/site/v2/sports"


def get_json(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:
            last = e
        time.sleep(2 * (i + 1))
    raise last


def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def parse(s):
    d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def iso(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")


def mk(sport, date, time_, title, sub):
    if time_:
        return {"s": sport, "start": iso(parse(f"{date}T{time_}")), "title": title, "sub": sub}
    return {"s": sport, "date": date, "tbc": True, "title": title, "sub": sub}


# ---------- F1 (Jolpica, sucesora de Ergast) ----------
F1_SESSIONS = [
    ("Qualifying", "Clasificación"),
    ("SprintQualifying", "Clasificación sprint"),
    ("SprintShootout", "Clasificación sprint"),
    ("Sprint", "Carrera sprint"),
]


def f1():
    out = []
    for year in (TODAY.year, TODAY.year + 1):
        data = get_json(f"https://api.jolpi.ca/ergast/f1/{year}.json")
        if not data:
            continue
        for race in data["MRData"]["RaceTable"]["Races"]:
            gp = "GP " + race["raceName"].replace(" Grand Prix", "")
            sessions = [(race.get(k), t) for k, t in F1_SESSIONS]
            sessions.append(({"date": race["date"], "time": race.get("time")}, "Carrera"))
            for s, title in sessions:
                if s:
                    out.append(mk("f1", s["date"], s.get("time"), title, gp))
    return out


# ---------- ESPN (NFL, LaLiga, Champions, tenis) ----------
def espn_events(path, days, step):
    seen = {}
    d, end = TODAY, TODAY + timedelta(days=days)
    while d <= end:
        e = min(d + timedelta(days=step - 1), end)
        url = f"{ESPN}/{path}/scoreboard?dates={d:%Y%m%d}-{e:%Y%m%d}&limit=300"
        data = get_json(url) or {}
        for ev in data.get("events", []):
            seen[ev["id"]] = ev
        d = e + timedelta(days=1)
        time.sleep(0.5)
    return list(seen.values())


def matches(path, sport, days, step):
    out = []
    for ev in espn_events(path, days, step):
        comp = ev["competitions"][0]
        t = {c["homeAway"]: c["team"]["displayName"] for c in comp["competitors"]}
        if "home" not in t or "away" not in t:
            continue
        venue = (comp.get("venue") or {}).get("fullName", "")
        out.append({"s": sport, "start": iso(parse(ev["date"])),
                    "title": f'{t["home"]} – {t["away"]}', "sub": venue})
    return out


def short(name):
    p = name.split()
    return f"{p[0][0]}. {' '.join(p[1:])}" if len(p) > 1 else name


def tennis(days=21):
    out, seen = [], set()
    for ev in espn_events("tennis/atp", days, 7):
        tname = ev.get("name") or ev.get("shortName") or ""
        comps = []
        for g in ev.get("groupings") or []:
            comps += g.get("competitions") or []
        comps += ev.get("competitions") or []
        for c in comps:
            names = []
            for p in c.get("competitors") or []:
                a = p.get("athlete") or {}
                names.append(a.get("displayName") or (p.get("team") or {}).get("displayName") or "")
            if len(names) != 2 or not any("alcaraz" in norm(n) for n in names):
                continue
            when = c.get("date") or c.get("startDate") or ev.get("date")
            if not when:
                continue
            rnd = (c.get("round") or {}).get("displayName", "")
            item = {"s": "tenis", "start": iso(parse(when)),
                    "title": f"{short(names[0])} – {short(names[1])}",
                    "sub": ", ".join(x for x in (tname, rnd) if x)}
            k = (item["start"], item["title"])
            if k not in seen:
                seen.add(k)
                out.append(item)
    return out


SOURCES = {
    "f1": f1,
    "nfl": lambda: matches("football/nfl", "nfl", 120, 14),
    "laliga": lambda: matches("soccer/esp.1", "laliga", 120, 30),
    "champions": lambda: matches("soccer/uefa.champions", "champions", 120, 30),
    "tenis": tennis,
}


def manual():
    if not MANUAL.exists():
        return []
    return json.loads(MANUAL.read_text("utf-8")).get("events", [])


def main():
    old = []
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text("utf-8")).get("events", [])
        except Exception:
            pass
    events, report, ok = [], [], 0
    for sport, fn in SOURCES.items():
        try:
            evs = fn()
            events += evs
            ok += 1
            report.append(f"{sport}: {len(evs)} eventos")
        except Exception as e:
            prev = [x for x in old if x["s"] == sport]
            events += prev
            report.append(f"{sport}: ERROR {e!r} (se conservan {len(prev)} anteriores)")
    try:
        m = manual()
        events += m
        report.append(f"manual: {len(m)} eventos")
    except Exception as e:
        report.append(f"manual: ERROR {e!r}")

    keep_from = (TODAY - timedelta(days=7)).isoformat()
    uniq = {}
    for e in events:
        key = e.get("start") or e.get("date")
        if key[:10] < keep_from:
            continue
        uniq[(e["s"], key, e["title"])] = e
    ordered = sorted(uniq.values(), key=lambda e: ((e.get("start") or e["date"] + "T99"), e["s"]))
    OUT.write_text(json.dumps({"updated": iso(NOW), "events": ordered},
                              ensure_ascii=False, indent=1), "utf-8")
    print("\n".join(report))
    print(f"Total: {len(ordered)} eventos")
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
