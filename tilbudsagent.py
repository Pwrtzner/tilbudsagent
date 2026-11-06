#!/usr/bin/env python3
"""Tilbudsagent – skelet.

Henter ugens tilbud fra Tjek (eTilbudsavis), gemmer dem i SQLite, estimerer normal-/bundpris
pr. vare og anbefaler hvilke butikker der er værd at køre til, når kørsel (kr/km) trækkes fra.

Kommandoer:
  app                        start appen (dashboard, varer, indstillinger) på http://localhost:8765
  hent                      hent tilbud for alle varer i varer.csv
  rapport                    lav rapport (stdout + rapport-ÅÅÅÅ-MM-DD.md)
  uge                        hent + rapport (til cron / planlagt opgave)
  manuel BUTIK VARE PRIS MÆNGDE [--foer P] [--til ÅÅÅÅ-MM-DD]
                             indtast et tilbud manuelt (fx ABC Lavpris); MÆNGDE i vareens enhed
  demo                       fyld en demo-database med syntetiske data og lav rapport
Kun standardbibliotek (Python 3.11+).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import os
import random
import re
import sqlite3
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # Python 3.10: pip install tomli
    import tomli as tomllib

VERSION = "0.5.0"
FROSSET = getattr(sys, "frozen", False)  # True når appen er pakket som .exe
# RES: hvor startværdier og app.html ligger. DATA: hvor brugerens database og log gemmes.
RES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
HERE = RES  # bagudkompatibelt navn


def data_mappe() -> Path:
    if os.environ.get("TILBUDSAGENT_DATA"):
        d = Path(os.environ["TILBUDSAGENT_DATA"])
    elif FROSSET:  # pakket app: fast datamappe, adskilt fra programfilen
        base = os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
        d = Path(base) / "Tilbudsagent"
    else:  # kørt som script: data ligger ved siden af scriptet, som før
        d = Path(__file__).resolve().parent
    d.mkdir(parents=True, exist_ok=True)
    return d


DATA = data_mappe()


def sikr_output() -> None:
    """Uden konsol (pakket med --noconsole) er stdout/stderr None. Send til logfil, så print ikke fejler."""
    if sys.stdout is None or sys.stderr is None:
        f = open(DATA / "tilbudsagent.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f

# ---------------------------------------------------------------- enheder ---
UNIT = {  # symbol -> (baseenhed, faktor til baseenhed)
    "mg": ("kg", 1e-6), "g": ("kg", 0.001), "kg": ("kg", 1.0),
    "ml": ("l", 0.001), "cl": ("l", 0.01), "dl": ("l", 0.1), "l": ("l", 1.0), "ltr": ("l", 1.0),
    "stk": ("stk", 1.0), "pcs": ("stk", 1.0), "rl": ("stk", 1.0), "rulle": ("stk", 1.0), "ruller": ("stk", 1.0),
}
RE_MAENGDE = re.compile(
    r"(?:(\d+)\s*[x×]\s*)?(\d+(?:[.,]\d+)?)\s*(kg|g|ml|cl|dl|ltr|l|stk|rl|ruller|rulle)\b"
)
RE_KOEB_N = re.compile(r"\b(\d+)\s*(?:stk\.?\s*)?for\s+(\d+(?:[.,]\d+)?)")
RE_BETINGELSE = re.compile(r"kun med|\bapp\b|medlem|kundekort|coop app|plus-?kunde", re.I)
UGEDAGE = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
MAANEDER = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august",
            "september", "oktober", "november", "december"]


def kr(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def tal(s):
    s = (s or "").strip().replace(",", ".")
    return float(s) if s else None


# -------------------------------------------------------------- indlæsning ---
def load_config(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_varer(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        linjer = (l for l in f if l.strip() and not l.lstrip().startswith("#"))
        varer = []
        for r in csv.DictReader(linjer, delimiter=";"):
            varer.append({
                "id": r["id"].strip(), "navn": r["navn"].strip(), "enhed": r["enhed"].strip().lower(),
                "soeg": [s.strip().lower() for s in r["soegeord"].split("|") if s.strip()],
                "udeluk": [s.strip().lower() for s in (r["udeluk"] or "").split("|") if s.strip()],
                "normal": tal(r["normalpris"]), "maal": tal(r["maalpris"]),
                "koeb": tal(r["koebsmaengde"]) or 1.0, "lager": tal(r["maks_lager"]),
            })
    return varer


def connect(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS obs(
        id INTEGER PRIMARY KEY, hentet TEXT, vare_id TEXT, butik TEXT, overskrift TEXT,
        pris REAL, foer_pris REAL, enhedspris REAL, enhed TEXT,
        gyldig_fra TEXT, gyldig_til TEXT, betingelse TEXT, kilde TEXT, tjek_id TEXT NOT NULL,
        UNIQUE(vare_id, butik, tjek_id))""")
    # Alle tilbud vi nogensinde har set, uændret. obs (dine varer) kan altid genopbygges herfra.
    con.execute("""CREATE TABLE IF NOT EXISTS raa(
        tjek_id TEXT PRIMARY KEY, forhandler TEXT, overskrift TEXT, beskrivelse TEXT, pris REAL, foer_pris REAL,
        gyldig_fra TEXT, gyldig_til TEXT, foerst_set TEXT, sidst_set TEXT, soeg TEXT, json TEXT NOT NULL)""")
    con.execute("CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS vare(id TEXT PRIMARY KEY, pos INTEGER, json TEXT NOT NULL)")
    con.commit()
    return con


