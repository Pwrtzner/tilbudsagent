"""Lokal webapp til tilbudsagenten (kun standardbibliotek).

Starter en server på 127.0.0.1 (kun din egen computer) og serverer app.html + et lille JSON-API.
"""
from __future__ import annotations

import json
import platform
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import steder as geo
import tilbudsagent as ta

HERE = ta.RES  # app.html, config.toml og varer.csv ligger her (i .exe: i den udpakkede pakke)
APP = {"db": ta.DATA / "priser.db", "config": HERE / "config.toml", "varer": HERE / "varer.csv",
       "hent": {"koerer": False}, "server": None}
LOCK = threading.Lock()


# ------------------------------------------------------------ hjælpere ---
def slug(tekst: str) -> str:
    t = tekst.lower().strip()
    for a, b in (("æ", "ae"), ("ø", "oe"), ("å", "aa"), ("é", "e")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "vare"


def liste(x) -> list[str]:
    if isinstance(x, str):
        x = re.split(r"[|,\n]", x)
    return [s.strip().lower() for s in (x or []) if str(s).strip()]


def talfelt(x, lo, hi, navn, valgfri=False):
    if x in (None, ""):
        if valgfri:
            return None
        raise ValueError(f"{navn} mangler.")
    try:
        v = float(str(x).replace(",", "."))
    except ValueError:
        raise ValueError(f"{navn} skal være et tal.")
    if not (lo <= v <= hi):
        raise ValueError(f"{navn} skal være mellem {lo} og {hi}.")
    return v


# ------------------------------------------------------------- dashboard ---
def dashboard(cfg, varer, con, idag: date) -> dict:
    B = cfg["butikker"]
    kands, uafklaret, info = ta.byg_kandidater(cfg, varer, con, idag)
    bedst = ta.bedste_tur(cfg, kands)
    afviste = ta.afviste_zoner(cfg, kands, bedst)
    i_tur = {(c["vare"]["id"], s) for s, cs in bedst["valg"].items() for c in cs}

    def linje(c):
        return dict(vare_id=c["vare"]["id"], vare=c["vare"]["navn"], enhed=c["vare"]["enhed"], tekst=c["tekst"],
                    pris=c["pris"], ep=c["ep"], ref=c["ref"], rabat=c["rabat"], maengde=c["maengde"],
                    besparelse=c["besparelse"], lager=c["lager"], betingelse=c["betingelse"],
                    fra=c["fra"], til=c["til"])

    tur_butikker = [dict(id=s, navn=B[s]["navn"], km=B[s]["afstand_km"], zone=B[s]["zone"],
                         linjer=[linje(c) for c in sorted(bedst["valg"][s], key=lambda c: -c["besparelse"])])
                    for s in sorted(bedst["valgte"], key=lambda s: B[s]["afstand_km"])]
    kl, stop, margin = ta.turkost_detaljer(cfg, bedst["valgte"]) if bedst["valgte"] else ([], 0.0, 0.0)

    tilbud = []
    for i in info:
        v = i["vare"]
        akt, ukl = ta.aktive(con, v, idag)
        ref = i["norm"] or v["maal"]
        for o in akt + ukl:
            if o["butik"] not in B:
                continue
            ep = o["enhedspris"]
            tilbud.append(dict(
                vare_id=v["id"], vare=v["navn"], enhed=v["enhed"], butik=o["butik"], butik_navn=B[o["butik"]]["navn"],
                zone=B[o["butik"]]["zone"], tekst=o["overskrift"], pris=o["pris"], ep=ep,
                rabat=(1 - ep / ref) if ep and ref else None, fra=o["gyldig_fra"], til=o["gyldig_til"],
                betingelse=o["betingelse"], kilde=o["kilde"], i_tur=(v["id"], o["butik"]) in i_tur,
                mistaenkelig=bool(ep and ref and 1 - ep / ref > cfg["regler"].get("max_rabat", 0.6))))

    lager = [dict(linje(c), butik_navn=B[c["butik"]]["navn"]) for cs in kands.values() for c in cs if c["lager"]]
    sidste = con.execute("SELECT MAX(hentet) m FROM obs WHERE kilde IN ('tjek','manuel')").fetchone()["m"]
    antal = con.execute("SELECT COUNT(*) n, SUM(kilde='demo') d FROM obs").fetchone()
    obs_pr_vare = {r["vare_id"]: r["n"] for r in con.execute("SELECT vare_id, COUNT(*) n FROM obs GROUP BY vare_id")}
    return dict(
        idag=idag.isoformat(),
        tur=dict(butikker=tur_butikker, sav=bedst["sav"], net=bedst["net"], stop=stop, margin=margin,
                 koersel=[dict(l) for l in kl], koersel_i_alt=sum(l["kr"] for l in kl)),
        afviste=[dict(zone=a["zone"], butikker=[B[s]["navn"] for s in a["butikker"]],
                      ekstra_sav=a["ekstra_sav"], ekstra_cost=a["ekstra_cost"]) for a in afviste],
        lager=lager, tilbud=tilbud,
        uafklaret=[dict(vare=o["vare"]["navn"], butik=B.get(o["butik"], {}).get("navn", o["butik"]),
                        tekst=o["overskrift"], pris=o["pris"]) for o in uafklaret[:8]],
        varestatus=[dict(id=i["vare"]["id"], norm=i["norm"], kilde=i["kilde"], bund=i["bund"], n=i["n"],
                         obs=obs_pr_vare.get(i["vare"]["id"], 0)) for i in info],
        sidste_hentning=sidste, antal_obs=antal["n"] or 0, demo=bool(antal["d"]),
        raa_antal=(r := con.execute("SELECT COUNT(*) n, MIN(foerst_set) f FROM raa").fetchone())["n"], raa_foerst=r["f"],
    )


def historik(cfg, varer, con, vare_id: str, idag: date) -> dict:
    v = next((x for x in varer if x["id"] == vare_id), None)
    if not v:
        raise ValueError("Ukendt vare.")
    B = cfg["butikker"]
    dage = cfg["regler"]["historik_dage"]
    rows = con.execute("SELECT butik, enhedspris ep, COALESCE(gyldig_fra, hentet) d FROM obs WHERE vare_id=? "
                       "AND enhedspris IS NOT NULL AND hentet>=? ORDER BY d", (vare_id, ta._cutoff(idag, dage))).fetchall()
    norm, kilde = ta.normalpris(con, v, dage, idag)
    bund, _ = ta.bundpris(con, v, dage, idag)
    return dict(vare=v["navn"], enhed=v["enhed"], normal=norm, normal_kilde=kilde, bund=bund, maal=v["maal"],
                punkter=[dict(d=r["d"][:10], butik=r["butik"], navn=B.get(r["butik"], {}).get("navn", r["butik"]),
                              zone=B.get(r["butik"], {}).get("zone", ""), ep=r["ep"]) for r in rows])


# -------------------------------------------------------------- skrivning ---
def vare_fra_form(b: dict, eksisterende: list[dict]) -> dict:
    navn = str(b.get("navn", "")).strip()
    if not navn:
        raise ValueError("Varen skal have et navn.")
    if b.get("enhed") not in ("kg", "l", "stk"):
        raise ValueError("Enhed skal være kg, l eller stk.")
    ids = {v["id"] for v in eksisterende}
    vid = b.get("id")
    if not vid:
        vid, n = slug(navn), 2
        while vid in ids:
            vid, n = f"{slug(navn)}-{n}", n + 1
    typ = "specifik" if b.get("type") == "specifik" else "generisk"
    maerker = liste(b.get("maerker"))
    if typ == "specifik" and not maerker:
        raise ValueError("Skriv mindst ét mærke eller produkt, fx «heinz ketchup».")
    return dict(
        id=vid, navn=navn, enhed=b["enhed"], type=typ, maerker=maerker, udeluk_maerker=liste(b.get("udeluk_maerker")),
        soeg=liste(b.get("soeg")) or (maerker if typ == "specifik" else [navn.lower()]),
        udeluk=liste(b.get("udeluk")),
        normal=talfelt(b.get("normal"), 0.01, 100000, "Normalpris", True),
        maal=talfelt(b.get("maal"), 0.01, 100000, "Målpris", True),
        koeb=talfelt(b.get("koeb") or 1, 0.001, 100000, "Købsmængde"),
        lager=talfelt(b.get("lager"), 0.001, 100000, "Maks. lager", True))


def indstillinger_fra_form(b: dict, cfg: dict) -> dict:
    ny = json.loads(json.dumps(cfg))
    ny["adresse"] = str(b.get("adresse", "")).strip()[:200]
    t, tb = ny["tjek"], b.get("tjek", {})
    t["lat"] = talfelt(tb.get("lat") or 0, -90, 90, "Breddegrad")
    t["lng"] = talfelt(tb.get("lng") or 0, -180, 180, "Længdegrad")
    t["radius_m"] = int(talfelt(tb.get("radius_m", t["radius_m"]), 500, 200000, "Radius (meter)"))
    if "api_key" in tb:
        t["api_key"] = str(tb["api_key"]).strip()
    k, kb = ny["koersel"], b.get("koersel", {})
    k["kr_pr_km"] = talfelt(kb.get("kr_pr_km"), 0, 50, "Kr pr. km")
    k["stop_kr"] = talfelt(kb.get("stop_kr"), 0, 1000, "Pris pr. butik")
    k["margin_pr_tur_kr"] = talfelt(kb.get("margin_pr_tur_kr", 0), 0, 10000, "Margin pr. tur")
    k["sunk_zoner"] = [str(z) for z in kb.get("sunk_zoner", [])]
    k["auto_afstand"] = bool(kb.get("auto_afstand"))
    g = kb.get("zone_graenser") or [10, 20]
    g1, g2 = talfelt(g[0], 1, 500, "Grænse for lokal zone"), talfelt(g[1], 1, 500, "Grænse for mellem-zone")
    if g1 >= g2:
        raise ValueError("Grænsen for «lokal» skal være mindre end grænsen for «mellem».")
    k["zone_graenser"] = [g1, g2]
    ny.setdefault("app", {})["auto_hent"] = bool((b.get("app") or {}).get("auto_hent", True))
    r, rb = ny["regler"], b.get("regler", {})
    r["min_rabat"] = talfelt(rb.get("min_rabat"), 0, 0.95, "Mindste rabat")
    r["lager_rabat"] = talfelt(rb.get("lager_rabat"), 0, 0.95, "Rabat for lagerkøb")
    r["max_rabat"] = talfelt(rb.get("max_rabat", 0.6), 0.2, 1, "Mistænkelig rabat")
    r["historik_dage"] = int(talfelt(rb.get("historik_dage"), 14, 1000, "Historik (dage)"))
    butikker = {}
    for key, bb in (b.get("butikker") or {}).items():
        navn = str(bb.get("navn", "")).strip()
        if not navn:
            raise ValueError("Alle butikker skal have et navn.")
        bid = key
        if key.startswith("ny:"):
            bid, n = slug(navn), 2
            while bid in butikker or bid in cfg["butikker"]:
                bid, n = f"{slug(navn)}-{n}", n + 1
        ny_b = dict(navn=navn, afstand_km=talfelt(bb.get("afstand_km"), 0, 2000, f"Afstand til {navn}"),
                    zone=str(bb.get("zone", "")).strip().lower() or "lokal",
                    tjek_navn=liste(bb.get("tjek_navn")) or [navn.lower()])
        if bb.get("fast_afstand"):
            ny_b["fast_afstand"] = True
        if bb.get("kilde") == "manuel":
            ny_b["kilde"] = "manuel"
        butikker[bid] = ny_b
    if not butikker:
        raise ValueError("Mindst én butik skal være med.")
    ny["butikker"] = butikker
    zoner = {x["zone"] for x in butikker.values()}
    k["sunk_zoner"] = [z for z in k["sunk_zoner"] if z in zoner]
    return ny


def geokod(q: str) -> list[dict]:
    """Adresse -> koordinater via OpenStreetMap Nominatim (lejlighedsvis opslag; maks. 1 pr. sekund)."""
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "countrycodes": "dk", "limit": 5})
    req = urllib.request.Request(url, headers={"User-Agent": f"tilbudsagent/{ta.VERSION} (lokal desktop-app)", "Accept-Language": "da"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    return [dict(navn=d["display_name"], lat=float(d["lat"]), lng=float(d["lon"])) for d in data]


def start_hent() -> dict:
    st = APP["hent"]
    with LOCK:
        if st.get("koerer"):
            return st
        st.clear()
        st.update(koerer=True, start=datetime.now().isoformat(timespec="seconds"), gjort=0, i_alt=0, nye=0, nu="")

    def job():
        con = ta.connect(APP["db"])
        try:
            cfg, varer = ta.get_cfg(con, APP["config"]), ta.get_varer(con, APP["varer"])
            res = ta.hent(cfg, varer, con, date.today(), fremdrift=st)
            pos = geo.aktiv_position(con, cfg)
            t = cfg["tjek"]
            if (not pos["hjem"] and (t.get("lat") or t.get("lng")) and (pos["lat"] or pos["lng"])
                    and geo.luftlinje_km(t["lat"], t["lng"], pos["lat"], pos["lng"]) > t.get("radius_m", 30000) / 2000):
                c2 = json.loads(json.dumps(cfg))  # position er langt fra hjem: hent også tilbud omkring den
                c2["tjek"]["lat"], c2["tjek"]["lng"] = pos["lat"], pos["lng"]
                r2 = ta.hent(c2, varer, con, date.today(), fremdrift=st)
                for kk in ("nye", "raa_nye", "fejl", "kald"):
                    res[kk] = res.get(kk, 0) + r2.get(kk, 0)
            st["resultat"] = res
            if st["resultat"]["fejl"] < max(1, st["resultat"].get("kald", 1)):  # mindst ét kald lykkedes
                con.execute("INSERT OR REPLACE INTO kv(key,value) VALUES('sidste_hent_ts',?)", (datetime.now().isoformat(timespec="seconds"),))
                con.commit()
        except Exception as e:  # vis fejlen i appen
            st["fejl"] = str(e)
        finally:
            st["koerer"] = False
            st["slut"] = datetime.now().isoformat(timespec="seconds")
            con.close()
    threading.Thread(target=job, daemon=True).start()
    return st


# ------------------------------------------------- eksport / import / fejlrapport ---
def eksport(con, cfg, varer, historik=False) -> dict:
    """Opsætningen som én fil, så den kan flyttes til en anden pc. Med historik=True følger alle gemte tilbud med."""
    d = dict(format="tilbudsagent-opsaetning", version=ta.VERSION,
             eksporteret=datetime.now().isoformat(timespec="seconds"), cfg=cfg, varer=varer)
    if historik:
        d["raa"] = [dict(r) for r in con.execute("SELECT * FROM raa")]
        d["obs_manuel"] = [{k: r[k] for k in r.keys() if k != "id"} for r in con.execute("SELECT * FROM obs WHERE kilde='manuel'")]
    return d


RAA_KOL = ["tjek_id", "forhandler", "overskrift", "beskrivelse", "pris", "foer_pris", "gyldig_fra", "gyldig_til",
           "foerst_set", "sidst_set", "soeg", "json"]


def flet_historik(con, b: dict) -> tuple[int, int]:
    """Fletter gemte tilbud ind uden dubletter: første/sidste gang set bevares, intet overskrives."""
    ny = 0
    for r in b.get("raa") or []:
        if not isinstance(r, dict) or not r.get("tjek_id") or not r.get("json"):
            continue
        json.loads(r["json"])  # skal være gyldig JSON
        fandtes = con.execute("SELECT 1 FROM raa WHERE tjek_id=?", (str(r["tjek_id"]),)).fetchone()
        con.execute("""INSERT INTO raa(%s) VALUES(%s) ON CONFLICT(tjek_id) DO UPDATE SET
                       foerst_set=MIN(raa.foerst_set, excluded.foerst_set), sidst_set=MAX(raa.sidst_set, excluded.sidst_set)"""
                    % (",".join(RAA_KOL), ",".join("?" * len(RAA_KOL))), [r.get(k) for k in RAA_KOL])
        ny += 0 if fandtes else 1
    manuelle = 0
    for r in b.get("obs_manuel") or []:
        if isinstance(r, dict) and r.get("tjek_id") and r.get("vare_id") and r.get("butik"):
            manuelle += ta.indsaet(con, **r)
    return ny, manuelle


def import_opsaetning(con, b: dict) -> int:
    if b.get("format") != "tilbudsagent-opsaetning":
        raise ValueError("Det er ikke en eksporteret opsætning fra Tilbudsagent.")
    cfg, varer = b.get("cfg"), b.get("varer")
    if not isinstance(cfg, dict) or not all(isinstance(cfg.get(k), dict) for k in ("koersel", "tjek", "regler", "butikker")):
        raise ValueError("Filen mangler indstillinger (kørsel, Tjek, regler eller butikker).")
    if not cfg["butikker"]:
        raise ValueError("Filen indeholder ingen butikker.")
    for bid, bu in cfg["butikker"].items():
        if not isinstance(bu, dict) or not all(k in bu for k in ("navn", "afstand_km", "zone", "tjek_navn")):
            raise ValueError(f"Butikken «{bid}» i filen er ufuldstændig.")
    if not isinstance(varer, list):
        raise ValueError("Filen mangler varer.")
    for v in varer:
        if not isinstance(v, dict) or not all(k in v for k in ("id", "navn", "enhed", "soeg")) or v["enhed"] not in ("kg", "l", "stk"):
            raise ValueError("En vare i filen er ufuldstændig.")
    for k in ("raa", "obs_manuel"):
        if k in b and not isinstance(b[k], list):
            raise ValueError("Historikken i filen er ugyldig.")
    ta.save_cfg(con, cfg)
    con.execute("DELETE FROM vare")
    for v in varer:
        ta.save_vare(con, v)
    con.execute("INSERT OR REPLACE INTO kv(key,value) VALUES('varer_seedet','1')")
    ny, man = flet_historik(con, b)
    con.commit()
    cfg2, v2 = ta.get_cfg(con, APP["config"]), ta.get_varer(con, APP["varer"])
    for v in v2:
        ta.ryd_obs(con, v)
    ta.genopbyg(con, cfg2, v2)
    return ny


def fejlrapport(con, cfg, varer) -> str:
    """Tekst testere kan sende. Ingen adresse eller koordinater; kun version, system, opsætning og seneste log."""
    c = json.loads(json.dumps(cfg))
    c.get("tjek", {}).pop("api_key", None)
    for k in ("lat", "lng"):
        c.get("tjek", {}).pop(k, None)
    c.pop("adresse", None)
    obs = con.execute("SELECT COUNT(*) n, MIN(hentet) fra, MAX(hentet) til FROM obs").fetchone()
    pr_butik = con.execute("SELECT butik, COUNT(*) n FROM obs GROUP BY butik ORDER BY n DESC").fetchall()
    log = ""
    lf = ta.DATA / "tilbudsagent.log"
    if lf.exists():
        log = "\n".join(lf.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
    return "\n".join([
        f"Tilbudsagent {ta.VERSION}", f"Tid: {datetime.now().isoformat(timespec='seconds')}",
        f"System: {platform.platform()}  Python {sys.version.split()[0]}  pakket: {ta.FROSSET}",
        f"Observationer: {obs['n']} ({obs['fra']} til {obs['til']})",
        "Pr. butik: " + ", ".join(f"{r['butik']}={r['n']}" for r in pr_butik),
        f"Seneste hentning: {APP['hent']}", "", "Opsætning (uden adresse/koordinater/nøgle):",
        json.dumps(c, ensure_ascii=False, indent=1), "", f"Varer: {len(varer)}",
        json.dumps([{k: v.get(k) for k in ("id", "navn", "enhed", "type", "soeg", "maerker", "udeluk")} for v in varer],
                   ensure_ascii=False), "", "Log (seneste linjer):", log or "(tom)"])


def auto_hent_loop() -> None:
    """Henter selv tilbud, hvis der er gået over 20 timer siden sidst, mens appen er åben (og adressen er sat)."""
    time.sleep(20)
    while True:
        try:
            con = ta.connect(APP["db"])
            try:
                cfg = ta.get_cfg(con, APP["config"])
                sidst = con.execute("SELECT value FROM kv WHERE key='sidste_hent_ts'").fetchone()
            finally:
                con.close()
            gammel = not sidst or (datetime.now() - datetime.fromisoformat(sidst["value"])).total_seconds() > 20 * 3600
            if cfg["app"].get("auto_hent", True) and gammel and (cfg["tjek"].get("lat") or cfg["tjek"].get("lng")):
                print("Automatisk hentning af tilbud ...")
                start_hent()
        except Exception as e:  # må aldrig vælte appen
            print(f"Automatisk hentning fejlede: {e}", file=sys.stderr)
        time.sleep(30 * 60)


def meld(tekst: str, titel: str = "Tilbudsagent") -> None:
    """Fejl- og statusbesked. Uden konsol (pakket .exe) vises en dialogboks på Windows."""
    print(tekst)
    if ta.FROSSET and sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, tekst, titel, 0x40)
        except Exception:
            pass


# ------------------------------------------------------------------ http ---
class Handler(BaseHTTPRequestHandler):
    server_version = "tilbudsagent"

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _host_ok(self):
        return self.headers.get("Host", "").split(":")[0] in ("localhost", "127.0.0.1")

    def do_GET(self):
        if not self._host_ok():
            return self._json({"fejl": "Ugyldig vært."}, 403)
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == "/":
                return self._send(200, (HERE / "app.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/hent/status":
                return self._json(APP["hent"])
            if u.path == "/api/ping":
                return self._json(dict(app="tilbudsagent", version=ta.VERSION))
            con = ta.connect(APP["db"])
            try:
                cfg, varer = ta.get_cfg(con, APP["config"]), ta.get_varer(con, APP["varer"])
                if u.path == "/api/state":
                    ceff = geo.effektiv(con, cfg)  # afstande/zoner for den aktive position (hjem eller "lige nu")
                    sen = con.execute("SELECT value FROM kv WHERE key='positioner_seneste'").fetchone()
                    eff = {bid: dict(navn=b["navn"], afstand_km=b["afstand_km"], zone=b["zone"], fundet=b.get("_fundet"),
                                     fjernet=bid not in ceff["butikker"]) for bid, b in cfg["butikker"].items()}
                    for bid, b in ceff["butikker"].items():
                        eff[bid].update(afstand_km=b["afstand_km"], zone=b["zone"], fundet=b.get("_fundet"))
                    return self._json(dict(cfg=cfg, varer=varer, dash=dashboard(ceff, varer, con, date.today()),
                                           position=ceff["_position"], seneste_positioner=json.loads(sen["value"]) if sen else [],
                                           eff_butikker=eff, zoner_eff=sorted({b["zone"] for b in ceff["butikker"].values()}),
                                           hent=APP["hent"], version=ta.VERSION, data_mappe=str(ta.DATA),
                                           db_mb=round(APP["db"].stat().st_size / 1e6, 1)))
                if u.path == "/api/eksport":
                    dato = date.today().isoformat()
                    return self._send(200, json.dumps(eksport(con, cfg, varer, u.query == "historik=1"), ensure_ascii=False, indent=None if u.query else 1).encode("utf-8"),
                                      "application/json; charset=utf-8",
                                      {"Content-Disposition": f'attachment; filename="tilbudsagent-{"komplet" if u.query else "opsaetning"}-{dato}.json"'})
                if u.path == "/api/fejlrapport":
                    return self._send(200, fejlrapport(con, cfg, varer).encode("utf-8"), "text/plain; charset=utf-8",
                                      {"Content-Disposition": 'attachment; filename="tilbudsagent-fejlrapport.txt"'})
                if u.path == "/api/historik":
                    vid = urllib.parse.parse_qs(u.query).get("vare", [""])[0]
                    return self._json(historik(cfg, varer, con, vid, date.today()))
            finally:
                con.close()
            self._json({"fejl": "Findes ikke."}, 404)
        except ValueError as e:
            self._json({"fejl": str(e)}, 400)

    def do_POST(self):
        if not self._host_ok() or "application/json" not in self.headers.get("Content-Type", ""):
            return self._json({"fejl": "Afvist."}, 403)
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > 100_000_000:
                raise ValueError("For stor forespørgsel.")
            b = json.loads(self.rfile.read(n) or b"{}")
            u = urllib.parse.urlparse(self.path).path
            if u == "/api/hent":
                return self._json(start_hent())
            if u == "/api/afslut":
                self._json({"ok": True})
                threading.Thread(target=APP["server"].shutdown, daemon=True).start()
                return
            if u == "/api/geokod":
                q = str(b.get("q", "")).strip()
                if len(q) < 3:
                    raise ValueError("Skriv en adresse (mindst 3 tegn).")
                try:
                    return self._json(dict(resultater=geokod(q)))
                except (urllib.error.URLError, TimeoutError, ValueError) as e:
                    raise ValueError(f"Adresseopslag mislykkedes ({e}). Indtast breddegrad og længdegrad manuelt.")
            con = ta.connect(APP["db"])
            try:
                cfg, varer = ta.get_cfg(con, APP["config"]), ta.get_varer(con, APP["varer"])
                if u == "/api/vare":
                    v = vare_fra_form(b, varer if not b.get("id") else [])
                    ta.save_vare(con, v)
                    ta.ryd_obs(con, v)  # fjern gemte priser der ikke passer til de nye regler
                    ta.genopbyg(con, cfg, [v])  # og find tilbud vi allerede har set, som nu passer
                elif u == "/api/vare/slet":
                    con.execute("DELETE FROM vare WHERE id=?", (str(b.get("id", "")),))
                    con.commit()
                elif u == "/api/indstillinger":
                    ny = indstillinger_fra_form(b, cfg)
                    ta.save_cfg(con, ny)
                    ta.genopbyg(con, ny, varer)  # butiksnavne kan være rettet
                    if ny["koersel"].get("auto_afstand") and (ny["tjek"].get("lat") or ny["tjek"].get("lng")):
                        try:  # slår kun op for det, der mangler (nye butikker, ændret adresse)
                            geo.find_afstande(con, ny["butikker"], ny["tjek"]["lat"], ny["tjek"]["lng"])
                        except RuntimeError as e:
                            raise ValueError(f"Indstillingerne er gemt, men afstande kunne ikke findes automatisk: {e}")
                elif u == "/api/position":
                    lat, lng = talfelt(b.get("lat"), -90, 90, "Breddegrad"), talfelt(b.get("lng"), -180, 180, "Længdegrad")
                    navn = str(b.get("navn") or "").strip()[:200] or "Anden position"
                    try:
                        rows = geo.find_afstande(con, cfg["butikker"], lat, lng)
                    except RuntimeError as e:
                        raise ValueError(str(e))
                    if not any(r["km"] is not None for r in rows.values()):
                        raise ValueError("Der blev ikke fundet nogen af dine butikker inden for 60 km af det sted.")
                    geo.gem_position(con, navn, lat, lng, bool(b.get("sunk", True)))
                elif u == "/api/position/hjem":
                    geo.ryd_position(con)
                elif u == "/api/afstande":
                    pos = geo.aktiv_position(con, cfg)
                    if not (pos["lat"] or pos["lng"]):
                        raise ValueError("Sæt din adresse under Indstillinger først.")
                    try:
                        geo.find_afstande(con, cfg["butikker"], pos["lat"], pos["lng"], tving=bool(b.get("tving")))
                    except RuntimeError as e:
                        raise ValueError(str(e))
                elif u == "/api/manuel":
                    ta.manuel(cfg, varer, con, SimpleNamespace(
                        butik=b.get("butik"), vare=b.get("vare"),
                        pris=talfelt(b.get("pris"), 0.01, 100000, "Pris"),
                        maengde=talfelt(b.get("maengde"), 0.001, 100000, "Mængde"),
                        foer=talfelt(b.get("foer"), 0.01, 100000, "Førpris", True),
                        til=(b.get("til") or None)), date.today())
                elif u == "/api/import":
                    self._json(dict(ok=True, nye_tilbud=import_opsaetning(con, b)))
                    return
                elif u == "/api/demo":
                    if b.get("paa"):
                        ta.demo(cfg, varer, con, date.today())
                    else:
                        con.execute("DELETE FROM obs WHERE kilde='demo'")
                        con.commit()
                else:
                    return self._json({"fejl": "Findes ikke."}, 404)
            finally:
                con.close()
            self._json({"ok": True})
        except (ValueError, json.JSONDecodeError) as e:
            self._json({"fejl": str(e)}, 400)


def migrer(con, cfg: dict) -> None:
    """Engangsrettelser af data fra tidligere versioner."""
    if not con.execute("SELECT 1 FROM kv WHERE key='migr_stk_v1'").fetchone():
        # Før blev "stk" uden kendt antal regnet som 1 stk. Sådanne enhedspriser var forkerte → ukendt.
        con.execute("UPDATE obs SET enhedspris=NULL WHERE kilde='tjek' AND enhed='stk' "
                    "AND enhedspris IS NOT NULL AND ABS(enhedspris-pris)<1e-9")
        con.execute("INSERT OR REPLACE INTO kv(key,value) VALUES('migr_stk_v1','1')")
        con.commit()
    aendret = False
    if not con.execute("SELECT 1 FROM kv WHERE key='migr_butikker_v2'").fetchone():
        for bid, navn, km, zone, tn in (("bilka", "Bilka", 22.6, "fjern", ["bilka"]),
                                        ("loevbjerg", "Løvbjerg", 27.8, "fjern", ["løvbjerg", "lovbjerg"]),
                                        ("kvickly", "Kvickly", 13.8, "mellem", ["kvickly"])):
            if bid not in cfg["butikker"]:
                cfg["butikker"][bid] = dict(navn=navn, afstand_km=km, zone=zone, tjek_navn=tn)
                aendret = True
        con.execute("INSERT OR REPLACE INTO kv(key,value) VALUES('migr_butikker_v2','1')")
        con.commit()
    if not con.execute("SELECT 1 FROM kv WHERE key='migr_zone_mellem_v1'").fetchone():
        for b in cfg["butikker"].values():
            if b.get("zone") == "spar":
                b["zone"] = "mellem"
                aendret = True
        cfg["koersel"]["sunk_zoner"] = ["mellem" if z == "spar" else z for z in cfg["koersel"].get("sunk_zoner", [])]
        con.execute("INSERT OR REPLACE INTO kv(key,value) VALUES('migr_zone_mellem_v1','1')")
        con.commit()
    for bid, b in cfg["butikker"].items():  # butikker der viser sig at findes på Tjek behøver ikke indtastes manuelt
        if b.get("kilde") == "manuel" and con.execute(
                "SELECT 1 FROM obs WHERE butik=? AND kilde='tjek' LIMIT 1", (bid,)).fetchone():
            del b["kilde"]
            aendret = True
    if aendret:
        ta.save_cfg(con, cfg)


def koer(a) -> None:
    APP.update(db=a.db, config=a.config, varer=a.varer)
    con = ta.connect(a.db)  # opretter tabeller + indlæser startværdier
    cfg = ta.get_cfg(con, a.config)
    for v in ta.get_varer(con, a.varer):
        ta.ryd_obs(con, v)  # fjerner gamle fejlmatch (matcher kun på overskrift nu)
    migrer(con, cfg)
    ta.genopbyg(con, ta.get_cfg(con, a.config), ta.get_varer(con, a.varer))  # fra gemte rå tilbud
    if ta.rens_gamle(con, ta.get_cfg(con, a.config)["regler"].get("raa_dage", 730)) > 500:
        con.execute("VACUUM")  # giv pladsen tilbage efter en stor oprydning
    con.close()
    url = f"http://localhost:{a.port}/"
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    except OSError:
        try:  # kører Tilbudsagent allerede? Så åbn bare den eksisterende i browseren.
            with urllib.request.urlopen(url + "api/ping", timeout=3) as r:
                if json.load(r).get("app") == "tilbudsagent":
                    if not a.ingen_browser:
                        webbrowser.open(url)
                    print("Tilbudsagent kører allerede – åbner den i browseren.")
                    return
        except Exception:
            pass
        meld(f"Port {a.port} er optaget af et andet program. Luk det, eller start med --port {a.port + 1}.")
        raise SystemExit(1)
    APP["server"] = srv
    threading.Thread(target=auto_hent_loop, daemon=True).start()
    print(f"Tilbudsagent {ta.VERSION} kører på {url}  (Ctrl+C eller knappen Afslut for at stoppe)")
    print(f"Data: {ta.DATA}")
    if not a.ingen_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    print("Stoppet.")
