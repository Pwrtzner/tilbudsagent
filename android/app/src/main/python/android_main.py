"""Startpunkt for Android-appen: Kotlin kalder start() i en baggrundstråd, og serveren kører i processen."""
import os


def _miljoe(res_dir: str, data_dir: str) -> None:
    # skal sættes før tilbudsagent importeres (RES og DATA findes ved import)
    os.environ["TILBUDSAGENT_RES"] = res_dir
    os.environ["TILBUDSAGENT_DATA"] = data_dir


def start(res_dir: str, data_dir: str, port: int) -> None:
    _miljoe(res_dir, data_dir)
    import tilbudsagent
    tilbudsagent.main(["app", "--port", str(port), "--ingen-browser"])


def hent_baggrund(res_dir: str, data_dir: str) -> str:
    """Kaldes af Android-baggrundsjobbet (WorkManager): hent tilbud, find nye topkøb og returnér dem som JSON."""
    import json
    from pathlib import Path
    _miljoe(res_dir, data_dir)
    import tilbudsagent as ta
    import webapp
    webapp.APP.update(db=Path(data_dir) / "priser.db", config=Path(res_dir) / "config.toml", varer=Path(res_dir) / "varer.csv")
    con = ta.connect(webapp.APP["db"])  # opretter tabeller og startværdier, hvis appen aldrig har været åbnet
    ta.get_cfg(con, webapp.APP["config"])
    ta.get_varer(con, webapp.APP["varer"])
    con.close()
    return json.dumps(webapp.baggrundshent(), ensure_ascii=False)
