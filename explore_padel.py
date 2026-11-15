"""Diagnostico: de donde saca motogp.com sus resultados (el nombre del archivo se mantiene
para no tocar la automatizacion 'Explorar padel')."""
import json

PAGES = [
    ("CARRERA", "https://www.motogp.com/es/gp-results/2026/qat/motogp/rac/classification"),
    ("SPRINT", "https://www.motogp.com/es/gp-results/2026/qat/motogp/spr/classification"),
]
SKIP = ("google", "cookiebot", "doubleclick", "facebook", "tiktok", "onetrust", "clarity", "hotjar",
        "newrelic", "sentry", "gtm", "analytics", "snapchat", "twitter", "linkedin", "adobe", "demdex")


def shape(obj, depth=0):
    if isinstance(obj, dict):
        return {k: (shape(v, depth + 1) if depth < 1 else type(v).__name__) for k, v in list(obj.items())[:15]}
    if isinstance(obj, list):
        return f"lista de {len(obj)}: " + (json.dumps(shape(obj[0], depth + 1), ensure_ascii=False)[:300] if obj else "")
    return type(obj).__name__


def main():
    from playwright.sync_api import sync_playwright
    store = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, url in PAGES:
            page = browser.new_page(locale="es-ES")

            def on_resp(r, label=label):
                u = r.url.lower()
                if r.request.resource_type not in ("xhr", "fetch") or any(s in u for s in SKIP):
                    return
                try:
                    data = r.json()
                except Exception:
                    return
                store.setdefault(label, []).append((r.request, r.status, data))

            page.on("response", on_resp)
            page.goto(url, wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(6000)
            store.setdefault(label + "_TEXTO", []).append(page.inner_text("body")[:1800])
            page.close()
        browser.close()

    for label, _ in PAGES:
        print(f"\n===== {label} =====")
        for req, status, data in store.get(label, [])[:30]:
            print(f"\n{req.method} {status} {req.url}")
            print("  post_data:", (req.post_data or "")[:300])
            print("  cabeceras:", sorted(k for k in req.headers if k.lower() not in ("user-agent", "accept-language", "sec-ch-ua")))
            print("  estructura:", json.dumps(shape(data), ensure_ascii=False)[:600])
            print("  inicio:", json.dumps(data, ensure_ascii=False)[:500])
        for t in store.get(label + "_TEXTO", []):
            print(f"\n--- texto visible ({label}) ---\n{t}")


if __name__ == "__main__":
    main()
