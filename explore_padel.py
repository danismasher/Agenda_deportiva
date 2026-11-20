"""Diagnostico: de donde saca indycar.com su calendario y sus resultados (el nombre del archivo se
mantiene para no tocar la automatizacion 'Explorar padel')."""
import json

START = "https://www.indycar.com/schedule?year=2026"
SKIP = ("google", "cookiebot", "doubleclick", "facebook", "tiktok", "onetrust", "cookielaw", "clarity", "hotjar",
        "newrelic", "sentry", "gtm", "analytics", "snapchat", "twitter", "linkedin", "adobe", "demdex", "optimizely")


def visit(ctx, url, label, show_text=1200):
    page = ctx.new_page()
    caps = []

    def on_resp(r):
        u = r.url.lower()
        if r.request.resource_type in ("xhr", "fetch") and not any(s in u for s in SKIP):
            try:
                caps.append((r.request.method, r.status, r.url, json.dumps(r.json(), ensure_ascii=False)[:350]))
            except Exception:
                caps.append((r.request.method, r.status, r.url, "(no es JSON)"))

    page.on("response", on_resp)
    try:
        page.goto(url, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(4000)
    except Exception as e:
        print(f"fallo al abrir {url}: {e!r}")
    links = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
    text = page.inner_text("body")[:show_text]
    title = page.title()
    page.close()
    print(f"\n===== {label}: {url} =====\ntitulo: {title}")
    for c in caps[:15]:
        print(f"  API {c[0]} {c[1]} {c[2]}\n      {c[3]}")
    return links, text


def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="en-US")
        links, text = visit(ctx, START, "CALENDARIO 2026", show_text=900)
        print("\n--- texto ---\n" + text)
        uniq = []
        for l in links:
            ll = l.lower()
            if l not in uniq and ("result" in ll or "/race" in ll or "schedule/" in ll or "/event" in ll):
                uniq.append(l)
        print("\n--- enlaces de resultados/carreras ---")
        for l in uniq[:50]:
            print("  ", l)
        cand = [l for l in uniq if "result" in l.lower() and "2026" in l][:2] or [l for l in uniq if "result" in l.lower()][:2]
        for n, l in enumerate(cand):
            _, t = visit(ctx, l, f"RESULTADOS {n + 1}")
            print("\n--- texto ---\n" + t)
        browser.close()


if __name__ == "__main__":
    main()
