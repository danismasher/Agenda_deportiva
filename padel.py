#!/usr/bin/env python3
"""Lee premierpadel.com y genera padel.json con cuartos, semifinales y finales."""
import json, re, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "padel.json"
API = "https://api-prod.premierpadel.com/api/tournament/"
LIST = "https://premierpadel.com/es/tournaments"
TODAY = datetime.now(timezone.utc).date()
GENDER = {"male": "masculino", "female": "femenino"}
SEEN_ROUNDS = set()
DEBUG = []
MATCH_MIN = {"female": 120, "male": 90}  # minutos supuestos por partido para estimar el siguiente
HDR = re.compile(r"(\d{1,2})[:.](\d{2})\s*([AaPp])?\.?[Mm]?")


def rnd(name):
    n = (name or "").strip().upper().replace("-", " ").replace("_", " ")
    SEEN_ROUNDS.add(n)
    if n in ("QF", "CUARTOS", "1/4") or "QUARTER" in n or "CUARTOS" in n:
        return "Cuartos de final"
    if n in ("SF",) or "SEMI" in n:
        return "Semifinal"
    if n in ("F", "FINAL") or (n.endswith("FINAL") and "QUARTER" not in n and "SEMI" not in n):
        return "Final"
    return None


def pair(team):
    names = [p.get("last_name") or p.get("first_name") or "" for p in (team.get("players") or [])]
    return " / ".join(n for n in names if n)


def utc_of(txt):
    return datetime.strptime(txt.strip()[:19], "%Y-%m-%d %H:%M:%S")


def header_time(h):
    """Hora de un texto tipo 'Not before 7:00 PM' o 'No antes de las 19:00'."""
    m = HDR.search(h or "")
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    ap = (m.group(3) or "").lower()
    if ap == "p" and hh < 12:
        hh += 12
    if ap == "a" and hh == 12:
        hh = 0
    if hh > 23 or mm > 59:
        return None
    return hh, mm


def court_offset(matches):
    """Diferencia hora local - UTC de la sede, sacada de los propios partidos."""
    for m in matches:
        try:
            local = datetime.strptime(f"{m['date']} {m['start_time']}", "%Y-%m-%d %H:%M")
            diff = local - utc_of(m["start_date_time"])
            return timedelta(minutes=round(diff.total_seconds() / 900) * 15)
        except Exception:
            continue
    return None


def court_events(tname, gender, courts):
    out = []
    for c in courts:
        ms = c.get("matches") or []
        off = court_offset(ms)
        prev_t, prev_hdr = None, None
        for m in ms:
            r = rnd(m.get("round_name"))
            sdt = m.get("start_date_time")
            if not sdt:
                if r and m.get("date"):
                    out.append(_ev(tname, gender, r, m, None, False))
                continue
            base, approx, t, nb = utc_of(sdt), False, None, False
            hdr = m.get("header") or ""
            if m.get("status") in ("P", "F"):
                t = base
            else:
                ht = header_time(hdr)
                if ht and off is not None and hdr != prev_hdr:
                    cand = datetime.combine(date.fromisoformat(m["date"]), datetime.min.time())
                    cand = cand.replace(hour=ht[0], minute=ht[1]) - off
                    if base <= cand <= base + timedelta(hours=10):
                        t, nb = cand, True
                if t is None:
                    if prev_t is not None:
                        t, approx = prev_t + timedelta(minutes=MATCH_MIN.get(gender, 90)), True
                    else:
                        t = base
            prev_t, prev_hdr = t, hdr
            if r:
                out.append(_ev(tname, gender, r, m, t, approx, nb))
                DEBUG.append(f"{tname} {gender} {c.get('court_name')} {m.get('round_name')} st={m.get('status')} "
                             f"start_time={m.get('start_time')} start_utc={sdt} header={hdr!r} -> {t} approx={approx}")
    return out


def padel_res(m, teams):
    if m.get("status") != "F" or len(teams) < 2:
        return None
    try:
        sets = []
        for t in teams[:2]:
            sc = t.get("score") or {}
            sets.append([sc.get(f"set{i}") for i in range(1, 6)])
        pairs = [(x, y) for x, y in zip(sets[0], sets[1]) if x is not None and y is not None]
        wa = sum(1 for x, y in pairs if x > y)
        wb = sum(1 for x, y in pairs if y > x)
        if not pairs or wa == wb:
            return None
        win = 0 if wa > wb else 1
        txt = " ".join(f"{x}-{y}" if win == 0 else f"{y}-{x}" for x, y in pairs)
        return {"head": f"Ganan {pair(teams[win])}: {txt}"}
    except Exception:
        return None