# Indstillinger og varer ligger i databasen (kan redigeres i appen).
# config.toml og varer.csv bruges kun som startværdier første gang.
def save_cfg(con, cfg: dict) -> None:
    con.execute("INSERT INTO kv(key,value) VALUES('cfg',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(cfg, ensure_ascii=False),))
    con.commit()


def get_cfg(con, seed: Path) -> dict:
    r = con.execute("SELECT value FROM kv WHERE key='cfg'").fetchone()
    if r:
        cfg = json.loads(r["value"])
        cfg["regler"].setdefault("max_rabat", 0.6)
        cfg.setdefault("app", {}).setdefault("auto_hent", True)
        return cfg
    if not seed.exists():
        sys.exit(f"Mangler {seed} (bruges som startværdier første gang).")
    cfg = load_config(seed)
    cfg.setdefault("adresse", "")
    cfg["regler"].setdefault("max_rabat", 0.6)
    cfg.setdefault("app", {}).setdefault("auto_hent", True)
    save_cfg(con, cfg)
    return cfg


def save_vare(con, v: dict) -> None:
    pos = con.execute("SELECT pos FROM vare WHERE id=?", (v["id"],)).fetchone()
    if pos is None:
        pos = (con.execute("SELECT COALESCE(MAX(pos),-1)+1 FROM vare").fetchone()[0],)
    con.execute("INSERT INTO vare(id,pos,json) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET json=excluded.json",
                (v["id"], pos[0], json.dumps(v, ensure_ascii=False)))
    con.commit()


def get_varer(con, seed: Path) -> list[dict]:
    if not con.execute("SELECT 1 FROM kv WHERE key='varer_seedet'").fetchone():
        if not con.execute("SELECT 1 FROM vare LIMIT 1").fetchone() and seed.exists():
            for v in load_varer(seed):
                save_vare(con, v)
        con.execute("INSERT OR REPLACE INTO kv(key,value) VALUES('varer_seedet','1')")
        con.commit()
    def med_standard(v):
        v.setdefault("type", "generisk")
        v.setdefault("maerker", [])
        v.setdefault("udeluk_maerker", [])
        return v
    return [med_standard(json.loads(r["json"])) for r in con.execute("SELECT json FROM vare ORDER BY pos, rowid")]


def indsaet(con, **k) -> bool:
    felter = ["hentet", "vare_id", "butik", "overskrift", "pris", "foer_pris", "enhedspris", "enhed",
              "gyldig_fra", "gyldig_til", "betingelse", "kilde", "tjek_id"]
    cur = con.execute(
        f"INSERT OR IGNORE INTO obs({','.join(felter)}) VALUES({','.join('?' * len(felter))})",
        [k.get(f) for f in felter])
    return cur.rowcount > 0


# ------------------------------------------------------- tilbud -> data ---
def _mid(x):
    if isinstance(x, dict):
        v = [y for y in (x.get("from"), x.get("to")) if isinstance(y, (int, float))]
        return sum(v) / len(v) if v else None
    return float(x) if isinstance(x, (int, float)) else None


def parse_maengde(o: dict):
    """Returnerer (mængde i baseenhed, baseenhed) eller None."""
    q = o.get("quantity") or {}
    sym = ((q.get("unit") or {}).get("symbol") or "").lower()
    if sym in UNIT:
        base, f = UNIT[sym]
        size, pieces = _mid(q.get("size")), _mid(q.get("pieces"))
        if base == "stk":
            if size or pieces:  # antal stk må aldrig gættes (fx ruller i en pakke toiletpapir)
                return (size or 1.0) * (pieces or 1.0), base
        elif size:
            return size * f * (pieces or 1.0), base
    tekst = f"{o.get('heading', '')} {o.get('description', '')}".lower()
    m = RE_MAENGDE.search(tekst)
    if m:
        antal = int(m.group(1)) if m.group(1) else 1
        base, f = UNIT[m.group(3)]
        return antal * float(m.group(2).replace(",", ".")) * f, base
    return None


def soegeord(v: dict) -> list[str]:
    """Hvad der søges på hos Tjek: produkterne hvis varen er 'specifik', ellers søgeordene."""
    return (v.get("maerker") if v.get("type") == "specifik" else None) or v["soeg"]


def vare_matcher(v: dict, overskrift: str) -> bool:
    """Matcher kun på tilbuddets overskrift (beskrivelser nævner for mange ord).

    generisk: alle ord i ét søgeord skal være med, og ingen ignorerede ord/mærker.
    specifik: alle ord i ét af mærkerne/produkterne skal være med (fx 'heinz ketchup').
    """
    t = overskrift.lower()

    def har(w):
        return re.search(rf"\b{re.escape(w)}", t) is not None
    if any(har(w) for w in list(v["udeluk"]) + list(v.get("udeluk_maerker") or [])):
        return False
    krav = v.get("maerker") if v.get("type") == "specifik" else v["soeg"]
    return any(all(har(w) for w in alt.split()) for alt in (krav or []))


def ryd_obs(con, v: dict) -> int:
    """Fjerner gemte Tjek-priser for varen, der ikke længere matcher dens regler."""
    ids = [r["id"] for r in con.execute("SELECT id, overskrift FROM obs WHERE vare_id=? AND kilde='tjek'", (v["id"],))
           if not vare_matcher(v, r["overskrift"] or "")]
    con.executemany("DELETE FROM obs WHERE id=?", [(i,) for i in ids])
    con.commit()
    return len(ids)


def butik_fra_dealer(cfg: dict, navn: str):
    n = navn.strip().lower()
    for key, b in cfg["butikker"].items():
        if n in [a.lower() for a in b.get("tjek_navn", [])]:
            return key
    return None


def betingelse(tekst: str) -> str:
    dele = []
    m = RE_KOEB_N.search(tekst)
    if m:
        dele.append(f"køb {m.group(1)}")
    if RE_BETINGELSE.search(tekst):
        dele.append("kun med app/medlemskab?")
    return ", ".join(dele)


# ------------------------------------------------------------------ hent ---
def tjek_hent(cfg: dict, query: str):
    t = cfg["tjek"]
    p = {"query": query, "limit": t.get("limit", 100)}
    if t.get("lat") and t.get("lng"):
        p.update(r_lat=t["lat"], r_lng=t["lng"], r_radius=t.get("radius_m", 30000))
    url = t["url"] + "?" + urllib.parse.urlencode(p)
    h = {"User-Agent": "tilbudsagent/0.1", "Accept": "application/json"}
    if t.get("api_key"):
        h["X-Api-Key"] = t["api_key"]  # tilpas efter Tjeks dokumentation, hvis en nøgle kræves
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
        return json.load(r)


def raa_gem(con, o: dict, soeg: str, dato: str) -> bool:
    """Gem tilbuddet uændret (første gang vi ser det) eller opdater 'sidst set'. True = nyt tilbud."""
    tid = o.get("id")
    if not tid:
        return False
    tid = str(tid)
    pr = o.get("pricing") or {}
    fandtes = con.execute("SELECT 1 FROM raa WHERE tjek_id=?", (tid,)).fetchone()
    con.execute(
        """INSERT INTO raa(tjek_id, forhandler, overskrift, beskrivelse, pris, foer_pris, gyldig_fra, gyldig_til,
                           foerst_set, sidst_set, soeg, json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(tjek_id) DO UPDATE SET sidst_set=MAX(raa.sidst_set, excluded.sidst_set),
             soeg=CASE WHEN instr(',' || raa.soeg || ',', ',' || excluded.soeg || ',') > 0
                       THEN raa.soeg ELSE raa.soeg || ',' || excluded.soeg END""",
        (tid, (o.get("dealer") or {}).get("name", ""), (o.get("heading") or "").strip(), o.get("description"),
         pr.get("price"), pr.get("pre_price"), (o.get("run_from") or "")[:10] or None,
         (o.get("run_till") or "")[:10] or None, dato, dato, soeg, json.dumps(o, ensure_ascii=False)))
    return not fandtes


def obs_fra_tilbud(cfg, v, o, hentet):
    """Et rå tilbud + en vare -> felter til obs, eller None hvis det ikke passer."""
    butik = butik_fra_dealer(cfg, (o.get("dealer") or {}).get("name", ""))
    if not butik or not vare_matcher(v, o.get("heading") or ""):
        return None
    pr = o.get("pricing") or {}
    pris = pr.get("price")
    if pris is None:
        return None
    m = parse_maengde(o)
    ep = pris / m[0] if m and m[1] == v["enhed"] and m[0] > 0 else None
    return dict(
        hentet=hentet, vare_id=v["id"], butik=butik, overskrift=(o.get("heading") or "").strip(), pris=pris,
        foer_pris=pr.get("pre_price"), enhedspris=ep, enhed=v["enhed"],
        gyldig_fra=(o.get("run_from") or "")[:10] or None, gyldig_til=(o.get("run_till") or "")[:10] or None,
        betingelse=betingelse(f"{o.get('heading', '')} {o.get('description', '')}"), kilde="tjek",
        tjek_id=str(o.get("id")))


def genopbyg(con, cfg, varer) -> int:
    """Genskab observationer for varerne ud fra alle gemte rå tilbud (efter rettede regler, nye varer eller butikker)."""
    n = 0
    for r in con.execute("SELECT json, foerst_set FROM raa").fetchall():
        o = json.loads(r["json"])
        for v in varer:
            k = obs_fra_tilbud(cfg, v, o, r["foerst_set"])
            if k:
                n += indsaet(con, **k)
    con.commit()
    return n


def hent(cfg, varer, con, idag: date, fremdrift: dict | None = None) -> dict:
    ukendte, nye, fejl, fejltekster, raa_nye = Counter(), 0, 0, [], 0
    fr = fremdrift if fremdrift is not None else {}
    fr.update(gjort=0, i_alt=sum(len(soegeord(v)) for v in varer), nye=0, nu="")
    for v in varer:
        for alt in soegeord(v):
            fr["gjort"] += 1
            fr["nu"] = alt
            try:
                tilbud = tjek_hent(cfg, alt)
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                print(f"  ! {v['id']} '{alt}': {e}", file=sys.stderr)
                fejl += 1
                fejltekster.append(f"{alt}: {e}")
                continue
            time.sleep(cfg["tjek"].get("pause_sek", 1.5))
            if not isinstance(tilbud, list):
                print(f"  ! {v['id']} '{alt}': uventet svarformat", file=sys.stderr)
                fejl += 1
                continue
            for o in tilbud:
                if raa_gem(con, o, alt, idag.isoformat()):
                    raa_nye += 1
                dn = (o.get("dealer") or {}).get("name", "")
                if not butik_fra_dealer(cfg, dn):
                    ukendte[dn] += 1
                    continue
                k = obs_fra_tilbud(cfg, v, o, idag.isoformat())
                if k:
                    nye += indsaet(con, **k)
                    fr["nye"] = nye
    con.commit()
    print(f"Hentet: {raa_nye} nye tilbud gemt, {nye} nye observationer ({fejl} fejlede kald).")
    if ukendte:
        top = ", ".join(f"{n or '?'} ({c})" for n, c in ukendte.most_common(8))
        print(f"Forhandlere der ikke matchede en butik (tjek 'Tjek-navn' under butikker): {top}")
    return dict(nye=nye, raa_nye=raa_nye, fejl=fejl, kald=fr["i_alt"], fejltekster=fejltekster[:3], ukendte=dict(ukendte.most_common(8)))


def manuel(cfg, varer, con, a, idag: date) -> None:
    if a.butik not in cfg["butikker"]:
        raise ValueError(f"Ukendt butik '{a.butik}'. Valg: {', '.join(cfg['butikker'])}")
    v = next((x for x in varer if x["id"] == a.vare), None)
    if not v:
        raise ValueError(f"Ukendt vare '{a.vare}'. Valg: {', '.join(x['id'] for x in varer)}")
    if not (a.pris and a.pris > 0 and a.maengde and a.maengde > 0):
        raise ValueError("Pris og mængde skal være større end 0.")
    til = a.til or (idag + timedelta(days=6 - idag.weekday())).isoformat()
    tid = "manuel-" + hashlib.sha1(f"{a.butik}{a.vare}{a.pris}{a.maengde}{idag}".encode()).hexdigest()[:10]
    indsaet(con, hentet=idag.isoformat(), vare_id=v["id"], butik=a.butik, overskrift="(manuelt indtastet)",
            pris=a.pris, foer_pris=a.foer, enhedspris=a.pris / a.maengde, enhed=v["enhed"],
            gyldig_fra=idag.isoformat(), gyldig_til=til, betingelse="", kilde="manuel", tjek_id=tid)
    con.commit()
    print(f"Gemt: {a.butik} / {v['navn']}: {kr(a.pris / a.maengde)} kr/{v['enhed']} (til {til}).")


# --------------------------------------------------------------- analyse ---
def _cutoff(idag, dage):
    return (idag - timedelta(days=dage)).isoformat()


def normalpris(con, v, dage, idag):
    if v["normal"]:
        return v["normal"], "angivet"
    rows = con.execute("SELECT enhedspris ep, foer_pris fp, pris p FROM obs WHERE vare_id=? "
                       "AND enhedspris IS NOT NULL AND hentet>=?", (v["id"], _cutoff(idag, dage))).fetchall()
    foer = [r["ep"] * r["fp"] / r["p"] for r in rows if r["fp"] and r["p"]]
    if foer:
        return statistics.median(foer), "førpris i tilbud"
    if len(rows) >= 4:
        return statistics.median(r["ep"] for r in rows), "estimat: typisk tilbudspris"
    return None, "ukendt"


def bundpris(con, v, dage, idag):
    r = con.execute("SELECT MIN(enhedspris) m, COUNT(DISTINCT tjek_id) n FROM obs WHERE vare_id=? "
                    "AND enhedspris IS NOT NULL AND hentet>=?", (v["id"], _cutoff(idag, dage))).fetchone()
    return r["m"], r["n"]


def aktive(con, v, idag):
    """Aktive/kommende tilbud: billigste pr. butik (med enhedspris) + alle uden enhedspris."""
    i, om_uge = idag.isoformat(), (idag + timedelta(days=7)).isoformat()
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM obs WHERE vare_id=? AND (gyldig_til IS NULL OR gyldig_til>=?) "
        "AND (gyldig_fra IS NULL OR gyldig_fra<=?)", (v["id"], i, om_uge))]
    bedst, uafklaret = {}, []
    for r in rows:
        if r["enhedspris"] is None:
            uafklaret.append(r)
        elif r["butik"] not in bedst or r["enhedspris"] < bedst[r["butik"]]["enhedspris"]:
            bedst[r["butik"]] = r
    return list(bedst.values()), uafklaret


