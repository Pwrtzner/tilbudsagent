"""Find nærmeste butik i hver kæde ud fra en position, og kørselsafstanden dertil.

Butikker: OpenStreetMap via Overpass. Kørselsafstand: OSRM (fri demoserver). Resultatet gemmes i tabellen
`afstand` pr. position, så den samme afstand aldrig slås op to gange. Ingen af tjenesterne kræver nøgle, men begge
er gratis og delte: spørg sjældent. Kan vejafstand ikke hentes, bruges luftlinje gange 1,3 (markeret som sådan).
"""
from __future__ import annotations

import copy
import json
import math
import re
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

OVERPASS_SERVERE = (  # offentlige, gratis spejle; den første der svarer bruges
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OVERPASS = OVERPASS_SERVERE[0]
OSRM = "https://router.project-osrm.org"
LUFTLINJE_FAKTOR = 1.3
KANDIDATER_PR_KAEDE = 3
CACHE_DAGE = 180      # en fundet butik tjekkes igen efter et halvt år
MANGLER_DAGE = 30     # en kæde der ikke blev fundet, prøves igen efter en måned
UA = "tilbudsagent (lokal desktop-app)"
BUTIKSTYPER = ("supermarket", "convenience", "chemist", "department_store", "variety_store", "general", "wholesale", "discount")


# ------------------------------------------------------------ netværk ---
def _post(url: str, data: dict, timeout: int = 70) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _get(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# --------------------------------------------------------------- geometri ---
def luftlinje_km(lat1, lng1, lat2, lng2) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lng2 - lng1) * p / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def pos_nøgle(lat: float, lng: float) -> str:
    return f"{lat:.3f},{lng:.3f}"  # ca. 100 m: samme sted giver samme nøgle


# ---------------------------------------------------------- OpenStreetMap ---
def _esc(t: str) -> str:
    return re.sub(r'([.^$*+?()\[\]{}|\\])', r"\\\1", t.replace('"', ""))


def overpass_forespoergsel(lat, lng, radius_m, butikker: dict) -> str:
    navne = sorted({n.lower() for b in butikker.values() for n in b["tjek_navn"]})
    rx = "^(" + "|".join(_esc(n) for n in navne) + ")( |-|$)"
    around = f"(around:{int(radius_m)},{lat},{lng})"
    typer = "^(" + "|".join(BUTIKSTYPER) + ")$"
    return (f'[out:json][timeout:50];(nwr["shop"~"{typer}"]["name"~"{rx}",i]{around};'
            f'nwr["shop"~"{typer}"]["brand"~"{rx}",i]{around};);out center tags 800;')


def _punkt(el: dict):
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    c = el.get("center") or {}
    return (c["lat"], c["lon"]) if "lat" in c and "lon" in c else (None, None)


def _adresse(tags: dict) -> str:
    gade = f"{tags.get('addr:street', '')} {tags.get('addr:housenumber', '')}".strip()
    by = tags.get("addr:city") or tags.get("addr:suburb") or tags.get("addr:place") or ""
    return ", ".join(x for x in (gade, by) if x)


def passer_til(tags: dict, tjek_navne: list[str]) -> bool:
    for k in ("name", "brand"):
        v = (tags.get(k) or "").strip().lower()
        for n in tjek_navne:
            n = n.lower()
            if v == n or v.startswith(n + " ") or v.startswith(n + "-"):
                return True
    return False


def kandidater(elementer: list[dict], butikker: dict, lat: float, lng: float) -> dict:
    """{butik_id: [(luftlinje_km, navn, adresse, lat, lng), ...]} de nærmeste først."""
    ud: dict[str, list] = {b: [] for b in butikker}
    set_: set = set()
    for el in elementer:
        la, lo = _punkt(el)
        tags = el.get("tags") or {}
        if la is None or tags.get("shop") not in BUTIKSTYPER:
            continue
        for bid, b in butikker.items():
            if passer_til(tags, b["tjek_navn"]):
                nøgle = (bid, round(la, 5), round(lo, 5))
                if nøgle in set_:
                    break
                set_.add(nøgle)
                ud[bid].append((luftlinje_km(lat, lng, la, lo), tags.get("name") or tags.get("brand") or b["navn"],
                                _adresse(tags), la, lo))
                break
    for bid in ud:
        ud[bid].sort(key=lambda x: x[0])
        ud[bid] = ud[bid][:KANDIDATER_PR_KAEDE]
    return ud


# ------------------------------------------------------------------ OSRM ---
def vejafstande_km(lat, lng, punkter: list[tuple[float, float]]) -> list[float | None]:
    """Kørselsafstand (km) fra (lat,lng) til hvert punkt, i ét kald."""
    if not punkter:
        return []
    koord = ";".join([f"{lng},{lat}"] + [f"{lo},{la}" for la, lo in punkter])
    d = _get(f"{OSRM}/table/v1/driving/{koord}?sources=0&annotations=distance")
    if d.get("code") != "Ok":
        raise RuntimeError(f"OSRM: {d.get('code')}")
    return [(m / 1000.0 if m is not None else None) for m in d["distances"][0][1:]]


# ----------------------------------------------------------------- cache ---
def hent_cache(con, lat, lng) -> dict:
    return {r["butik"]: dict(r) for r in con.execute("SELECT * FROM afstand WHERE pos=?", (pos_nøgle(lat, lng),))}


def _gammel(r: dict, idag: date) -> bool:
    try:
        alder = (idag - date.fromisoformat(r["hentet"])).days
    except Exception:
        return True
    return alder > (CACHE_DAGE if r["km"] is not None else MANGLER_DAGE)


def mangler_afstande(con, butikker: dict, lat: float, lng: float, idag: date | None = None) -> int:
    """Hvor mange kæder mangler en (frisk) afstand for dette sted?"""
    idag = idag or date.today()
    cache = hent_cache(con, lat, lng)
    return sum(1 for b in butikker if b not in cache or _gammel(cache[b], idag))


def _trin(fr, nr: int, tekst: str) -> None:
    if fr is not None:
        fr["trin"], fr["trin_tekst"] = nr, tekst


def overpass_med_reserve(foresp: str, fremdrift: dict | None = None, pause: float = 3.0) -> dict:
    """Overpass er en delt, gratis tjeneste, der ofte er overbelastet (502/504). Prøv flere spejle, og vent kort mellem forsøg."""
    fejl = []
    for i, url in enumerate(OVERPASS_SERVERE):
        for forsoeg in (1, 2):
            if fremdrift is not None and (i or forsoeg > 1):
                _trin(fremdrift, 1, f"Søger efter dine butikker i OpenStreetMap-data (server {i + 1} af {len(OVERPASS_SERVERE)})")
            try:
                return _post(url, {"data": foresp})
            except Exception as e:
                fejl.append(f"{url.split('/')[2]}: {e}")
                if forsoeg == 1:
                    time.sleep(pause)
    raise RuntimeError("Kunne ikke hente butikker fra OpenStreetMap. Tjenesten er sandsynligvis overbelastet lige nu; prøv igen om lidt. (" + "; ".join(fejl[-3:]) + ")")


def find_afstande(con, butikker: dict, lat: float, lng: float, max_km: float = 60.0, tving: bool = False,
                  idag: date | None = None, fremdrift: dict | None = None) -> dict:
    """Sørger for at der er en afstand til (nærmeste butik i) hver kæde. Slår kun op for det, der mangler."""
    idag = idag or date.today()
    cache = hent_cache(con, lat, lng)
    mangler = {b: v for b, v in butikker.items() if tving or b not in cache or _gammel(cache[b], idag)}
    if fremdrift is not None:
        fremdrift.update(i_alt=len(butikker), opslag=len(mangler))
    if mangler:
        _trin(fremdrift, 1, "Søger efter dine butikker i OpenStreetMap-data")
        svar = overpass_med_reserve(overpass_forespoergsel(lat, lng, max_km * 1000, mangler), fremdrift)
        kand = kandidater(svar.get("elements") or [], mangler, lat, lng)
        punkter = [(k[3], k[4]) for bid in kand for k in kand[bid]]
        if fremdrift is not None:
            fremdrift["kandidater"] = len(punkter)
        _trin(fremdrift, 2, f"Beregner kørselsafstand til {len(punkter)} mulige butikker")
        try:
            veje = vejafstande_km(lat, lng, punkter)
            metode = "vej"
        except Exception:
            veje, metode = [None] * len(punkter), "luftlinje"
        _trin(fremdrift, 3, "Vælger den nærmeste butik i hver kæde og gemmer")
        i = 0
        for bid, lst in kand.items():
            bedste = None
            for k in lst:
                vej = veje[i]
                i += 1
                km = vej if vej is not None else k[0] * LUFTLINJE_FAKTOR
                m = "vej" if vej is not None else "luftlinje"
                if bedste is None or km < bedste[0]:
                    bedste = (km, k, m)
            if bedste:
                km, k, m = bedste
                row = (pos_nøgle(lat, lng), bid, km, k[1], k[2], k[3], k[4], m, idag.isoformat())
            else:
                row = (pos_nøgle(lat, lng), bid, None, None, None, None, None, "ikke fundet", idag.isoformat())
            con.execute("INSERT OR REPLACE INTO afstand(pos,butik,km,navn,adresse,lat,lng,metode,hentet) "
                        "VALUES(?,?,?,?,?,?,?,?,?)", row)
        con.commit()
    else:
        _trin(fremdrift, 3, "Alt var allerede gemt for dette sted")
    return hent_cache(con, lat, lng)


# --------------------------------------------------------------- position ---
def aktiv_position(con, cfg) -> dict:
    r = con.execute("SELECT value FROM kv WHERE key='position_nu'").fetchone()
    if r:
        p = json.loads(r["value"])
        return dict(hjem=False, navn=p.get("navn") or "Anden position", lat=p["lat"], lng=p["lng"],
                    sunk=bool(p.get("sunk")))
    t = cfg["tjek"]
    return dict(hjem=True, navn=cfg.get("adresse") or "Hjem", lat=t.get("lat") or 0.0, lng=t.get("lng") or 0.0, sunk=True)


def zone_for(km: float, graenser) -> str:
    g = sorted(graenser or [10, 20])
    return "lokal" if km <= g[0] else "mellem" if km <= g[1] else "fjern"


def effektiv(con, cfg) -> dict:
    """Kopi af indstillingerne med afstande, zoner og søgested for den aktive position. Slår intet op på nettet."""
    pos = aktiv_position(con, cfg)
    c = copy.deepcopy(cfg)
    k = c["koersel"]
    har = bool(pos["lat"] or pos["lng"])
    if har:
        c["tjek"]["lat"], c["tjek"]["lng"] = pos["lat"], pos["lng"]
    if har and (not pos["hjem"] or k.get("auto_afstand")):
        rows = hent_cache(con, pos["lat"], pos["lng"])
        for bid in list(c["butikker"]):
            b, r = c["butikker"][bid], rows.get(bid)
            if pos["hjem"] and b.get("fast_afstand"):
                continue
            if r and r["km"] is not None:
                b["afstand_km"] = round(r["km"], 1)
                b["zone"] = zone_for(r["km"], k.get("zone_graenser"))
                b["_fundet"] = dict(navn=r["navn"], adresse=r["adresse"], metode=r["metode"])
            elif not pos["hjem"]:
                del c["butikker"][bid]  # ikke fundet i nærheden af den position
        k["sunk_zoner"] = [z for z in k.get("sunk_zoner", [])] if pos["hjem"] else (["lokal"] if pos["sunk"] else [])
    elif not pos["hjem"] and not pos["sunk"]:
        k["sunk_zoner"] = []
    c["_position"] = pos
    return c


def gem_position(con, navn: str, lat: float, lng: float, sunk: bool) -> None:
    con.execute("INSERT OR REPLACE INTO kv(key,value) VALUES('position_nu',?)",
                (json.dumps(dict(navn=navn, lat=lat, lng=lng, sunk=sunk), ensure_ascii=False),))
    r = con.execute("SELECT value FROM kv WHERE key='positioner_seneste'").fetchone()
    liste = [p for p in (json.loads(r["value"]) if r else []) if pos_nøgle(p["lat"], p["lng"]) != pos_nøgle(lat, lng)]
    liste.insert(0, dict(navn=navn, lat=lat, lng=lng))
    con.execute("INSERT OR REPLACE INTO kv(key,value) VALUES('positioner_seneste',?)",
                (json.dumps(liste[:6], ensure_ascii=False),))
    con.commit()


def ryd_position(con) -> None:
    con.execute("DELETE FROM kv WHERE key='position_nu'")
    con.commit()
