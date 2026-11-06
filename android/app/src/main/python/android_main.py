"""Startpunkt for Android-appen: Kotlin kalder start() i en baggrundstråd, og serveren kører i processen."""
import os


def start(res_dir: str, data_dir: str, port: int) -> None:
    # skal sættes før tilbudsagent importeres (RES og DATA findes ved import)
    os.environ["TILBUDSAGENT_RES"] = res_dir
    os.environ["TILBUDSAGENT_DATA"] = data_dir
    import tilbudsagent
    tilbudsagent.main(["app", "--port", str(port), "--ingen-browser"])
