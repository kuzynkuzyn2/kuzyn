"""
Moduł Debug Cycle - przeprowadza pełen cykl bota w trybie diagnostycznym.

Główne cechy:
- Wywołuje KAŻDĄ akcję cyklu po kolei (village_init, builder, units, recruit,
  farm_assistant, gather, market)
- Zapisuje kopie WSZYSTKICH odpowiedzi HTTP do cache/debugcycle/<village_id>/<screen>.html
- Generuje raport JSON z wynikami każdej akcji (sukces/porażka/przyczyna)
- Zapisuje też wyciągi Extractor (game_state, building_data, recruit_data, etc.)
  do cache/debugcycle/<village_id>/<screen>.json
- Nie blokuje głównego bota - działa w subprocess lub osobnym wątku
- Loguje wszystko do konsoli z kolorowym oznaczeniem sekcji

Wywołanie:
    python debug_cycle.py                 # uruchamia cykl dla wszystkich wiosek
    python debug_cycle.py --village 123   # tylko dla wioski 123
    python debug_cycle.py --dry-run       # bez prawdziwych POSTów

Konkretne screen-y, które są odpytywane w każdym cyklu:
- overview         (game_state - village, player, resources)
- main             (BuildingMain.buildings - koszty budowy)
- place&mode=units&display=units  (dostępne wojska w wiosce)
- smith            (BuildingSmith.techs - poziomy badań)
- train            (jednostki do rekrutacji)
- market           (oferty rynkowe)
- am_farm          (farm assistant targets)
- scavenge         (opcje zbieractwa)
"""

import collections
import json
import logging
import os
import re
import sys
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Upewnij się, że katalog projektu jest w sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.extractors import Extractor
from core.filemanager import FileManager

LOGGER = logging.getLogger("DebugCycle")
# Logger odziedziczy handlery z root loggera, więc wiadomości pojawią się
# zarówno w konsoli stderr, jak i w webmanager (przez bot_log_handler).
if not LOGGER.handlers and not LOGGER.parent.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s - [%(levelname)s] [%(name)s] - %(message)s"
    ))
    LOGGER.addHandler(_handler)
LOGGER.setLevel(logging.DEBUG)
# Zapobiegaj podwójnemu logowaniu przez propagację
LOGGER.propagate = True


# Lista screen-ów do przetestowania w cyklu diagnostycznym
# Każdy screen to krotka (action, mode) gdzie:
# - action: nazwa akcji przekazywana do get_action()
# - mode: dodatkowy parametr mode dla get_url() (None = brak)
DEBUG_CYCLE_SCREENS: List[Tuple[str, Optional[str]]] = [
    # (screen_action, mode)
    ("overview", None),               # village state, player info
    ("main", None),                    # building data
    ("place", "units"),                # available units (display mode)
    ("smith", None),                   # smithy research
    ("train", None),                   # recruit (barracks)
    ("market", None),                   # market offers
    ("am_farm", None),                 # farm assistant targets
    ("scavenge", None),                # gather options
]


class DebugCycleResult:
    """Pojedynczy wynik akcji w cyklu debug."""

    def __init__(self, name: str, success: bool, message: str = "",
                 details: Optional[Dict[str, Any]] = None):
        self.name = name
        self.success = success
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "success": self.success,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
        }