def byg_kandidater(cfg, varer, con, idag):
    reg = cfg["regler"]
    kands, uafklaret, info = {}, [], []
    for v in varer:
        norm, kilde = normalpris(con, v, reg["historik_dage"], idag)
        bund, n = bundpris(con, v, reg["historik_dage"], idag)
        info.append(dict(vare=v, norm=norm, kilde=kilde, bund=bund, n=n))
        ref = norm or v["maal"]
        akt, ukl = aktive(con, v, idag)
        uafklaret += [dict(o, vare=v) for o in ukl]
        for o in akt:
            if not ref or o["butik"] not in cfg["butikker"]:
                continue
            ep = o["enhedspris"]
            rabat = 1 - ep / ref
            if rabat > reg.get("max_rabat", 0.6):
                continue  # urealistisk høj rabat → ikke brugt (typisk forkert pakkestørrelse)
            under_maal = bool(v["maal"]) and ep <= v["maal"]
            if rabat < reg["min_rabat"] and not under_maal:
                continue
            neer_bund = bund is not None and n >= 4 and ep <= bund * 1.05
            lager = bool(v["lager"]) and neer_bund and rabat >= reg["lager_rabat"]
            maengde = v["lager"] if lager else v["koeb"]
            kands.setdefault(v["id"], []).append(dict(
                vare=v, butik=o["butik"], tekst=o["overskrift"], pris=o["pris"], ep=ep, ref=ref, rabat=rabat,
                maengde=maengde, besparelse=max(0.0, ref - ep) * maengde, lager=lager,
                betingelse=o["betingelse"], fra=o["gyldig_fra"], til=o["gyldig_til"], kilde=o["kilde"]))
    return kands, uafklaret, info


