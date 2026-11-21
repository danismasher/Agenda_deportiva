"""Diagnostico: como muestra indycar.com los horarios de las sesiones de cada evento (el nombre del
archivo se mantiene para no tocar la automatizacion 'Explorar padel')."""
import json

PAGES = [
    ("EVENTO PASADO", "https://www.indycar.com/Schedule/2026/Laguna-Seca"),
    ("EVENTO FUTURO", "https://www.indycar.com/Schedule/2027/St-Petersburg"),
]
SKIP = ("google", "cookiebot", "doubleclick", "facebook", "tiktok", "onetrust", "cookielaw", "clarity", "hotjar",
        "newrelic", "sentry", "gtm", "analytics", "snapchat", "twitter", "linkedin", "adobe", "demdex", "optimizely",
        "ketchcdn", "sharethis", "userway", "jsdelivr", "ecal.com")


def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="en-US")
        for label, url in PAGES:
            page = ctx.new_page()
            caps = []

            def on_resp(r):
                u = r.url.lower()
                if r.request.resource_type in ("xhr", "fetch") and not any(s in u for s in SKIP):
                    try:
                        caps.append((r.request.method, r.status, r.url, json.dumps(r.json(), ensure_ascii=False)[:500]))
                    except Exception:
                        caps.append((r.request.method, r.status, r.url, "(no es JSON)"))

            page.on("response", on_resp)
            try:
                page.goto(url, wait_until="networkidle", timeout=90000)
                page.wait_for_timeout(4000)
            except Exception as e:
                print(f"fallo al abrir {url}: {e!r}")
            print(f"\n===== {label}: {url} =====\ntitulo: {page.title()}")
            for c in caps[:12]:
                print(f"  API {c[0]} {c[1]} {c[2]}\n      {c[3]}")
            txt = page.inner_text("body")
            i = txt.find("SCHEDULE")
            print("\n--- texto ---\n" + txt[max(i, 0):max(i, 0) + 3000])
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