class DebugCycleRunner:
    """
    Przeprowadza pełen cykl diagnostyczny dla wybranej wioski lub wszystkich wiosek.

    Cykl:
    1. village_init() - pobiera overview, parsuje game_state
    2. set_world_config() - sprawdza opcje świata
    3. update_pre_run() - aktualizuje stan zasobów
    4. setup_defence_manager() - sprawdza stan obrony
    5. run_builder() - próbuje budować
    6. units_get_template() - ładuje szablon jednostek
    7. set_unit_wanted_levels() - oblicza pożądane jednostki
    8. units.update_totals() - aktualizuje liczbę wojsk
    9. attempt_upgrade() - bada w kuźni
    10. do_recruit() - rekrutuje
    11. run_farming() - farma (attack manager)
    12. do_gather() - zbiera
    13. go_manage_market() - rynek

    Każdy krok jest niezależny - jeśli jeden zawiedzie, cykl kontynuuje.
    """

    def __init__(self, wrapper, village_id: str, config: Optional[Dict] = None,
                 dry_run: bool = False, save_responses: bool = True,
                 output_dir: str = "cache/debugcycle"):
        """
        :param wrapper: WebWrapper z aktywną sesją
        :param village_id: ID wioski do debugowania
        :param config: konfiguracja bota (config["villages"][vid] itp.)
        :param dry_run: jeśli True, nie wykonuje prawdziwych POSTów
        :param save_responses: jeśli True, zapisuje odpowiedzi HTTP
        :param output_dir: katalog wyjściowy
        """
        self.wrapper = wrapper
        self.village_id = str(village_id)
        self.config = config or {}
        self.dry_run = dry_run
        self.save_responses = save_responses
        self.output_dir = output_dir
        self.village_dir = os.path.join(output_dir, self.village_id)
        self.results: List[DebugCycleResult] = []
        self.responses: Dict[str, Dict[str, Any]] = {}  # screen_name -> {html, json_extracted, status, size}
        self.errors: List[Dict[str, Any]] = []
        self.start_time = None
        self.end_time = None

        # Utwórz katalog wyjściowy
        if self.save_responses:
            os.makedirs(self.village_dir, exist_ok=True)

        # Konfiguracja managera raportowania błędów
        self._report = []

        # W trybie debug NIE czekamy 3-7s na każde żądanie HTTP.
        # priority_mode pomija delay w wrapper.get_url/post_url.
        # Zmiana jest widoczna dla wszystkich kolejnych requestów,
        # dlatego przywracamy oryginalną wartość na końcu cyklu.
        self._old_priority_mode = getattr(self.wrapper, "priority_mode", False)
        self._old_delay = getattr(self.wrapper, "delay", 1.0)
        try:
            self.wrapper.priority_mode = True
            if hasattr(self.wrapper, "delay"):
                self.wrapper.delay = 0.0
        except Exception:
            LOGGER.warning("Nie udało się ustawić priority_mode na wrapperze", exc_info=True)

    def __del__(self):
        try:
            if hasattr(self, "_old_priority_mode"):
                self.wrapper.priority_mode = self._old_priority_mode
            if hasattr(self, "_old_delay") and hasattr(self.wrapper, "delay"):
                self.wrapper.delay = self._old_delay
        except Exception:
            pass
        """Zapisuje odpowiedź HTTP do pliku HTML i wyciąg JSON do pliku JSON."""
        if not self.save_responses or response is None:
            return
        try:
            html_text = response.text if hasattr(response, 'text') else str(response)
            status_code = getattr(response, 'status_code', None)
            url = getattr(response, 'url', None)
            size = len(html_text) if html_text else 0
            html_path = os.path.join(self.village_dir, f"{screen_name}.html")
            with open(html_path, 'w', encoding='utf-8') as f:
                # Zapisz metadane w komentarzu HTML
                f.write("<!-- DEBUG CYCLE RESPONSE\n")
                f.write(f"     screen: {screen_name}\n")
                f.write(f"     village_id: {self.village_id}\n")
                f.write(f"     timestamp: {datetime.utcnow().isoformat()}Z\n")
                if status_code:
                    f.write(f"     status: {status_code}\n")
                if url:
                    f.write(f"     url: {url}\n")
                f.write(f"     size: {size} bytes\n")
                f.write("     -->\n")
                f.write(html_text)
            self.responses[screen_name] = {
                "html_path": html_path,
                "size": size,
                "status_code": status_code,
                "url": url,
            }
            if extracted:
                json_path = os.path.join(self.village_dir, f"{screen_name}.json")
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(extracted, f, indent=2, default=str, ensure_ascii=False)
                self.responses[screen_name]["json_path"] = json_path
        except Exception as e:
            self.errors.append({
                "phase": "save_response",
                "screen": screen_name,
                "error": str(e),
            })

    def _save_final_report(self) -> str:
        """Zapisuje raport JSON z wynikami całego cyklu."""
        report = {
            "village_id": self.village_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "dry_run": self.dry_run,
            "total_actions": len(self.results),
            "successful_actions": sum(1 for r in self.results if r.success),
            "failed_actions": sum(1 for r in self.results if not r.success),
            "responses": self.responses,
            "errors": self.errors,
            "results": [r.to_dict() for r in self.results],
            "summary_by_phase": self._phase_summary(),
        }
        report_path = os.path.join(self.village_dir, "_report.json")
        try:
            os.makedirs(self.village_dir, exist_ok=True)
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, default=str, ensure_ascii=False)
        except Exception as e:
            LOGGER.error("Nie udało się zapisać raportu: %s", e)
        return report_path

    def _phase_summary(self) -> Dict[str, Dict[str, int]]:
        """Zwraca podsumowanie wyników pogrupowane wg faz."""
        summary = {}
        for r in self.results:
            phase = r.details.get("phase", "other")
            if phase not in summary:
                summary[phase] = {"total": 0, "ok": 0, "failed": 0}
            summary[phase]["total"] += 1
            if r.success:
                summary[phase]["ok"] += 1
            else:
                summary[phase]["failed"] += 1
        return summary

    # ------------------------------------------------------------------
    # Wrappery na WebWrapper z auto-zapisem odpowiedzi
    # ------------------------------------------------------------------
    def get_url(self, url, label=None):
        """Wrapper na wrapper.get_url() z auto-zapisem."""
        try:
            response = self.wrapper.get_url(url)
            if label and self.save_responses:
                self._save_response(label, response)
            return response
        except Exception as e:
            self.errors.append({
                "phase": "get_url",
                "label": label,
                "url": url,
                "error": str(e),
            })
            LOGGER.exception("Błąd w get_url(%s): %s", url, e)
            return None

    def get_action(self, action, mode=None, label=None):
        """Wrapper na wrapper.get_action() z auto-zapisem."""
        url = f"game.php?village={self.village_id}&screen={action}"
        if mode:
            url += f"&mode={mode}"
        try:
            response = self.wrapper.get_action(
                village_id=self.village_id, action=action
            )
            if label and self.save_responses:
                self._save_response(label, response)
            return response
        except Exception as e:
            self.errors.append({
                "phase": "get_action",
                "label": label,
                "action": action,
                "error": str(e),
            })
            LOGGER.exception("Błąd w get_action(%s): %s", action, e)
            return None

    def get_api_data(self, action, params=None, label=None):
        """Wrapper na wrapper.get_api_data() z auto-zapisem."""
        try:
            response = self.wrapper.get_api_data(
                village_id=self.village_id,
                action=action,
                params=params or {},
            )
            if label and self.save_responses:
                self._save_response(label, response)
            return response
        except Exception as e:
            self.errors.append({
                "phase": "get_api_data",
                "label": label,
                "action": action,
                "error": str(e),
            })
            LOGGER.exception("Błąd w get_api_data(%s): %s", action, e)
            return None

    def get_api_action(self, action, params=None, data=None, label=None):
        """Wrapper na wrapper.get_api_action() z auto-zapisem.
        W trybie dry_run NIE wysyła prawdziwych POSTów."""
        if self.dry_run:
            LOGGER.info("[DRY RUN] Pomijam POST %s", action)
            return None
        try:
            response = self.wrapper.get_api_action(
                village_id=self.village_id,
                action=action,
                params=params or {},
                data=data or {},
            )
            if label and self.save_responses:
                self._save_response(label, response)
            return response
        except Exception as e:
            self.errors.append({
                "phase": "get_api_action",
                "label": label,
                "action": action,
                "error": str(e),
            })
            LOGGER.exception("Błąd w get_api_action(%s): %s", action, e)
            return None

    # ------------------------------------------------------------------
    # Fazy cyklu
    # ------------------------------------------------------------------
    def phase_1_init_overview(self) -> DebugCycleResult:
        """Faza 1: pobranie overview i sparsowanie game_state."""
        try:
            url = f"game.php?village={self.village_id}&screen=overview"
            response = self.get_url(url, label="01_overview")
            if not response:
                return DebugCycleResult(
                    "phase_1_overview", False,
                    "Brak odpowiedzi z overview",
                    {"phase": "init"},
                )
            game_state = Extractor.game_state(response)
            if not game_state:
                return DebugCycleResult(
                    "phase_1_overview", False,
                    "Nie udało się sparsować game_state z overview",
                    {"phase": "init", "html_size": len(response.text or "")},
                )
            village = game_state.get("village", {})
            details = {
                "phase": "init",
                "village_name": village.get("name"),
                "village_id": village.get("id"),
                "wood": village.get("wood"),
                "stone": village.get("stone"),
                "iron": village.get("iron"),
                "pop": village.get("pop"),
                "pop_max": village.get("pop_max"),
                "storage_max": village.get("storage_max"),
                "buildings": village.get("buildings"),
                "player_id": game_state.get("player", {}).get("id"),
                "x": village.get("x"),
                "y": village.get("y"),
            }
            return DebugCycleResult(
                "phase_1_overview", True,
                f"Pobrano overview wioski {village.get('name')}",
                details,
            )
        except Exception as e:
            return DebugCycleResult(
                "phase_1_overview", False, f"Błąd: {e}", {"phase": "init"},
            )

    def phase_2_main_screen(self) -> DebugCycleResult:
        """Faza 2: pobranie ekranu main (koszty budowy)."""
        try:
            response = self.get_action("main", label="02_main")
            if not response:
                return DebugCycleResult(
                    "phase_2_main", False, "Brak odpowiedzi z main",
                    {"phase": "building"},
                )
            building_data = Extractor.building_data(response)
            if not building_data:
                return DebugCycleResult(
                    "phase_2_main", False,
                    "Nie udało się sparsować building_data",
                    {"phase": "building", "html_size": len(response.text or "")},
                )
            buildings_available = list(building_data.keys())
            return DebugCycleResult(
                "phase_2_main", True,
                f"Pobrano koszty {len(building_data)} budynków",
                {
                    "phase": "building",
                    "buildings_available": buildings_available,
                    "sample_main_cost": building_data.get("main", {}),
                },
            )
        except Exception as e:
            return DebugCycleResult(
                "phase_2_main", False, f"Błąd: {e}", {"phase": "building"},
            )

    def phase_3_units(self) -> DebugCycleResult:
        """Faza 3: pobranie ekranu units (dostępne wojska)."""
        try:
            response = self.get_action(
                "place", mode="units", label="03_units",
            )
            if not response:
                return DebugCycleResult(
                    "phase_3_units", False, "Brak odpowiedzi z place&mode=units",
                    {"phase": "units"},
                )
            units_in_village = Extractor.units_in_village(response)
            units_in_total = Extractor.units_in_total(response)
            return DebugCycleResult(
                "phase_3_units", True,
                f"Pobrano {len(units_in_village)} typów wojsk (w wiosce) "
                f"i {len(units_in_total)} (sumarycznie)",
                {
                    "phase": "units",
                    "in_village": dict(units_in_village),
                    "in_total": dict(units_in_total),
                },
            )
        except Exception as e:
            return DebugCycleResult(
                "phase_3_units", False, f"Błąd: {e}", {"phase": "units"},
            )

    def phase_4_smith(self) -> DebugCycleResult:
        """Faza 4: pobranie ekranu smith (poziomy badań)."""
        try:
            response = self.get_action("smith", label="04_smith")
            if not response:
                return DebugCycleResult(
                    "phase_4_smith", False, "Brak odpowiedzi z smith",
                    {"phase": "smith"},
                )
            smith_data = Extractor.smith_data(response)
            if not smith_data:
                return DebugCycleResult(
                    "phase_4_smith", False,
                    "Nie udało się sparsować smith_data",
                    {"phase": "smith", "html_size": len(response.text or "")},
                )
            return DebugCycleResult(
                "phase_4_smith", True,
                f"Pobrano dane smith ({len(smith_data)} typów jednostek)",
                {
                    "phase": "smith",
                    "available_types": list(smith_data.keys()),
                },
            )
        except Exception as e:
            return DebugCycleResult(
                "phase_4_smith", False, f"Błąd: {e}", {"phase": "smith"},
            )

    def phase_5_recruit_data(self) -> DebugCycleResult:
        """Faza 5: pobranie ekranu train (dane rekrutacji)."""
        try:
            response = self.get_action("train", label="05_train")
            if not response:
                return DebugCycleResult(
                    "phase_5_recruit", False, "Brak odpowiedzi z train",
                    {"phase": "recruit"},
                )
            recruit_data = Extractor.recruit_data(response)
            game_state = Extractor.game_state(response)
            if not recruit_data:
                return DebugCycleResult(
                    "phase_5_recruit", False,
                    "Nie udało się sparsować recruit_data",
                    {"phase": "recruit", "html_size": len(response.text or "")},
                )
            return DebugCycleResult(
                "phase_5_recruit", True,
                f"Pobrano dane rekrutacji ({len(recruit_data)} typów)",
                {
                    "phase": "recruit",
                    "available_units": list(recruit_data.keys()),
                    "village_wood": game_state.get("village", {}).get("wood"),
                    "village_iron": game_state.get("village", {}).get("iron"),
                },
            )
        except Exception as e:
            return DebugCycleResult(
                "phase_5_recruit", False, f"Błąd: {e}", {"phase": "recruit"},
            )

    def phase_6_market(self) -> DebugCycleResult:
        """Faza 6: pobranie ekranu market."""
        try:
            response = self.get_action(
                "market", mode="own_offer", label="06_market",
            )
            if not response:
                return DebugCycleResult(
                    "phase_6_market", False, "Brak odpowiedzi z market",
                    {"phase": "market"},
                )
            return DebugCycleResult(
                "phase_6_market", True,
                f"Pobrano market ({len(response.text or '')} bajtów)",
                {
                    "phase": "market",
                    "html_size": len(response.text or ""),
                    "has_offers": "data-id=" in (response.text or ""),
                },
            )
        except Exception as e:
            return DebugCycleResult(
                "phase_6_market", False, f"Błąd: {e}", {"phase": "market"},
            )

    def phase_7_farm_assistant(self) -> DebugCycleResult:
        """Faza 7: pobranie ekranu am_farm (farm assistant)."""
        try:
            response = self.get_action("am_farm", label="07_am_farm")
            if not response:
                return DebugCycleResult(
                    "phase_7_farm", False, "Brak odpowiedzi z am_farm",
                    {"phase": "farm_assistant"},
                )
            targets = Extractor.farm_assistant_targets(response)
            templates = Extractor.farm_assistant_templates(response)
            pagination = Extractor.farm_assistant_pagination(response)
            return DebugCycleResult(
                "phase_7_farm", True,
                f"Znaleziono {len(targets)} celów farm, "
                f"{len(templates)} szablonów, {len(pagination)} dodatkowych stron",
                {
                    "phase": "farm_assistant",
                    "targets_count": len(targets),
                    "templates_count": len(templates),
                    "pagination_count": len(pagination),
                    "sample_target": next(iter(targets.values())) if targets else None,
                },
            )
        except Exception as e:
            return DebugCycleResult(
                "phase_7_farm", False, f"Błąd: {e}", {"phase": "farm_assistant"},
            )

    def phase_8_gather(self) -> DebugCycleResult:
        """Faza 8: pobranie ekranu scavenge (zbieractwo)."""
        try:
            response = self.get_action(
                "place", mode="scavenge", label="08_scavenge",
            )
            if not response:
                return DebugCycleResult(
                    "phase_8_gather", False, "Brak odpowiedzi z scavenge",
                    {"phase": "gather"},
                )
            village_data = Extractor.village_data(response)
            if not village_data:
                return DebugCycleResult(
                    "phase_8_gather", False,
                    "Nie udało się sparsować village_data",
                    {"phase": "gather", "html_size": len(response.text or "")},
                )
            options = village_data.get("options", {})
            return DebugCycleResult(
                "phase_8_gather", True,
                f"Pobrano {len(options)} opcji zbieractwa",
                {
                    "phase": "gather",
                    "options_count": len(options),
                    "options": {
                        k: {"locked": v.get("is_locked"),
                            "running": v.get("scavenging_squad") is not None}
                        for k, v in options.items()
                    },
                },
            )
        except Exception as e:
            return DebugCycleResult(
                "phase_8_gather", False, f"Błąd: {e}", {"phase": "gather"},
            )

    def phase_9_flags(self) -> DebugCycleResult:
        """Faza 9: sprawdzenie stanu flag."""
        try:
            response = self.get_action("flags", label="09_flags")
            if not response:
                return DebugCycleResult(
                    "phase_9_flags", False, "Brak odpowiedzi z flags",
                    {"phase": "flags"},
                )
            text = response.text or ""
            flags_info = {
                "has_flags_screen": "setFlagCounts" in text or "current_flag" in text,
                "html_size": len(text),
            }
            return DebugCycleResult(
                "phase_9_flags", True, "Pobrano ekran flag",
                {"phase": "flags", **flags_info},
            )
        except Exception as e:
            return DebugCycleResult(
                "phase_9_flags", False, f"Błąd: {e}", {"phase": "flags"},
            )

    # ------------------------------------------------------------------
    # Uruchomienie pełnego cyklu
    # ------------------------------------------------------------------
    def run(self, on_phase_done=None) -> Dict[str, Any]:
        """
        Przeprowadza pełen cykl diagnostyczny. Zwraca raport.

        :param on_phase_done: opcjonalny callback(label, result, progress_pct)
                             wywoływany po zakończeniu każdej fazy.
        """
        LOGGER.info("=" * 80)
        LOGGER.info("Rozpoczynam DEBUG CYCLE dla wioski %s", self.village_id)
        LOGGER.info("Tryb: %s", "DRY RUN" if self.dry_run else "LIVE")
        LOGGER.info("Katalog wyjściowy: %s", self.village_dir)
        LOGGER.info("=" * 80)
        self.start_time = datetime.utcnow().isoformat() + "Z"

        phases = [
            ("01_overview", self.phase_1_init_overview),
            ("02_main_screen", self.phase_2_main_screen),
            ("03_units", self.phase_3_units),
            ("04_smith", self.phase_4_smith),
            ("05_recruit_data", self.phase_5_recruit_data),
            ("06_market", self.phase_6_market),
            ("07_farm_assistant", self.phase_7_farm_assistant),
            ("08_gather", self.phase_8_gather),
            ("09_flags", self.phase_9_flags),
        ]

        total_phases = len(phases)
        for idx, (label, phase_fn) in enumerate(phases):
            LOGGER.info("--- Faza %d/%d: %s ---", idx + 1, total_phases, label)
            try:
                result = phase_fn()
            except Exception as e:
                LOGGER.exception("Wyjątek w fazie %s: %s", label, e)
                result = DebugCycleResult(
                    label, False, f"Nieobsłużony wyjątek: {e}",
                    {"phase": label, "exception": traceback.format_exc()},
                )
            self.results.append(result)
            status = "OK" if result.success else "FAIL"
            LOGGER.info("[%s] %s: %s", status, result.name, result.message)

            # Callback dla UI - aktualizacja postępu w czasie rzeczywistym
            if on_phase_done is not None:
                try:
                    progress_pct = int((idx + 1) * 100 / total_phases)
                    on_phase_done(label, result, progress_pct)
                except Exception as cb_err:
                    LOGGER.warning("Błąd callback on_phase_done: %s", cb_err)

            # Bardzo krótka pauza (delay został wyłączony w __init__)
            time.sleep(0.05)

        self.end_time = datetime.utcnow().isoformat() + "Z"
        report_path = self._save_final_report()

        # Podsumowanie
        total = len(self.results)
        ok = sum(1 for r in self.results if r.success)
        failed = total - ok
        LOGGER.info("=" * 80)
        LOGGER.info("DEBUG CYCLE zakończony")
        LOGGER.info("  Sukces: %d/%d", ok, total)
        LOGGER.info("  Porażka: %d/%d", failed, total)
        LOGGER.info("  Raport: %s", report_path)
        LOGGER.info("=" * 80)

        return {
            "village_id": self.village_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total": total,
            "ok": ok,
            "failed": failed,
            "results": [r.to_dict() for r in self.results],
            "report_path": report_path,
            "errors": self.errors,
        }