def turkost_detaljer(cfg, valgte):
    """Returnerer (linjer pr. zone, stop-omkostning, margin)."""
    k, zoner = cfg["koersel"], {}
    for s in valgte:
        b = cfg["butikker"][s]
        zoner[b["zone"]] = max(zoner.get(b["zone"], 0.0), b["afstand_km"])
    linjer = []
    for z, km in sorted(zoner.items()):
        sunk = z in k["sunk_zoner"]
        linjer.append(dict(zone=z, km=km, km_tur_retur=2 * km, sunk=sunk,
                           kr=0.0 if sunk else 2 * km * k["kr_pr_km"]))
    margin = k.get("margin_pr_tur_kr", 0.0) * sum(1 for l in linjer if not l["sunk"])
    return linjer, k["stop_kr"] * len(valgte), margin


def turkost(cfg, valgte):
    linjer, stop, margin = turkost_detaljer(cfg, valgte)
    return sum(l["kr"] for l in linjer) + stop + margin, {l["zone"]: l["km"] for l in linjer}


def kurv(kands, valgte):
    valg, sav = {}, 0.0
    for vid, cs in kands.items():
        best = max((c for c in cs if c["butik"] in valgte), key=lambda c: c["besparelse"], default=None)
        if best and best["besparelse"] > 0:
            valg.setdefault(best["butik"], []).append(best)
            sav += best["besparelse"]
    return valg, sav


