"""Diagnostico 2: estructura de los datos de premierpadel.com (partidos y calendario)."""
import json
from collections import Counter

DETAIL = "https://premierpadel.com/es/tournaments-detail/dubai-p1-3"
LIST = "https://premierpadel.com/es/tournaments"
KEYS = ("slug", "name", "title", "category_id", "country", "gender", "start_date_utc", "end_date_utc")


def find_list(obj, depth=0):
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return obj
    if isinstance(obj, dict) and depth < 3:
        for v in obj.values():
            r = find_list(v, depth + 1)
            if r:
                return r
    return None


def summarize_matches(data):
    courts = (data.get("data") or {}).get("courts") or []
    matches = [m for c in courts for m in (c.get("matches") or [])]
    print(f"  data keys: {list((data.get('data') or {}).keys())}")
    print(f"  pistas: {len(courts)}, partidos: {len(matches)}")
    print("  round_name:", dict(Counter(m.get('round_name') for m in matches)))
    print("  status:", dict(Counter(m.get('status') for m in matches)))
    if matches:
        print("  PARTIDO EJEMPLO:", json.dumps(matches[0], ensure_ascii=False)[:1800])
    others = [m for m in matches if not str(m.get("round_name", "")).upper().startswith("Q")]
    for m in others[:2]:
        print("  PARTIDO RONDA PRINCIPAL:", json.dumps(m, ensure_ascii=False)[:1800])


def summarize_list(data):
    items = find_list(data)
    if not items:
        print("  (sin lista)")
        return
    print(f"  elementos: {len(items)}; claves del primero: {list(items[0].keys())[:25]}")
    for it in items[:40]:
        print("   ", {k: it.get(k) for k in KEYS if k in it})


def main():
    from playwright.sync_api import sync_playwright
    store = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, url in (("detalle", DETAIL), ("calendario", LIST)):
            page = browser.new_page(locale="es-ES")

            def on_resp(r, label=label):
                if "api-prod.premierpadel.com" in r.url and r.request.resource_type in ("xhr", "fetch"):
                    try:
                        data = r.json()
                    except Exception:
                        return
                    store.setdefault(label, []).append((r.request, data))

            page.on("response", on_resp)
            page.goto(url, wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(5000)
            page.close()
        browser.close()

    for label, calls in store.items():
        print(f"\n===== {label.upper()} =====")
        for req, data in calls:
            if "ournament" not in req.url and "chedule" not in req.url:
                continue
            names = sorted(k for k in req.headers if k.lower() not in ("user-agent", "accept-language", "sec-ch-ua"))
            print(f"\n{req.method} {req.url}")
            print("  post_data:", (req.post_data or "")[:300])
            print("  cabeceras:", names)
            if req.url.endswith("getTournamentMatches"):
                summarize_matches(data)
            else:
                summarize_list(data)


if __name__ == "__main__":
    main()
