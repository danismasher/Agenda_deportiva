#!/usr/bin/env python3
"""Genera events.json con los eventos deportivos. Solo usa la libreria estandar."""
import json, re, sys, time, unicodedata, urllib.request, urllib.error
from html.parser import HTMLParser
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "events.json"
MANUAL = ROOT / "manual.json"
UA = {"User-Agent": "agenda-deportiva/1.0 (uso personal)"}
NOW = datetime.now(timezone.utc)
TODAY = NOW.date()
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
BACK = 14   # dias hacia atras que se vuelven a consultar para recoger resultados
WSTART = TODAY - timedelta(days=BACK)
KEEP = 90   # dias que se conservan los eventos pasados
OLD = {}    # eventos de la ejecucion anterior, por clave


def ekey(e):
    return (e["s"], e.get("start") or e.get("date"), e["title"])


class HttpFail(Exception):
    def __init__(self, code, url):
        super().__init__(f"HTTP {code} en {url}")
        self.code = code


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
            if 400 <= e.code < 500:
                raise HttpFail(e.code, url)
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


BROWSER_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0 Safari/537.36", "Accept-Language": "en"}


def get_html(url, tries=2):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=BROWSER_UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if 400 <= e.code < 500:
                raise HttpFail(e.code, url)
            last = e
        except Exception as e:
            last = e
        time.sleep(2 * (i + 1))
    raise last


class TableParser(HTMLParser):
    """Lee la primera tabla de una pagina: filas -> celdas -> trozos de texto."""

    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.depth, self.done = [], None, None, 0, False

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if tag == "table":
            self.depth += 1
        elif self.depth and tag == "tr":
            self.row = []
        elif self.depth and tag in ("td", "th"):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None and data.strip():
            self.cell.append(data.strip())

    def handle_endtag(self, tag):
        if self.done:
            return
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.depth:
            self.depth -= 1
            if self.depth == 0:
                self.done = True


def ctext(cell):
    return " ".join(cell).strip()


def f1_driver(cell):
    nodes = list(cell)
    if len(nodes) >= 2 and re.fullmatch(r"[A-Z]{3}", nodes[-1]):
        return " ".join(nodes[:-1]).strip()
    s = " ".join(nodes).strip()
    m = re.match(r"^(.*?)([A-Z]{3})$", s)
    return m.group(1).strip() if m else s


def short_name(n):
    p = n.split()
    return f"{p[0][0]}. {' '.join(p[1:])}" if len(p) > 1 else n


def f1_table_res(html, kind):
    p = TableParser()
    p.feed(html)
    rows = p.rows
    if len(rows) < 2:
        return None
    hdr = [ctext(c).lower() for c in rows[0]]

    def col(*keys):
        for i, h in enumerate(hdr):
            if any(h.startswith(k) for k in keys):
                return i
        return None

    ip, idr, it, tcol = col("pos"), col("driver"), col("team"), col("time")
    qcols = [i for i, h in enumerate(hdr) if h in ("q1", "q2", "q3")]
    if idr is None:
        return None
    out, full = [], []
    for r in rows[1:]:
        if len(r) <= idr:
            continue
        pos = ctext(r[ip]) if ip is not None and ip < len(r) else str(len(out) + 1)
        name = f1_driver(r[idr])
        team = ctext(r[it]) if it is not None and it < len(r) else ""
        last = ""
        if kind in ("qualifying", "sprintq"):
            for i in reversed(qcols):
                if i < len(r) and ctext(r[i]):
                    last = ctext(r[i])
                    break
        elif tcol is not None and tcol < len(r):
            last = ctext(r[tcol])
        out.append([pos, short_name(name), team, last])
        full.append(name)
    if not out:
        return None
    label = "Pole" if kind in ("qualifying", "sprintq") else "Ganador"
    return {"head": f"{label}: {full[0]}", "rows": out}