def bedste_tur(cfg, kands):
    butikker = sorted({c["butik"] for cs in kands.values() for c in cs})
    bedst = dict(net=0.0, valgte=(), sav=0.0, cost=0.0)
    for r in range(1, len(butikker) + 1):
        for S in itertools.combinations(butikker, r):
            _, sav = kurv(kands, S)
            cost, _ = turkost(cfg, S)
            if sav - cost > bedst["net"] + 1e-9:
                bedst = dict(net=sav - cost, valgte=S, sav=sav, cost=cost)
    valg, _ = kurv(kands, bedst["valgte"])
    bedst["valgte"] = tuple(s for s in bedst["valgte"] if s in valg)  # drop butikker uden varer
    if bedst["valgte"]:
        bedst["cost"], _ = turkost(cfg, bedst["valgte"])
        valg, bedst["sav"] = kurv(kands, bedst["valgte"])
        bedst["net"] = bedst["sav"] - bedst["cost"]
    bedst["valg"] = valg
    return bedst


def afviste_zoner(cfg, kands, bedst):
    k, ud = cfg["koersel"], []
    zoner = {b["zone"] for b in cfg["butikker"].values()} - set(k["sunk_zoner"])
    valgte_zoner = {cfg["butikker"][s]["zone"] for s in bedst["valgte"]}
    for z in sorted(zoner - valgte_zoner):
        med = [s for s, b in cfg["butikker"].items() if b["zone"] == z and any(
            c["butik"] == s for cs in kands.values() for c in cs)]
        if not med:
            continue
        S = tuple(set(bedst["valgte"]) | set(med))
        _, sav = kurv(kands, S)
        cost, _ = turkost(cfg, S)
        ud.append(dict(zone=z, butikker=med, ekstra_sav=sav - bedst["sav"], ekstra_cost=cost - bedst["cost"]))
    return ud


