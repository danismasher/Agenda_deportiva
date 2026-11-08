"""Diagnostico unico: descubre de donde saca premierpadel.com el cronograma."""
from playwright.sync_api import sync_playwright

URL = "https://premierpadel.com/es/tournaments-detail/dubai-p1-3"
n = 0

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(locale="es-ES")

    def on_response(r):
        global n
        ct = r.headers.get("content-type", "")
        if "json" in ct and r.request.resource_type in ("xhr", "fetch") and n < 25:
            n += 1
            try:
                body = r.text()
            except Exception:
                body = ""
            print(f"API {r.status} {r.url} (len {len(body)})")
            print("   " + body[:500].replace("\n", " "))

    page.on("response", on_response)
    page.goto(URL, wait_until="networkidle", timeout=90000)
    for label in ("CRONOGRAMA", "Cronograma", "SCHEDULE"):
        try:
            page.get_by_text(label, exact=True).first.click(timeout=3000)
            break
        except Exception:
            pass
    page.wait_for_timeout(6000)
    print("=== TEXTO VISIBLE ===")
    print(page.inner_text("body")[:2500])
    browser.close()