F1_PAGES = {"results": ["race-result"], "sprint": ["sprint-results", "sprint"],
            "qualifying": ["qualifying"], "sprintq": ["sprint-qualifying", "sprint-shootout"]}


def f1_official_index(year):
    """(id, slug) de cada gran premio, en orden de calendario, segun formula1.com."""
    html = get_html(f"https://www.formula1.com/en/results/{year}/races")
    if not html:
        return []
    seen, out = set(), []
    for rid, slug in re.findall(rf"/en/results/{year}/races/(\d+)/([a-z0-9-]+)/race-result", html):
        if rid not in seen:
            seen.add(rid)
            out.append((rid, slug))
    return out


def f1_official_result(year, race, kind, cache):
    rid, slug = race
    for page in F1_PAGES.get(kind, []):
        k = (year, rid, page)
        if k not in cache:
            html = None
            try:
                html = get_html(f"https://www.formula1.com/en/results/{year}/races/{rid}/{slug}/{page}")
            except Exception as e:
                print(f"aviso: formula1.com {slug}/{page}: {e}")
            cache[k] = f1_table_res(html, kind) if html else None
            time.sleep(0.5)
        if cache[k]:
            return cache[k]
    return None


# ---------- F1 (calendario: Jolpica; resultados: formula1.com) ----------
F1_SESSIONS = [
    ("Qualifying", "Clasificación"),
    ("SprintQualifying", "Clasificación sprint"),
    ("SprintShootout", "Clasificación sprint"),
    ("Sprint", "Carrera sprint"),
]


RES_KIND = {"Carrera": "results", "Carrera sprint": "sprint", "Clasificación": "qualifying",
            "Clasificación sprint": "sprintq"}


def f1_name(d):
    return f'{(d.get("givenName") or "?")[:1]}. {d.get("familyName", "")}'


def f1_result(year, rd, kind, cache):
    k = (year, rd, kind)
    if k not in cache:
        data = get_json(f"https://api.jolpi.ca/ergast/f1/{year}/{rd}/{kind}.json")
        races = (((data or {}).get("MRData") or {}).get("RaceTable") or {}).get("Races") or []
        cache[k] = races[0] if races else None
        time.sleep(0.5)
    race = cache[k]
    if not race:
        return None
    field = "QualifyingResults" if kind == "qualifying" else ("SprintResults" if kind == "sprint" else "Results")
    lst = race.get(field) or []
    if not lst:
        return None
    rows = []
    for x in lst[:10]:
        if kind == "qualifying":
            last = x.get("Q3") or x.get("Q2") or x.get("Q1") or ""
        else:
            last = (x.get("Time") or {}).get("time") or x.get("status", "")
        rows.append([x.get("position", ""), f1_name(x["Driver"]), x["Constructor"]["name"], last])
    d0 = lst[0]["Driver"]
    label = "Pole" if kind == "qualifying" else "Ganador"
    return {"head": f'{label}: {d0.get("givenName", "")} {d0.get("familyName", "")}', "rows": rows}


def f1():
    out, cache, ocache = [], {}, {}
    now = datetime.now(timezone.utc)
    for year in (TODAY.year, TODAY.year + 1):
        data = get_json(f"https://api.jolpi.ca/ergast/f1/{year}.json")
        if not data:
            continue
        races = sorted(data["MRData"]["RaceTable"]["Races"], key=lambda r: int(r["round"]))
        if not races:
            continue
        try:
            official = f1_official_index(year)
        except Exception as e:
            print(f"aviso: sin indice de formula1.com ({e})")
            official = []
        if official and len(official) != len(races):
            print(f"aviso: formula1.com tiene {len(official)} carreras y el calendario {len(races)}; se usa Jolpica")
            official = []
        for n, race in enumerate(races):
            gp = "GP " + race["raceName"].replace(" Grand Prix", "")
            rd = int(race["round"])
            sessions = [(race.get(k), t) for k, t in F1_SESSIONS]
            sessions.append(({"date": race["date"], "time": race.get("time")}, "Carrera"))
            for s, title in sessions:
                if not s:
                    continue
                ev = mk("f1", s["date"], s.get("time"), title, gp)
                kind = RES_KIND.get(title)
                if kind and "start" in ev:
                    st = parse(ev["start"])
                    old = OLD.get(ekey(ev))
                    if old and old.get("res"):
                        ev["res"] = old["res"]
                    elif st + timedelta(hours=3) < now and st >= now - timedelta(days=KEEP) \
                            and (old is None or st >= now - timedelta(days=14)):
                        r = None
                        if official:
                            r = f1_official_result(year, official[n], kind, ocache)
                        if not r and kind in ("results", "sprint", "qualifying"):
                            try:
                                r = f1_result(year, rd, kind, cache)
                            except Exception as e:
                                print(f"aviso: sin resultado F1 {year}/{rd}/{kind}: {e}")
                        if r:
                            ev["res"] = r
                out.append(ev)
    return out