def run_debug_cycle_for_village(wrapper, village_id: str, config: Optional[Dict] = None,
                                  dry_run: bool = False,
                                  save_responses: bool = True) -> Dict[str, Any]:
    """Helper - uruchamia pełen cykl debug dla jednej wioski."""
    runner = DebugCycleRunner(
        wrapper=wrapper,
        village_id=village_id,
        config=config,
        dry_run=dry_run,
        save_responses=save_responses,
    )
    return runner.run()


def run_debug_cycle_for_all(wrapper, village_ids: List[str], config: Optional[Dict] = None,
                             dry_run: bool = False,
                             save_responses: bool = True) -> List[Dict[str, Any]]:
    """Helper - uruchamia cykl debug dla listy wiosek."""
    all_reports = []
    for vid in village_ids:
        LOGGER.info("=" * 80)
        LOGGER.info("Przetwarzam wioskę %s (%d/%d)", vid, village_ids.index(vid) + 1, len(village_ids))
        try:
            report = run_debug_cycle_for_village(
                wrapper=wrapper,
                village_id=str(vid),
                config=(config or {}).get("villages", {}).get(str(vid), {}),
                dry_run=dry_run,
                save_responses=save_responses,
            )
            all_reports.append(report)
        except Exception as e:
            LOGGER.exception("Błąd cyklu dla wioski %s: %s", vid, e)
            all_reports.append({
                "village_id": str(vid),
                "error": str(e),
                "traceback": traceback.format_exc(),
            })
        time.sleep(1.0)  # pauza między wioskami
    return all_reports