# --------------------------------------------------------------- rapport ---
def rapport(cfg, varer, con, idag: date) -> str:
    kands, uafklaret, info = byg_kandidater(cfg, varer, con, idag)
    bedst = bedste_tur(cfg, kands)
    B = cfg["butikker"]
    demo = con.execute("SELECT 1 FROM obs WHERE kilde='demo' LIMIT 1").fetchone()
    L = [f"# Tilbudsrapport – {UGEDAGE[idag.weekday()]} {idag.day}. {MAANEDER[idag.month - 1]} {idag.year}", ""]
    if demo:
        L += ["> **DEMO-DATA** – syntetiske priser, kun til at teste logikken.", ""]

    L += ["## Anbefalet indkøbstur", ""]
    if not bedst["valgte"]:
        L += ["Ingen tur er værd at køre efter denne uge (ingen tilbud klarer rabatgrænsen efter kørsel).", ""]
    else:
        L += [f"**Besparelse {kr(bedst['sav'])} kr – kørsel/stop {kr(bedst['cost'])} kr – "
              f"netto {kr(bedst['net'])} kr**", ""]
        for s in sorted(bedst["valgte"], key=lambda s: B[s]["afstand_km"]):
            L += [f"### {B[s]['navn']} ({str(B[s]['afstand_km']).replace('.', ',')} km, zone {B[s]['zone']})", "",
                  "| Vare | Tilbud | Pris | Enhedspris | Rabat | Køb | Besparelse | Gælder |",
                  "|---|---|---|---|---|---|---|---|"]
            for c in sorted(bedst["valg"][s], key=lambda c: -c["besparelse"]):
                v = c["vare"]
                note = (" ⚠ " + c["betingelse"]) if c["betingelse"] else ""
                lager = " (lagerkøb)" if c["lager"] else ""
                L.append(f"| {v['navn']} | {c['tekst'][:40]}{note} | {kr(c['pris'])} | {kr(c['ep'])} kr/{v['enhed']} | "
                         f"{c['rabat'] * 100:.0f} % | {str(round(c['maengde'], 2)).replace('.', ',')} {v['enhed']}{lager} | "
                         f"{kr(c['besparelse'])} kr | {c['fra'] or '?'} → {c['til'] or '?'} |")
            L.append("")

    af = afviste_zoner(cfg, kands, bedst)
    if af:
        L += ["## Ikke værd at køre efter (endnu)", "",
              "| Zone | Butikker | Ekstra besparelse | Ekstra kørsel | Mangler for at løbe rundt |", "|---|---|---|---|---|"]
        for a in af:
            gab = a["ekstra_cost"] - a["ekstra_sav"]
            L.append(f"| {a['zone']} | {', '.join(B[s]['navn'] for s in a['butikker'])} | {kr(a['ekstra_sav'])} kr | "
                     f"{kr(a['ekstra_cost'])} kr | {kr(gab) + ' kr' if gab > 0 else 'løber rundt'} |")
        L.append("")

    lager = [c for cs in kands.values() for c in cs if c["lager"]]
    if lager:
        L += ["## Lagerkøb – nær bundpris", ""]
        for c in sorted(lager, key=lambda c: -c["besparelse"]):
            L.append(f"- {c['vare']['navn']} hos {B[c['butik']]['navn']}: {kr(c['ep'])} kr/{c['vare']['enhed']} "
                     f"({c['rabat'] * 100:.0f} % under normalpris), op til {c['vare']['lager']} {c['vare']['enhed']}")
        L.append("")

    if uafklaret:
        L += ["## Tilbud hvor enhedsprisen ikke kunne aflæses (tjek manuelt)", ""]
        for o in uafklaret[:8]:
            L.append(f"- {B[o['butik']]['navn']}: {o['overskrift'][:60]} – {kr(o['pris'])} kr ({o['vare']['navn']})")
        L.append("")

    L += ["## Datagrundlag", "", "| Vare | Normalpris | Kilde | Bundpris | Observationer |", "|---|---|---|---|---|"]
    for i in info:
        v = i["vare"]
        L.append(f"| {v['navn']} | {kr(i['norm']) + ' kr/' + v['enhed'] if i['norm'] else '–'} | {i['kilde']} | "
                 f"{kr(i['bund']) if i['bund'] else '–'} | {i['n']} |")
    mangler = [i["vare"]["navn"] for i in info if i["kilde"].startswith(("estimat", "ukendt"))]
    if mangler:
        L += ["", "Normalpris er estimeret eller ukendt for: " + ", ".join(mangler) +
              ". Tilbudsaviser viser kun kampagnepriser, så estimatet undervurderer normalprisen – "
              "udfyld `normalpris` i varer.csv for skarpere rabatter."]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ demo ---