# ---------- ESPN (NFL, LaLiga, Champions, tenis) ----------
def scoreboard(path, d, e):
    """Eventos entre las fechas d y e. Si ESPN rechaza el rango, pide dia a dia."""
    try:
        data = get_json(f"{ESPN}/{path}/scoreboard?dates={d:%Y%m%d}-{e:%Y%m%d}&limit=300") or {}
        return data.get("events", [])
    except HttpFail as err:
        if err.code != 400 or d == e:
            raise
    out, day, total, fails, last = [], d, 0, 0, None
    while day <= e:
        total += 1
        try:
            data = get_json(f"{ESPN}/{path}/scoreboard?dates={day:%Y%m%d}&limit=300") or {}
            out += data.get("events", [])
        except HttpFail as err:
            fails, last = fails + 1, err
        day += timedelta(days=1)
        time.sleep(0.3)
    if fails == total:
        raise last
    return out


def espn_events(path, days, step):
    seen = {}
    d, end = WSTART, TODAY + timedelta(days=days)
    while d <= end:
        e = min(d + timedelta(days=step - 1), end)
        for ev in scoreboard(path, d, e):
            seen[ev["id"]] = ev
        d = e + timedelta(days=1)
        time.sleep(0.5)
    return list(seen.values())


def txt(v):
    if isinstance(v, dict):
        v = v.get("displayValue", v.get("value"))
    return "" if v is None else str(v).strip()


def is_done(*objs):
    for o in objs:
        t = ((o or {}).get("status") or {}).get("type") or {}
        if t.get("completed"):
            return True
    return False


