#!/usr/bin/env python3
"""Resultados de IndyCar (todas las clasificaciones y la carrera) desde la API de indycar.com.
Genera indycar.json. Solo usa la libreria estandar."""
import json, re, sys, time, urllib.request, urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "indycar.json"
SERIES = "b856a4f1-e85c-4fac-8c36-fd58d962227a"
API = "https://www.indycar.com/api/results/"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "application/json, text/plain, */*", "Referer": "https://www.indycar.com/Results"}
TODAY = datetime.now(timezone.utc).date()
KEEP = 90
DEBUG = []


def get_json(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
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


def norm_session(name):
    """Nombre de sesion en espanol. Devuelve None si no es clasificacion ni carrera."""
    n = (name or "").strip()
    low = n.lower()
    if low == "race":
        return "Carrera"
    if "qualif" not in low:
        return None
    if low == "combined qualifying":
        return "Clasificación"
    rest = re.sub(r"(?i)^qualifying\s*[-–:]?\s*", "", n)
    rest = re.sub(r"(?i)firestone\s*", "", rest).strip()
    for en, es in (("Round", "Ronda"), ("Group", "grupo"), ("Day", "Día"), ("Pole", "Pole"), ("Last Chance", "Última oportunidad")):
        rest = re.sub(rf"(?i)\b{en}\b", es, rest)
    rest = re.sub(r"\s+", " ", rest).strip(" -")
    if re.search(r"(?i)ronda \d+ grupo", rest):
        rest = re.sub(r"(?i)(ronda \d+) grupo", r"\1, grupo", rest)
    return f"Clasificación, {rest}" if rest else "Clasificación"


def short_event(name):
    m = re.search(r"Grand Prix of (.+)$", name or "", re.I)
    return f"GP {m.group(1).strip()}" if m else (name or "").strip()


def pick(rec, subs, bad=()):
    for k, v in rec.items():
        lk = k.lower()
        if any(s in lk for s in subs) and not any(b in lk for b in bad) and v not in (None, ""):
            return v
    return None


def short(n):
    p = n.split()
    return f"{p[0][0]}. {' '.join(p[1:])}" if len(p) > 1 else n


def to_res(records, is_race, title):
    rows = []
    for i, r in enumerate(records):
        name = f'{r.get("FirstName", "")} {r.get("LastName", "")}'.strip()
        pos = pick(r, ("position", "finish", "pos"), bad=("start", "grid", "led"))
        team = pick(r, ("team",)) or ""
        if is_race:
            t = pick(r, ("elapsed",)) or pick(r, ("time",), bad=("pit",)) or ""
            if str(pick(r, ("status",)) or "").lower() not in ("", "running") and not t:
                t = str(pick(r, ("status",)))
        else:
            t = pick(r, ("besttime", "best_time", "bestlap", "best lap")) or pick(r, ("time", "lap"), bad=("pit", "laps", "led")) or ""
        rows.append([str(pos if pos is not None else i + 1), short(name), str(team), str(t)])
    if not rows:
        return None
    first = f'{records[0].get("FirstName", "")} {records[0].get("LastName", "")}'.strip()
    label = "Ganador" if is_race else ("Pole" if title in ("Clasificación",) or "Fast" in title else "Mejor")
    return {"head": f"{label}: {first}", "rows": rows}


def parse_date(s):
    try:
        m, d, y = [int(x) for x in str(s).split("/")]
        return date(y, m, d)
    except Exception:
        return None


def collect(prev, tried):
    seasons = get_json(f"{API}SeasonDropDown?id={SERIES}") or []
    out, new_tried, shown = [], dict(tried), set()
    for season in seasons:
        try:
            if int(season.get("Year")) < TODAY.year - 1:
                continue
        except Exception:
            continue
        stop = False
        for ev in season.get("Events") or []:
            sessions = [(s, norm_session(s.get("SessionName"))) for s in ev.get("Sessions") or []]
            sessions = [(s, t) for s, t in sessions if t]
            if not sessions:
                continue
            event_date = None
            for s, title in sorted(sessions, key=lambda x: x[1] != "Carrera"):  # primero la carrera: da la fecha
                sid = str(s["EventsSessionID"])
                if sid in prev:
                    out.append(prev[sid])
                    event_date = event_date or parse_date(prev[sid].get("d"))
                    continue
                if sid in tried and event_date and event_date < TODAY - timedelta(days=3):
                    continue
                det = get_json(f"{API}EventsSessionDetails?id={sid}") or {}
                time.sleep(0.3)
                d = parse_date(det.get("SessionDate"))
                records = det.get("records") or []
                if d:
                    event_date = event_date or d
                if not d or d > TODAY or d < TODAY - timedelta(days=KEEP):
                    if d and d < TODAY - timedelta(days=KEEP):
                        stop = True
                    new_tried[sid] = (d or TODAY).isoformat()
                    continue
                if not records:
                    new_tried[sid] = d.isoformat()
                    continue
                if records and title not in shown and len(shown) < 2:
                    shown.add(title)
                    DEBUG.append(f"ejemplo de registro ({title}): " + json.dumps(records[0], ensure_ascii=False)[:600])
                res = to_res(records, title == "Carrera", title)
                if res:
                    out.append({"s": "indy", "date": d.isoformat(), "tbc": True, "title": title,
                                "sub": short_event(det.get("EventName") or ev.get("EventName")), "res": res, "sid": sid, "d": d.isoformat()})
            if stop:
                break
        if stop:
            break
    return out, new_tried


def main():
    prev, tried = {}, {}
    if OUT.exists():
        try:
            j = json.loads(OUT.read_text("utf-8"))
            prev = {e["sid"]: e for e in j.get("events", []) if e.get("sid")}
            tried = j.get("tried", {})
        except Exception:
            pass
    events, new_tried = collect(prev, tried)
    new = {"events": events, "tried": new_tried}
    try:
        j = json.loads(OUT.read_text("utf-8"))
        same = {"events": j.get("events"), "tried": j.get("tried")} == new
    except Exception:
        same = False
    if not same:
        OUT.write_text(json.dumps({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z"), **new},
                                  ensure_ascii=False, indent=1), "utf-8")
    print(f"indycar: {len(events)} sesiones con resultado")
    for line in DEBUG[:10]:
        print("  ", line)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR en indycar.py: {e!r}")
        for line in DEBUG[:10]:
            print("  ", line)
        sys.exit(1)