def _ev(tname, gender, r, m, t, approx, nb=False):
    teams = sorted(m.get("teams") or [], key=lambda x: x.get("team_no", 0))
    a, b = (pair(teams[0]), pair(teams[1])) if len(teams) >= 2 else ("", "")
    title = f"{a} – {b}" if a and b else f"{r} {GENDER[gender]}"
    sub = f"{r} {GENDER[gender]}, {tname}" + (" (hora aproximada)" if approx else "")
    if t is None:
        ev = {"s": "padel", "date": m["date"], "tbc": True, "title": title, "sub": sub, "_round": r}
    else:
        ev = {"s": "padel", "start": t.strftime("%Y-%m-%dT%H:%M:00Z"), "title": title, "sub": sub, "_round": r}
        if nb:
            ev["nb"] = True
    res = padel_res(m, teams)
    if res:
        ev["res"] = res
    return ev


def estimates(tname, end, have_rounds):
    plan = (("Cuartos de final", 2), ("Semifinal", 1), ("Final", 0))
    out = []
    for r, back in plan:
        if r in have_rounds:
            continue
        d = (end - timedelta(days=back)).isoformat()
        out.append({"s": "padel", "date": d, "tbc": True, "title": r,
                    "sub": f"{tname} (fecha estimada)"})
    return out


def day(s):
    return date.fromisoformat(s[:10])


def build(tournaments, fetch_matches):
    """fetch_matches(slug, gender, date_or_None) -> dict de la API."""
    events = []
    for t in tournaments:
        start, end = day(t["start_date_utc"]), day(t["end_date_utc"])
        if end < TODAY - timedelta(days=14) or start > TODAY + timedelta(days=60):
            continue
        tname = (t.get("name") or t["slug"]).title()
        real = []
        if start <= TODAY + timedelta(days=14):
            for gender in GENDER:
                first = fetch_matches(t["slug"], gender, None)
                dates = (first.get("data") or {}).get("date") or []
                for d in dates:
                    if day(d) < TODAY - timedelta(days=14):
                        continue
                    data = fetch_matches(t["slug"], gender, d)
                    real += court_events(tname, gender, (data.get("data") or {}).get("courts") or [])
        have = {e["_round"] for e in real}
        events += [{k: v for k, v in e.items() if k != "_round"} for e in real]
        if end >= TODAY:
            events += estimates(tname, end, have)
    return events


def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="es-ES")
        page = ctx.new_page()
        auth = {}

        def on_req(r):
            if "api-prod.premierpadel.com" in r.url and r.headers.get("authorization"):
                auth["v"] = r.headers["authorization"]

        page.on("request", on_req)
        page.goto(LIST, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(3000)
        if "v" not in auth:
            raise RuntimeError("no se obtuvo la credencial de la web")
        headers = {"authorization": auth["v"], "content-type": "application/json",
                   "language_code": "es", "origin": "https://premierpadel.com",
                   "referer": "https://premierpadel.com/"}

        def post(path, body):
            r = ctx.request.post(API + path, data=json.dumps(body), headers=headers)
            if not r.ok:
                raise RuntimeError(f"HTTP {r.status} en {path}")
            return r.json()

        tournaments = []
        for y in (TODAY.year, TODAY.year + 1):
            try:
                tournaments += post("getTournaments", {"year": y, "type": "all"}).get("data") or []
            except Exception as e:
                if y == TODAY.year:
                    raise
                print(f"aviso: sin datos de {y}: {e}")

        def fetch(slug, gender, d):
            body = {"slug": slug, "isFavourite": False, "gender": gender, "matchStatus": "All"}
            if d:
                body["date"] = d
            return post("getTournamentMatches", body)

        events = build(tournaments, fetch)
        browser.close()

    uniq = {(e["s"], e.get("start") or e["date"], e["title"]): e for e in events}
    events = sorted(uniq.values(), key=lambda e: (e.get("start") or e["date"] + "T99"))
    try:
        same = json.loads(OUT.read_text("utf-8")).get("events") == events
    except Exception:
        same = False
    if not same:
        OUT.write_text(json.dumps({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z"),
                                   "events": events}, ensure_ascii=False, indent=1), "utf-8")
    real = sum(1 for e in events if "start" in e)
    print(f"padel: {len(events)} eventos ({real} con hora real, {len(events) - real} estimados)")
    print("rondas vistas en la web:", sorted(SEEN_ROUNDS))
    for line in DEBUG[:40]:
        print("  ", line)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR en padel.py: {e!r}")
        sys.exit(1)