if __name__ == "__main__":
    # Uruchomienie z linii komend - wymaga istniejącej sesji w cache/session.json
    import argparse
    parser = argparse.ArgumentParser(description="TWB Debug Cycle")
    parser.add_argument("--village", help="ID wioski (domyślnie: wszystkie z config.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Nie wysyłaj prawdziwych POSTów")
    parser.add_argument("--no-save", action="store_true",
                        help="Nie zapisuj odpowiedzi HTTP do cache/debugcycle")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - [%(levelname)s] [%(name)s] - %(message)s",
    )

    # Załaduj config
    config = FileManager.load_json_file("config.json") or {}
    if not config:
        # Spróbuj example
        config = FileManager.load_json_file("config.example.json") or {}

    # Pobierz listę wiosek
    if args.village:
        village_ids = [args.village]
    else:
        village_ids = list((config.get("villages") or {}).keys())

    if not village_ids:
        LOGGER.error("Brak wiosek w config.json. Użyj --village <id> lub dodaj wioski do konfiguracji.")
        sys.exit(1)

    # Załaduj sesję z cache
    session_data = FileManager.load_json_file("cache/session.json")
    if not session_data or not session_data.get("endpoint"):
        LOGGER.error("Brak aktywnej sesji. Uruchom najpierw bota, aby zapisał sesję.")
        sys.exit(1)

    # Utwórz wrapper
    from core.request import WebWrapper
    wrapper = WebWrapper(
        url=session_data.get("endpoint"),
        server=session_data.get("server"),
        endpoint=session_data.get("endpoint"),
        reporter_enabled=False,
        reporter_constr=None,
    )
    if session_data.get("cookies"):
        try:
            wrapper.web.cookies.update(session_data["cookies"])
            LOGGER.info("Załadowano %d ciasteczek sesji", len(session_data["cookies"]))
        except Exception as e:
            LOGGER.warning("Błąd ładowania ciasteczek: %s", e)

    # Uruchom cykl
    reports = run_debug_cycle_for_all(
        wrapper=wrapper,
        village_ids=village_ids,
        config=config,
        dry_run=args.dry_run,
        save_responses=not args.no_save,
    )

    # Podsumowanie końcowe
    LOGGER.info("=" * 80)
    LOGGER.info("PODSUMOWANIE WSZYSTKICH WIOSEK")
    for r in reports:
        if "error" in r:
            LOGGER.error("  Wioska %s: BŁĄD: %s", r["village_id"], r["error"])
        else:
            LOGGER.info(
                "  Wioska %s: %d/%d OK, raport=%s",
                r["village_id"], r["ok"], r["total"], r.get("report_path"),
            )
    LOGGER.info("=" * 80)
    sys.exit(0)