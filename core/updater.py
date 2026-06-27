"""
Logika sprawdzania aktualizacji
"""

import json
import os.path
import time
import requests
import logging


def check_update():
    """
    Jeśli włączone, sprawdź czy wersja szablonu konfiguracji pasuje do tej na githubie
    Powiadom i 5 sekund przerwy, jeśli aktualizacja jest dostępna
    """
    get_local_config_template_version = os.path.join(
        os.path.dirname(__file__),
        "..",
        "config.example.json"
    )

    get_local_config_version = os.path.join(
        os.path.dirname(__file__),
        "..",
        "config.json"
    )
    if os.path.exists(get_local_config_version):
        try:
            with open(get_local_config_version, "r", encoding="utf-8") as running_cf:
                parsed = json.load(fp=running_cf)
                if not parsed.get("bot", {}).get("check_update", False):
                    return
        except Exception as e:
            logging.debug("Nie można wczytać config.json: %s", e)
            return

    if not os.path.exists(get_local_config_template_version):
        return

    try:
        with open(get_local_config_template_version, "r", encoding="utf-8") as local_cf:
            parsed = json.load(fp=local_cf)
    except Exception as e:
        logging.debug("Nie można wczytać config.example.json: %s", e)
        return

    # Sprawdź aktualizację z tolerancją na brak internetu
    try:
        get_remote_version = requests.get(
            "https://raw.githubusercontent.com/stefan2200/TWB/master/config.example.json",
            timeout=(10, 30),
        ).json()
        if parsed["build"]["version"] != get_remote_version["build"]["version"]:
            logging.warning(
                "Dostępna jest nowa wersja bota.\n"
                "Pobierz najnowsze wydanie z:\n"
                "https://github.com/stefan2200/TWB"
            )
            time.sleep(5)
        else:
            logging.info("Bot jest aktualny")
    except (requests.RequestException, ValueError, KeyError) as e:
        logging.debug("Nie udało się sprawdzić aktualizacji (brak internetu?): %s", e)