def demo(cfg, varer, con, idag: date) -> None:
    rnd = random.Random(13)
    basis = {"kg": 60.0, "l": 30.0, "stk": 4.0}
    ugestart = idag - timedelta(days=idag.weekday())
    for v in varer:
        norm = v["normal"] or basis[v["enhed"]] * rnd.uniform(0.6, 1.6)
        for uge in range(10, -1, -1):
            fra = ugestart - timedelta(weeks=uge)
            for s, b in cfg["butikker"].items():
                if rnd.random() > (0.30 if b["zone"] == "lokal" else 0.22):
                    continue
                rabat = rnd.uniform(0.10, 0.45) + (0.08 if b["zone"] == "fjern" else 0)
                ep = norm * (1 - rabat)
                m = 1.0 if v["enhed"] != "stk" else 6.0
                indsaet(con, hentet=fra.isoformat(), vare_id=v["id"], butik=s, overskrift=f"{v['navn']} demo",
                        pris=round(ep * m, 2), foer_pris=None, enhedspris=ep, enhed=v["enhed"],
                        gyldig_fra=fra.isoformat(), gyldig_til=(fra + timedelta(days=6)).isoformat(),
                        betingelse="", kilde="demo", tjek_id=f"demo-{v['id']}-{s}-{uge}")
    con.commit()