# nombres cortos de estadios: (fragmento normalizado, nombre corto). Gana el primero que encaje.
VENUES = [
    # LaLiga
    ("bernabeu", "Bernabéu"), ("metropolitano", "Metropolitano"), ("camp nou", "Camp Nou"),
    ("sanchez pizjuan", "Sánchez Pizjuán"), ("benito villamarin", "Benito Villamarín"),
    ("ceramica", "La Cerámica"), ("mestalla", "Mestalla"), ("san mames", "San Mamés"),
    ("reale arena", "Reale Arena"), ("anoeta", "Reale Arena"), ("balaidos", "Balaídos"),
    ("mendizorrotza", "Mendizorrotza"), ("vallecas", "Vallecas"), ("coliseum", "Coliseum"),
    ("el sadar", "El Sadar"), ("montjuic", "Montjuïc"), ("rcde", "RCDE Stadium"), ("son moix", "Son Moix"),
    ("ipurua", "Ipurua"), ("rosaleda", "La Rosaleda"), ("riazor", "Riazor"), ("gran canaria", "Gran Canaria"),
    ("carmenes", "Los Cármenes"), ("molinon", "El Molinón"), ("montilivi", "Montilivi"),
    ("romareda", "La Romareda"), ("alcoraz", "El Alcoraz"), ("zorrilla", "Zorrilla"), ("butarque", "Butarque"),
    ("ciutat de valencia", "Ciutat de València"), ("carranza", "Carranza"), ("la cartuja", "La Cartuja"),
    # Champions
    ("emirates", "Emirates"), ("anfield", "Anfield"), ("etihad", "Etihad"), ("old trafford", "Old Trafford"),
    ("stamford bridge", "Stamford Bridge"), ("tottenham hotspur", "Tottenham"), ("allianz arena", "Allianz Arena"),
    ("allianz stadium", "Allianz Stadium"), ("signal iduna", "Signal Iduna Park"), ("giuseppe meazza", "San Siro"),
    ("san siro", "San Siro"), ("parc des princes", "Parc des Princes"), ("cruijff", "Johan Cruyff Arena"),
    ("cruyff", "Johan Cruyff Arena"), ("de kuip", "De Kuip"), ("da luz", "Estádio da Luz"),
    ("alvalade", "Alvalade"), ("dragao", "Estádio do Dragão"), ("olimpico", "Olímpico"), ("bombonera", "La Bombonera"),
    # NFL
    ("superdome", "Superdome"), ("state farm", "State Farm"), ("mercedes-benz", "Mercedes-Benz"),
    ("m&t bank", "M&T Bank"), ("highmark", "Highmark"), ("bank of america", "Bank of America"),
    ("soldier field", "Soldier Field"), ("paycor", "Paycor"), ("huntington bank", "Huntington Bank"),
    ("at&t", "AT&T"), ("mile high", "Mile High"), ("ford field", "Ford Field"), ("lambeau", "Lambeau"),
    ("nrg", "NRG"), ("lucas oil", "Lucas Oil"), ("everbank", "EverBank"), ("arrowhead", "Arrowhead"),
    ("allegiant", "Allegiant"), ("sofi", "SoFi"), ("hard rock", "Hard Rock"), ("u.s. bank", "U.S. Bank"),
    ("gillette", "Gillette"), ("metlife", "MetLife"), ("lincoln financial", "Lincoln Financial"),
    ("acrisure", "Acrisure"), ("levi", "Levi's"), ("lumen", "Lumen Field"), ("raymond james", "Raymond James"),
    ("nissan stadium", "Nissan"), ("northwest stadium", "Northwest"), ("fedex", "FedEx"),
    # NHL
    ("td garden", "TD Garden"), ("madison square", "MSG"), ("scotiabank arena", "Scotiabank Arena"),
    ("bell centre", "Bell Centre"), ("rogers place", "Rogers Place"), ("saddledome", "Saddledome"),
    ("t-mobile arena", "T-Mobile Arena"), ("ball arena", "Ball Arena"), ("amalie", "Amalie Arena"),
    ("amerant", "Amerant"), ("crypto.com", "Crypto.com"), ("sap center", "SAP Center"), ("ppg paints", "PPG Paints"),
    ("capital one", "Capital One"), ("american airlines", "American Airlines"), ("united center", "United Center"),
    ("wells fargo", "Wells Fargo"), ("prudential center", "Prudential"), ("ubs arena", "UBS Arena"),
    ("nationwide", "Nationwide"), ("pnc arena", "PNC Arena"), ("lenovo center", "Lenovo Center"),
    ("keybank", "KeyBank"), ("little caesars", "Little Caesars"), ("xcel energy", "Xcel Energy"),
    ("enterprise center", "Enterprise Center"), ("bridgestone arena", "Bridgestone"), ("climate pledge", "Climate Pledge"),
    ("rogers arena", "Rogers Arena"), ("honda center", "Honda Center"), ("canada life", "Canada Life"),
    ("delta center", "Delta Center"), ("grand casino", "Grand Casino"), ("mullett", "Mullett Arena"),
    ("wembley", "Wembley"), ("maracana", "Maracanã"), ("azteca", "Azteca"), ("croke park", "Croke Park"),
]
GENERIC = {"estadio", "estadi", "estadio", "estádio", "stadium", "stadion", "stadio", "stade", "municipal", "de", "del",
           "la", "el", "los", "las", "do", "da", "di"}


