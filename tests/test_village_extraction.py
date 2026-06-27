"""
Testy jednostkowe dla game/village.py — walidują poprawność pobierania
stanu gry (zasoby, populacja, budynki) z prawidłowym zabezpieczeniem
przed błędami Extraction.

Nie wymagają uruchomionego bota — mockujemy WebWrapper.
"""

import sys
import unittest
from unittest.mock import MagicMock

import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.extractors import Extractor
from game.village import Village


OVERVIEW_GAMEDATA = (
    '{"player": {"id": 1, "name": "Test"},'
    '"village": {'
    '"id": "100", "name": "Test Village",'
    '"wood": 1000, "stone": 2000, "iron": 3000,'
    '"pop": 50, "pop_max": 200, "storage_max": 50000,'
    '"buildings": {"main": 3, "barracks": 1, "farm": 2,'
    '"stable": 0, "garage": 0, "snob": 0, "market": 1},'
    '"x": 500, "y": 500'
    '}}'
)

MAIN_GAMEDATA = (
    '{"player": {"id": 1},'
    '"village": {"id": "100", "name": "Test Village",'
    '"buildings": {"main": 3, "barracks": 1, "farm": 2}}}'
)

VALID_OVERVIEW_HTML = (
    '<html><script>TribalWars.updateGameData(' + OVERVIEW_GAMEDATA + ');</script></html>'
)

INVALID_OVERVIEW_HTML = '<html>No game data here</html>'


def make_wrapper(text):
    """Tworzy obiekt WebWrapper z mockowaną odpowiedzią."""
    wrapper = MagicMock()
    response = MagicMock()
    response.text = text
    response.status_code = 200
    wrapper.get_url.return_value = response
    wrapper.get_action.return_value = response
    return wrapper


class TestVillageInit(unittest.TestCase):
    """Village.village_init() — inicjalizacja z prawidłowym zabezpieczeniem."""

    def test_village_init_with_known_id_extracts_resources(self):
        v = Village(village_id="100", wrapper=make_wrapper(VALID_OVERVIEW_HTML))
        v.config = {"villages": {}, "world": {}, "bot": {}, "units": {}}
        v.logger = MagicMock()
        data = v.village_init()
        self.assertIsNotNone(v.game_data)
        self.assertEqual(v.game_data["village"]["wood"], 1000)
        self.assertEqual(v.game_data["village"]["stone"], 2000)
        self.assertEqual(v.game_data["village"]["iron"], 3000)
        self.assertEqual(v.game_data["village"]["pop"], 50)
        self.assertEqual(v.game_data["village"]["pop_max"], 200)
        self.assertEqual(v.game_data["village"]["storage_max"], 50000)

    def test_village_init_with_known_id_extracts_buildings(self):
        v = Village(village_id="100", wrapper=make_wrapper(VALID_OVERVIEW_HTML))
        v.config = {"villages": {}, "world": {}, "bot": {}, "units": {}}
        v.logger = MagicMock()
        v.village_init()
        b = v.game_data["village"]["buildings"]
        self.assertEqual(b["main"], 3)
        self.assertEqual(b["barracks"], 1)
        self.assertEqual(b["farm"], 2)

    def test_village_init_with_unknown_id_falls_back_to_overview_intro(self):
        """Gdy village_id jest None, fetchujemy /overview&intro."""
        v = Village(village_id=None, wrapper=make_wrapper(VALID_OVERVIEW_HTML))
        v.logger = MagicMock()
        v.village_init()
        # Sprawdź, że village_id został pobrany z game_data
        self.assertEqual(v.village_id, "100")

    def test_village_init_does_not_crash_on_invalid_response(self):
        """Brak danych gry w odpowiedzi — nie może powodować KeyError."""
        v = Village(village_id="100", wrapper=make_wrapper(INVALID_OVERVIEW_HTML))
        v.config = {"villages": {}, "world": {}, "bot": {}, "units": {}}
        v.logger = MagicMock()
        # Przed naprawą: KeyError 'village'
        # Po naprawie: graceful — game_data = None, bez crash
        try:
            v.village_init()
        except (KeyError, TypeError) as e:
            self.fail(f"village_init crashed on invalid response: {e}")
        # game_data może być None — nie powinno crashować
        # (run() sprawdza to zanim użyje)

    def test_village_init_handles_empty_response(self):
        """Pusta odpowiedź nie może powodować crash."""
        v = Village(village_id="100", wrapper=make_wrapper(""))
        v.config = {"villages": {}, "world": {}, "bot": {}, "units": {}}
        v.logger = MagicMock()
        try:
            v.village_init()
        except (KeyError, TypeError, AttributeError) as e:
            self.fail(f"village_init crashed on empty response: {e}")