# ------------------------------------------------------------------- cli ---
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kommando", nargs="?", default="app", choices=["app", "hent", "rapport", "uge", "manuel", "demo"])
    ap.add_argument("butik", nargs="?")
    ap.add_argument("vare", nargs="?")
    ap.add_argument("pris", nargs="?", type=float)
    ap.add_argument("maengde", nargs="?", type=float)
    ap.add_argument("--foer", type=float)
    ap.add_argument("--til")
    ap.add_argument("--config", type=Path, default=RES / "config.toml")
    ap.add_argument("--varer", type=Path, default=RES / "varer.csv")
    ap.add_argument("--db", type=Path, default=DATA / "priser.db")
    ap.add_argument("--dato", help="ÅÅÅÅ-MM-DD (til test)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--ingen-browser", action="store_true")
    ap.add_argument("--version", action="version", version=f"Tilbudsagent {VERSION}")
    sikr_output()
    a = ap.parse_args()

    if a.kommando == "app":
        import webapp
        webapp.koer(a)
        return
    idag = datetime.strptime(a.dato, "%Y-%m-%d").date() if a.dato else date.today()
    if a.kommando == "demo":
        a.db = DATA / "demo.db"
    con = connect(a.db)
    cfg, varer = get_cfg(con, a.config), get_varer(con, a.varer)
    if a.kommando == "demo":
        demo(cfg, varer, con, idag)
    if a.kommando in ("hent", "uge"):
        hent(cfg, varer, con, idag)
    if a.kommando == "manuel":
        if None in (a.butik, a.vare, a.pris, a.maengde):
            sys.exit("Brug: manuel BUTIK VARE PRIS MÆNGDE [--foer P] [--til ÅÅÅÅ-MM-DD]")
        try:
            manuel(cfg, varer, con, a, idag)
        except ValueError as e:
            sys.exit(str(e))
    if a.kommando in ("rapport", "uge", "demo"):
        tekst = rapport(cfg, varer, con, idag)
        print(tekst)
        (a.db.parent / f"rapport-{idag.isoformat()}.md").write_text(tekst, encoding="utf-8")


if __name__ == "__main__":
    main()