def short_venue(name, limit=20):
    """Nombre de estadio recortado para la tarjeta, sin perder lo importante."""
    name = (name or "").strip()
    n = norm(name)
    for key, val in VENUES:
        if key in n:
            return val
    words = [w for w in name.replace("-", " - ").split() if norm(w) not in GENERIC and w != "-"] or name.split()
    s = " ".join(words)
    while len(s) > limit and len(words) > 2:
        words = words[1:]
        s = " ".join(words)
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s


def team_logo(team):
    u = team.get("logo")
    if not u:
        for lg in team.get("logos") or []:
            if lg.get("href"):
                u = lg["href"]
                break
    return (u or "").replace("http://", "https://")


def matches(path, sport, days, step):
    out = []
    for ev in espn_events(path, days, step):
        comp = ev["competitions"][0]
        t = {c["homeAway"]: c["team"]["displayName"] for c in comp["competitors"]}
        if "home" not in t or "away" not in t:
            continue
        venue = short_venue((comp.get("venue") or {}).get("fullName", ""))
        item = {"s": sport, "start": iso(parse(ev["date"])),
                "title": f'{t["home"]} – {t["away"]}', "sub": venue}
        lg = {c["homeAway"]: team_logo(c["team"]) for c in comp["competitors"]}
        if lg.get("home") and lg.get("away"):
            item["ic"] = [lg["home"], lg["away"]]
        if is_done(ev, comp):
            sc = {c["homeAway"]: txt(c.get("score")) for c in comp["competitors"]}
            if sc.get("home") and sc.get("away"):
                item["res"] = {"head": f'{t["home"]} {sc["home"]} – {sc["away"]} {t["away"]}'}
        out.append(item)
    return out


def nhl_name(t):
    pn = (t.get("placeName") or {}).get("default", "")
    cn = (t.get("commonName") or {}).get("default", "")
    return f"{pn} {cn}".strip() or t.get("abbrev", "")


def nhl_official(days=60):
    """Calendario y resultados de la API oficial de la NHL (api-web.nhle.com)."""
    out, seen = [], set()
    d, end = WSTART, TODAY + timedelta(days=days)
    while d <= end:
        data = get_json(f"https://api-web.nhle.com/v1/schedule/{d.isoformat()}") or {}
        for day in data.get("gameWeek") or []:
            for g in day.get("games") or []:
                try:
                    if g["id"] in seen or g.get("gameType") not in (2, 3):
                        continue
                    seen.add(g["id"])
                    home, away = g["homeTeam"], g["awayTeam"]
                    item = {"s": "nhl", "start": iso(parse(g["startTimeUTC"])),
                            "title": f"{nhl_name(home)} – {nhl_name(away)}",
                            "sub": short_venue((g.get("venue") or {}).get("default", ""))}
                    if home.get("logo") and away.get("logo"):
                        item["ic"] = [home["logo"], away["logo"]]
                    hs, as_ = home.get("score"), away.get("score")
                    if g.get("gameState") in ("FINAL", "OFF") and hs is not None and as_ is not None:
                        extra = {"OT": " (prórroga)", "SO": " (penaltis)"}.get(
                            (g.get("gameOutcome") or {}).get("lastPeriodType"), "")
                        item["res"] = {"head": f"{nhl_name(home)} {hs} – {as_} {nhl_name(away)}{extra}"}
                    out.append(item)
                except Exception:
                    continue
        nxt = data.get("nextStartDate")
        try:
            nd = date.fromisoformat(nxt) if nxt else None
        except Exception:
            nd = None
        d = nd if nd and nd > d else d + timedelta(days=7)
        time.sleep(0.3)
    return out


def nhl():
    try:
        out = nhl_official()
        if out:
            return out
        print("aviso: la API oficial de la NHL no devolvió partidos; se usa ESPN")
    except Exception as e:
        print(f"aviso: API oficial de la NHL no disponible ({e}); se usa ESPN")
    return matches("hockey/nhl", "nhl", 60, 7)


