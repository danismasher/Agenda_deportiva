#!/usr/bin/env python3
"""Resultados de MotoGP (sprint y carrera) leidos de motogp.com con un navegador.
Genera motogp.json con los eventos ya disputados y su clasificacion."""
import json, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "motogp.json"
BASE = "https://www.motogp.com/es/gp-results"
TODAY = datetime.now(timezone.utc).date()
KEEP = 90
RETRY_DAYS = 14
SESSIONS = (("spr", "Carrera sprint", 1), ("rac", "Carrera", 0))  # codigo, titulo, dias antes del fin del GP
DEBUG = []
FMT = 2  # version del formato; si cambia, se vuelven a leer los resultados


def find_rows(obj, depth=0):
    """Primera lista de dicts con 'position' y 'rider' (la clasificacion)."""
    if isinstance(obj, list):
        if len(obj) >= 3 and all(isinstance(x, dict) for x in obj[:3]) \
                and "position" in obj[0] and ("rider" in obj[0] or "rider_name" in obj[0]):
            return obj
        if depth < 4:
            for v in obj[:3]:
                r = find_rows(v, depth + 1)
                if r:
                    return r
    elif isinstance(obj, dict) and depth < 4:
        for v in obj.values():
            r = find_rows(v, depth + 1)
            if r:
                return r
    return None


def nm(d):
    return (d.get("name") or "").strip() if isinstance(d, dict) else ""


def rider_name(it):
    r = it.get("rider")
    if isinstance(r, dict):
        n = r.get("full_name") or r.get("name") or f'{r.get("first_name", "")} {r.get("last_name", "")}'.strip()
        if n:
            return n.strip()
    return str(it.get("rider_name") or "").strip()


def last_col(it):
    gap = it.get("gap")
    g = str((gap.get("first") if isinstance(gap, dict) else gap) or "").strip()
    if it.get("position") == 1 and it.get("time"):
        return str(it["time"]).strip()
    if g and g not in ("0", "0.0", "0.000"):
        return g if g[0] in "+-" else "+" + g
    return str(it.get("time") or "").strip()


def to_res(rows):
    out = []
    for it in rows:
        pos = it.get("position")
        team = str(it.get("team_name") or "").strip() or nm(it.get("team")) or nm(it.get("constructor"))
        t = last_col(it)
        out.append(["–" if pos in (None, "") else str(pos), short(rider_name(it)), team, t])
    if not out:
        return None
    return {"head": f"Ganador: {rider_name(rows[0])}", "rows": out}


def short(n):
    p = n.split()
    return f"{p[0][0]}. {' '.join(p[1:])}" if len(p) > 1 else n


def collect(load, prev, tried):
    """load(url) -> lista de (url_api, json). Devuelve (eventos, intentados)."""
    evs = None
    for url in (BASE, f"{BASE}/{TODAY.year}/qat/motogp/rac/classification"):
        for u, d in load(url):
            if "/results/events" in u and isinstance(d, list) and d:
                evs = d
        if evs:
            break
    if not evs:
        raise RuntimeError("no se obtuvo la lista de eventos")
    out, now_tried, shown = [], set(), False
    for ev in evs:
        if ev.get("test") or not ev.get("date_end"):
            continue
        end = date.fromisoformat(ev["date_end"][:10])
        if end > TODAY or end < TODAY - timedelta(days=KEEP):
            continue
        short_name = (ev.get("short_name") or "").strip().lower()
        if len(short_name) != 3:
            DEBUG.append(f"evento sin codigo de 3 letras: {ev.get('short_name')!r} {ev.get('name')!r}")
            continue
        country = (ev.get("country") or {}).get("name") or ev.get("name") or short_name.upper()
        for code, title, back in SESSIONS:
            d = (end - timedelta(days=back)).isoformat()
            key = f"{d}|{title}"
            old = prev.get(key)
            if old and old.get("res"):
                out.append(old)
                continue
            if key in tried and end < TODAY - timedelta(days=RETRY_DAYS):
                now_tried.add(key)
                continue
            caps = load(f"{BASE}/{end.year}/{short_name}/motogp/{code}/classification")
            rows = None
            for u, data in caps:
                if "classification" in u:
                    rows = find_rows(data)
                    if rows:
                        if not shown:
                            shown = True
                            DEBUG.append("ejemplo de fila: " + json.dumps(rows[0], ensure_ascii=False)[:700])
                        break
            res = to_res(rows) if rows else None
            DEBUG.append(f"{short_name} {code}: {'OK' if res else 'sin resultado'} "
                         f"(llamadas: {[u.split('/motogp/v1/')[-1][:60] for u, _ in caps if 'pulselive' in u][:6]})")
            if res:
                out.append({"s": "motogp", "date": d, "tbc": True, "title": title,
                            "sub": f"GP {country}", "res": res})
            else:
                now_tried.add(key)
    return out, now_tried


def main():
    from playwright.sync_api import sync_playwright
    prev, tried = {}, set()
    if OUT.exists():
        try:
            j = json.loads(OUT.read_text("utf-8"))
            if j.get("fmt") == FMT:
                prev = {f'{e.get("date")}|{e["title"]}': e for e in j.get("events", [])}
                tried = set(j.get("tried", []))
        except Exception:
            pass
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="es-ES")

        def load(url):
            page = ctx.new_page()
            caps = []

            def on_resp(r):
                if "api.pulselive.motogp.com" in r.url and r.request.resource_type in ("xhr", "fetch"):
                    try:
                        caps.append((r.url, r.json()))
                    except Exception:
                        pass

            page.on("response", on_resp)
            try:
                page.goto(url, wait_until="networkidle", timeout=90000)
                page.wait_for_timeout(2500)
            except Exception as e:
                DEBUG.append(f"fallo al abrir {url}: {e!r}")
            page.close()
            return caps

        events, now_tried = collect(load, prev, tried)
        browser.close()
    new = {"fmt": FMT, "events": events, "tried": sorted(now_tried)}
    try:
        j = json.loads(OUT.read_text("utf-8"))
        same = {"fmt": j.get("fmt"), "events": j.get("events"), "tried": j.get("tried")} == new
    except Exception:
        same = False
    if not same:
        OUT.write_text(json.dumps({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z"), **new},
                                  ensure_ascii=False, indent=1), "utf-8")
    print(f"motogp: {len(events)} sesiones con resultado")
    for line in DEBUG[:30]:
        print("  ", line)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR en motogp.py: {e!r}")
        for line in DEBUG[:30]:
            print("  ", line)
        sys.exit(1)
