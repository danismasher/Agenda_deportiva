#!/usr/bin/env python3
"""Lee premierpadel.com y genera padel.json con cuartos, semifinales y finales."""
import json, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "padel.json"
API = "https://api-prod.premierpadel.com/api/tournament/"
LIST = "https://premierpadel.com/es/tournaments"
TODAY = datetime.now(timezone.utc).date()
GENDER = {"male": "masculino", "female": "femenino"}
SEEN_ROUNDS = set()


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


def real_events(tname, gender, matches):
    out = []
    for m in matches:
        r = rnd(m.get("round_name"))
        if not r:
            continue
        teams = sorted(m.get("teams") or [], key=lambda t: t.get("team_no", 0))
        a, b = (pair(teams[0]), pair(teams[1])) if len(teams) >= 2 else ("", "")
        title = f"{a} – {b}" if a and b else f"{r} {GENDER[gender]}"
        sub = f"{r} {GENDER[gender]}, {tname}"
        sdt = m.get("start_date_time")
        if sdt:
            start = sdt.strip().replace(" ", "T")[:19] + "Z"
            start = start[:16] + ":00Z"
            out.append({"s": "padel", "start": start, "title": title, "sub": sub, "_round": r})
        elif m.get("date"):
            out.append({"s": "padel", "date": m["date"], "tbc": True, "title": title, "sub": sub, "_round": r})
    return out


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
        if end < TODAY or start > TODAY + timedelta(days=60):
            continue
        tname = (t.get("name") or t["slug"]).title()
        real = []
        if start <= TODAY + timedelta(days=14):
            for gender in GENDER:
                first = fetch_matches(t["slug"], gender, None)
                dates = (first.get("data") or {}).get("date") or []
                for d in dates:
                    if day(d) < TODAY - timedelta(days=1):
                        continue
                    data = fetch_matches(t["slug"], gender, d)
                    ms = [m for c in (data.get("data") or {}).get("courts", []) for m in (c.get("matches") or [])]
                    real += real_events(tname, gender, ms)
        have = {e["_round"] for e in real}
        events += [{k: v for k, v in e.items() if k != "_round"} for e in real]
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
    OUT.write_text(json.dumps({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z"),
                               "events": events}, ensure_ascii=False, indent=1), "utf-8")
    real = sum(1 for e in events if "start" in e)
    print(f"padel: {len(events)} eventos ({real} con hora real, {len(events) - real} estimados)")
    print("rondas vistas en la web:", sorted(SEEN_ROUNDS))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR en padel.py: {e!r}")
        sys.exit(1)