def short(name):
    p = name.split()
    return f"{p[0][0]}. {' '.join(p[1:])}" if len(p) > 1 else name


def tennis_res(c, names):
    try:
        if not is_done(c):
            return None
        ps = c.get("competitors") or []
        ls = [[int(float(s.get("value"))) for s in (p.get("linescores") or []) if s.get("value") is not None]
              for p in ps]
        win = next((i for i, p in enumerate(ps) if p.get("winner")), None)
        if win is None or len(ls) != 2 or not ls[0] or len(ls[0]) != len(ls[1]):
            return None
        sets = " ".join(f"{ls[win][i]}-{ls[1 - win][i]}" for i in range(len(ls[0])))
        return {"head": f"Gana {short(names[win])}: {sets}"}
    except Exception:
        return None


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
            res = tennis_res(c, names)
            if res:
                item["res"] = res
            k = (item["start"], item["title"])
            if k not in seen:
                seen.add(k)
                out.append(item)
    return out


def indycar():
    f = ROOT / "indycar.json"
    if not f.exists():
        return []
    return json.loads(f.read_text("utf-8")).get("events", [])


def motogp():
    f = ROOT / "motogp.json"
    if not f.exists():
        return []
    return json.loads(f.read_text("utf-8")).get("events", [])


def padel():
    f = ROOT / "padel.json"
    if not f.exists():
        return []
    return json.loads(f.read_text("utf-8")).get("events", [])


SOURCES = {
    "f1": f1,
    "nfl": lambda: matches("football/nfl", "nfl", 100, 7),
    "nhl": nhl,
    "laliga": lambda: matches("soccer/esp.1", "laliga", 100, 7),
    "champions": lambda: matches("soccer/uefa.champions", "champions", 100, 7),
    "tenis": tennis,
    "padel": padel,
    "motogp": motogp,
    "indy": indycar,
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
    OLD.update({ekey(e): e for e in old if "s" in e and "title" in e})
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
        mkeys = {((x.get("start") or x.get("date"))[:10], x["title"]): x for x in m if x.get("s") == "motogp"}
        kept = []
        for e in events:
            if e["s"] == "motogp":
                k = ((e.get("start") or e.get("date"))[:10], e["title"])
                if k in mkeys:  # el manual tiene hora; solo se le pasa el resultado
                    if e.get("res"):
                        mkeys[k]["res"] = e["res"]
                    continue
            kept.append(e)
        events = kept + m
        report.append(f"manual: {len(m)} eventos")
    except Exception as e:
        report.append(f"manual: ERROR {e!r}")

    # eventos antiguos (ya fuera de la ventana de consulta) que se conservan con su resultado
    wstart = WSTART.isoformat()
    for o in old:
        if o.get("s") in ("nfl", "nhl", "laliga", "champions", "tenis", "padel") and \
                (o.get("start") or o.get("date") or "9")[:10] < wstart:
            events.append(o)

    keep_from = (TODAY - timedelta(days=KEEP)).isoformat()
    uniq = {}
    for e in events:
        key = e.get("start") or e.get("date")
        if key[:10] < keep_from:
            continue
        uniq[(e["s"], key, e["title"])] = e
    ordered = sorted(uniq.values(), key=lambda e: ((e.get("start") or e["date"] + "T99"), e["s"]))
    for e in ordered:
        o = OLD.get(ekey(e))
        if "res" not in e and o and o.get("res"):
            e["res"] = o["res"]
    n_res = sum(1 for e in ordered if e.get("res"))
    report.append(f"resultados: {n_res} eventos con resultado")
    if old == ordered:
        report.append("sin cambios: no se reescribe events.json")
    else:
        OUT.write_text(json.dumps({"updated": iso(NOW), "events": ordered},
                                  ensure_ascii=False, indent=1), "utf-8")
    print("\n".join(report))
    print(f"Total: {len(ordered)} eventos")
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