class TestVillageInitSafetyVsVillageSetName(unittest.TestCase):
    """Sprawdza, że village_set_name nie powoduje KeyError gdy brak game_data."""

    def test_village_set_name_does_not_crash_on_no_gamedata(self):
        v = Village(village_id="100", wrapper=make_wrapper(INVALID_OVERVIEW_HTML))
        v.config = {"villages": {}, "world": {}, "bot": {}, "units": {}}
        v.logger = MagicMock()
        v.village_set_name = "New Name"
        try:
            v.village_init()
        except (KeyError, TypeError, AttributeError) as e:
            self.fail(f"village_set_name check crashed on invalid response: {e}")


class TestResourceManagerUpdate(unittest.TestCase):
    """ResourceManager.update() — poprawność wyliczania surowców i populacji."""

    def test_update_extracts_resources(self):
        from game.resources import ResourceManager
        rm = ResourceManager(wrapper=MagicMock(), village_id="100")
        rm.update({
            "village": {
                "wood": 1000, "stone": 2000, "iron": 3000,
                "pop": 50, "pop_max": 200, "storage_max": 50000,
                "name": "Test",
            }
        })
        self.assertEqual(rm.actual["wood"], 1000)
        self.assertEqual(rm.actual["stone"], 2000)
        self.assertEqual(rm.actual["iron"], 3000)
        # POPRAWIONE: pop = pop_max - pop (dostępne miejsce)
        self.assertEqual(rm.actual["pop"], 150)
        self.assertEqual(rm.storage, 50000)

    def test_update_handles_missing_fields(self):
        from game.resources import ResourceManager
        rm = ResourceManager(wrapper=MagicMock(), village_id="100")
        # Brak niektórych pól — powinno użyć .get() z default
        try:
            rm.update({
                "village": {
                    "wood": 100,
                    # brak stone, iron, pop, pop_max, storage_max
                }
            })
        except (KeyError, TypeError) as e:
            self.fail(f"ResourceManager.update crashed on missing fields: {e}")

    def test_update_pop_calculation_is_differential(self):
        """
        POPRAWIONE: rm.actual["pop"] oznacza WOLNĄ populację (pop_max - pop),
        a nie aktualną populację. To jest kluczowe dla planowania rekrutacji.
        """
        from game.resources import ResourceManager
        rm = ResourceManager(wrapper=MagicMock(), village_id="100")
        rm.update({
            "village": {
                "wood": 0, "stone": 0, "iron": 0,
                "pop": 100, "pop_max": 200, "storage_max": 1000,
                "name": "x",
            }
        })
        # wolna populacja = 200 - 100 = 100
        self.assertEqual(rm.actual["pop"], 100)
        # pełna wioska
        rm.update({
            "village": {
                "wood": 0, "stone": 0, "iron": 0,
                "pop": 200, "pop_max": 200, "storage_max": 1000,
                "name": "x",
            }
        })
        self.assertEqual(rm.actual["pop"], 0)


class TestPopulationExtraction(unittest.TestCase):
    """
    Sprawdza, że bot poprawnie pobiera populację (ilość miejsca w zagrodzie).

    To kluczowe dla:
    - can_recruit() - czy jest miejsce na nowe wojska
    - set_unit_wanted_levels() - czy jednostki się zmieszczą
    - buildingmanager.has_enough() - czy budowa się zmieści
    """

    def test_pop_max_minus_pop_in_overview(self):
        """Sprawdź, czy overview daje pop_max i pop."""
        result = Extractor.game_state(make_wrapper(VALID_OVERVIEW_HTML).get_url(""))
        # Jeśli Extraction zadziała, oba pola powinny być obecne
        self.assertIn("pop_max", result["village"])
        self.assertIn("pop", result["village"])

    def test_storage_max_in_overview(self):
        """Pojemność magazynu dostępna w overview."""
        result = Extractor.game_state(make_wrapper(VALID_OVERVIEW_HTML).get_url(""))
        self.assertEqual(result["village"]["storage_max"], 50000)


if __name__ == "__main__":
    unittest.main(verbosity=2)