"""
Testy jednostkowe dla core/extractors.py

Walidują poprawność ekstrakcji danych gry z response HTML/JSON:
- game_state (TribalWars.updateGameData) z ekranu overview i main
- village_data
- building_data
- recruit_data
- smith_data
- units_in_village / units_in_total
- attack_form
- village_ids_from_overview
- get_quests, get_quest_rewards
- get_daily_reward (bezpieczne zachowanie przy braku dopasowania)
- map_data
- premium_data
- active_building_queue, active_recruit_queue

Testy nie wymagają uruchomionego bota — operują na syntetycznych response'ach.
"""

import json
import sys
import unittest
from unittest.mock import MagicMock

# Pozwól na import modułów TWB
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.extractors import Extractor


def make_response(text):
    """Tworzy obiekt udający requests.Response z .text"""
    r = MagicMock()
    r.text = text
    return r


# ---------------------------------------------------------------------------
# Symulowane fragmenty stron (jakie faktycznie zwraca serwer TW)
# ---------------------------------------------------------------------------

SAMPLE_OVERVIEW_GAMEDATA = json.dumps({
    "player": {"id": 123, "name": "Stefan", "ally_id": 0},
    "village": {
        "id": 456,
        "name": "Warsaw 01",
        "wood": 12345,
        "stone": 23456,
        "iron": 34567,
        "pop": 123,
        "pop_max": 240,
        "storage_max": 50000,
        "buildings": {
            "main": 5, "barracks": 3, "stable": 2, "garage": 1,
            "snob": 0, "market": 4, "wood": 8, "stone": 8, "iron": 8,
            "farm": 6, "storage": 7, "wall": 5,
        },
        "x": 500,
        "y": 500,
        "coord": "500|500",
    },
    "world": {"speed": 1.0, "unit_speed": 1.0},
})

SAMPLE_OVERVIEW_HTML = (
    '<html><head></head><body>'
    '<script>TribalWars.updateGameData('
    + SAMPLE_OVERVIEW_GAMEDATA
    + ');</script>'
    '</body></html>'
)


# ---------------------------------------------------------------------------
# Testy game_state
# ---------------------------------------------------------------------------

class TestGameStateExtractor(unittest.TestCase):
    """game_state — najczęściej wywoływany ekstraktor"""

    def test_game_state_from_overview_extracts_village_resources(self):
        """Ekstrakcja surowców i pojemności magazynu z ekranu overview."""
        result = Extractor.game_state(make_response(SAMPLE_OVERVIEW_HTML))
        self.assertIsNotNone(result)
        self.assertIn("village", result)
        village = result["village"]
        self.assertEqual(village["wood"], 12345)
        self.assertEqual(village["stone"], 23456)
        self.assertEqual(village["iron"], 34567)
        self.assertEqual(village["pop"], 123)
        self.assertEqual(village["pop_max"], 240)
        self.assertEqual(village["storage_max"], 50000)

    def test_game_state_from_overview_extracts_buildings(self):
        """Ekstrakcja poziomów budynków z ekranu overview."""
        result = Extractor.game_state(make_response(SAMPLE_OVERVIEW_HTML))
        buildings = result["village"]["buildings"]
        self.assertEqual(buildings["main"], 5)
        self.assertEqual(buildings["barracks"], 3)
        self.assertEqual(buildings["stable"], 2)
        self.assertEqual(buildings["snob"], 0)
        self.assertEqual(buildings["storage"], 7)
        self.assertEqual(buildings["wall"], 5)

    def test_game_state_extracts_player_id(self):
        """Ekstrakcja player.id potrzebna do rozróżniania własnych wiosek."""
        result = Extractor.game_state(make_response(SAMPLE_OVERVIEW_HTML))
        self.assertEqual(result["player"]["id"], 123)

    def test_game_state_handles_parens_inside_string(self):
        """Regex nie może się zatrzymać na ')' wewnątrz stringu JSON."""
        weird_html = (
            '<script>TribalWars.updateGameData({'
            '"player": {"id": 1, "name": "test)with(parens"},'
            '"village": {"id": 2, "name": "v"}'
            '});</script>'
        )
        result = Extractor.game_state(make_response(weird_html))
        self.assertIsNotNone(result)
        self.assertEqual(result["player"]["name"], "test)with(parens")

    def test_game_state_handles_newlines_in_json(self):
        """DOTALL — multiline JSON powinien być akceptowany."""
        multiline = (
            '<script>TribalWars.updateGameData({\n'
            '"village": {"id": 99, "name": "multi"},\n'
            '"player": {"id": 1}\n'
            '});</script>'
        )
        result = Extractor.game_state(make_response(multiline))
        self.assertIsNotNone(result)
        self.assertEqual(result["village"]["id"], 99)

    def test_game_state_returns_none_when_missing(self):
        """Brak skryptu updateGameData → None zamiast crash."""
        result = Extractor.game_state(make_response("<html>No TW here</html>"))
        self.assertIsNone(result)

    def test_game_state_accepts_plain_string(self):
        """Extractor powinien akceptować zarówno Response jak i surowy string."""
        result = Extractor.game_state(SAMPLE_OVERVIEW_HTML)
        self.assertIsNotNone(result)
        self.assertEqual(result["village"]["name"], "Warsaw 01")

    def test_game_state_handles_empty_input(self):
        """Pusty string nie powinien crashować."""
        self.assertIsNone(Extractor.game_state(""))
        self.assertIsNone(Extractor.game_state(None))


# ---------------------------------------------------------------------------
# Testy building_data (ekran main)
# ---------------------------------------------------------------------------

class TestBuildingDataExtractor(unittest.TestCase):

    def test_building_data_extracts_from_main_screen(self):
        sample = (
            '<html><script>BuildingMain.buildings = '
            '{"main": {"can_build": true, "wood": 100, "stone": 100, '
            '"iron": 100, "pop": 5, "build_time": 3600},'
            '"barracks": {"can_build": false}};'
            '</script></html>'
        )
        result = Extractor.building_data(make_response(sample))
        self.assertIsNotNone(result)
        self.assertIn("main", result)
        self.assertEqual(result["main"]["wood"], 100)
        self.assertFalse(result["barracks"]["can_build"])

    def test_building_data_returns_none_when_missing(self):
        result = Extractor.building_data(make_response("<html></html>"))
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Testy recruit_data (ekrany barracks/stable/garage)
# ---------------------------------------------------------------------------

class TestRecruitDataExtractor(unittest.TestCase):

    def test_recruit_data_extracts_units(self):
        sample = (
            '<script>unit_managers.units = '
            '{spear: {wood: 50, stone: 30, iron: 20, pop: 1, '
            '"build_time": 840, "requirements_met": true},'
            'sword: {wood: 30, stone: 30, iron: 70, pop: 1, '
            '"build_time": 1200, "requirements_met": true}'
            '};'
            '</script>'
        )
        result = Extractor.recruit_data(make_response(sample))
        self.assertIsNotNone(result)
        self.assertIn("spear", result)
        self.assertEqual(result["spear"]["wood"], 50)
        self.assertEqual(result["sword"]["iron"], 70)

    def test_recruit_data_returns_none_when_missing(self):
        self.assertIsNone(Extractor.recruit_data(make_response("<html></html>")))


# ---------------------------------------------------------------------------
# Testy smith_data (ekran smith — kuźnia)
# ---------------------------------------------------------------------------

class TestSmithDataExtractor(unittest.TestCase):

    def test_smith_data_extracts_techs(self):
        sample = (
            '<script>BuildingSmith.techs = '
            '{spear: {level: 5, "can_research": true, "research_time": "00:14:00"},'
            'sword: {level: 3, "can_research": true}'
            '};'
            '</script>'
        )
        result = Extractor.smith_data(make_response(sample))
        self.assertIsNotNone(result)
        self.assertEqual(result["spear"]["level"], 5)
        self.assertEqual(result["spear"]["research_time"], "00:14:00")

    def test_smith_data_returns_none_when_missing(self):
        self.assertIsNone(Extractor.smith_data(make_response("<html></html>")))


# ---------------------------------------------------------------------------
# Testy units_in_village i units_in_total
# ---------------------------------------------------------------------------

class TestUnitsExtractor(unittest.TestCase):
    """
    Sprawdza odczyt wojsk z ekranu place?mode=units&display=units
    """

    SAMPLE_UNITS_HTML = (
        '<table id="units_home">'
        '<tr><th>Row 1 (ignored)</th></tr>'
        '<tr>'
        '<td class="unit-item unit-item-spear">100</td>'
        '<td class="unit-item unit-item-sword">50</td>'
        '<td class="unit-item unit-item-axe">25</td>'
        '<td class="unit-item unit-item-spy">10</td>'
        '<td class="unit-item unit-item-light">5</td>'
        '<td class="unit-item unit-item-heavy">0</td>'
        '<td class="unit-item unit-item-ram">2</td>'
        '<td class="unit-item unit-item-catapult">1</td>'
        '<td class="unit-item unit-item-snob">0</td>'
        '</tr>'
        '</table>'
    )

    def test_units_in_village_extracts_all_units(self):
        result = Extractor.units_in_village(make_response(self.SAMPLE_UNITS_HTML))
        # dict -> list of (name, qty) tuples
        as_dict = dict(result)
        self.assertEqual(int(as_dict["spear"]), 100)
        self.assertEqual(int(as_dict["sword"]), 50)
        self.assertEqual(int(as_dict["axe"]), 25)
        self.assertEqual(int(as_dict["spy"]), 10)
        self.assertEqual(int(as_dict["light"]), 5)
        # Jednostki z 0 są odfiltrowywane
        self.assertNotIn("heavy", as_dict)
        self.assertNotIn("snob", as_dict)

    def test_units_in_village_returns_empty_when_no_table(self):
        result = Extractor.units_in_village(make_response("<html></html>"))
        self.assertEqual(result, [])

    def test_units_in_total_extracts_units(self):
        result = Extractor.units_in_total(make_response(self.SAMPLE_UNITS_HTML))
        as_dict = dict(result)
        self.assertEqual(int(as_dict["spear"]), 100)
        self.assertEqual(int(as_dict["sword"]), 50)


# ---------------------------------------------------------------------------
# Testy attack_form (place screen)
# ---------------------------------------------------------------------------

class TestAttackFormExtractor(unittest.TestCase):

    def test_attack_form_extracts_inputs(self):
        html = (
            '<form>'
            '<input type="text" name="spear" value="100">'
            '<input type="text" name="sword" value="50">'
            '<input type="hidden" name="h" value="abc123">'
            '</form>'
        )
        result = Extractor.attack_form(make_response(html))
        as_dict = dict(result)
        self.assertEqual(as_dict["spear"], "100")
        self.assertEqual(as_dict["sword"], "50")
        self.assertEqual(as_dict["h"], "abc123")

    def test_attack_form_returns_empty_when_no_form(self):
        self.assertEqual(Extractor.attack_form(make_response("<html></html>")), [])


# ---------------------------------------------------------------------------
# Testy village_ids_from_overview
# ---------------------------------------------------------------------------

class TestVillageIdsExtractor(unittest.TestCase):

    def test_village_ids_from_overview(self):
        html = (
            '<span class="quickedit-vn" data-id="111"></span>'
            '<span class="quickedit-vn" data-id="222"></span>'
            '<span class="quickedit-vn" data-id="333"></span>'
        )
        result = Extractor.village_ids_from_overview(make_response(html))
        self.assertEqual(set(result), {"111", "222", "333"})

    def test_village_ids_empty(self):
        self.assertEqual(Extractor.village_ids_from_overview(
            make_response("<html></html>")), [])


# ---------------------------------------------------------------------------
# Testy get_quests / get_quest_rewards
# ---------------------------------------------------------------------------

class TestQuestsExtractor(unittest.TestCase):

    def test_get_quests_finds_completed(self):
        html = (
            '<script>Quests.setQuestData({'
            '"q1": {"goals_completed": 3, "goals_total": 3},'
            '"q2": {"goals_completed": 1, "goals_total": 5}'
            '});</script>'
        )
        self.assertEqual(Extractor.get_quests(make_response(html)), "q1")

    def test_get_quests_returns_none_when_no_completed(self):
        html = (
            '<script>Quests.setQuestData({'
            '"q1": {"goals_completed": 1, "goals_total": 3}'
            '});</script>'
        )
        self.assertIsNone(Extractor.get_quests(make_response(html)))

    def test_get_quests_returns_none_when_no_data(self):
        self.assertIsNone(Extractor.get_quests(make_response("<html></html>")))

    def test_get_quest_rewards_extracts_unlocked(self):
        html = (
            '<script>RewardSystem.setRewards(['
            '{"id": 1, "status": "unlocked", "reward": {}},'
            '{"id": 2, "status": "locked", "reward": {}}'
            '],</script>'
        )
        result = Extractor.get_quest_rewards(make_response(html))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 1)


# ---------------------------------------------------------------------------
# Testy get_daily_reward (bezpieczne przy braku dopasowania)
# ---------------------------------------------------------------------------

class TestDailyRewardExtractor(unittest.TestCase):

    def test_get_daily_reward_returns_none_when_missing(self):
        """Brak dopasowania regex nie może powodować AttributeError."""
        result = Extractor.get_daily_reward(make_response("<html></html>"))
        self.assertIsNone(result)

    def test_get_daily_reward_returns_none_on_empty(self):
        self.assertIsNone(Extractor.get_daily_reward(make_response("")))


# ---------------------------------------------------------------------------
# Testy map_data i premium_data
# ---------------------------------------------------------------------------

class TestMapAndPremiumExtractor(unittest.TestCase):

    def test_map_data_extracts_sectors(self):
        html = (
            '<script>TWMap.sectorPrefech = ['
            '{"data": {"x": 500, "y": 500, "villages": {}}},'
            '{"data": {"x": 501, "y": 500, "villages": {}}}'
            ']);</script>'
        )
        result = Extractor.map_data(make_response(html))
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)

    def test_map_data_returns_none_when_missing(self):
        self.assertIsNone(Extractor.map_data(make_response("<html></html>")))

    def test_premium_data_extracts(self):
        html = (
            '<script>PremiumExchange.receiveData({"stock": {}, "capacity": {},'
            '"tax": {}, "constants": {}, "duration": 1, "merchants": 5});</script>'
        )
        result = Extractor.premium_data(make_response(html))
        self.assertIsNotNone(result)
        self.assertEqual(result["merchants"], 5)


# ---------------------------------------------------------------------------
# Testy active_building_queue i active_recruit_queue
# ---------------------------------------------------------------------------

class TestQueueExtractor(unittest.TestCase):

    def test_active_building_queue_counts(self):
        html = (
            '<table id="build_queue">'
            '<tr><td><a class="btn btn-cancel">x</a></td></tr>'
            '<tr><td><a class="btn btn-cancel">x</a></td></tr>'
            '<tr><td>no cancel</td></tr>'
            '</table>'
        )
        self.assertEqual(
            Extractor.active_building_queue(make_response(html)), 2)

    def test_active_building_queue_no_table(self):
        self.assertEqual(
            Extractor.active_building_queue(make_response("<html></html>")), 0)

    def test_active_recruit_queue_extracts_ids(self):
        html = (
            '<a href="#" onclick="TrainOverview.cancelOrder(11)">x</a>'
            '<a href="#" onclick="TrainOverview.cancelOrder(22)">x</a>'
        )
        result = Extractor.active_recruit_queue(make_response(html))
        self.assertEqual(result, ["11", "22"])


# ---------------------------------------------------------------------------
# Testy attack_duration i report_table
# ---------------------------------------------------------------------------

class TestMiscExtractor(unittest.TestCase):

    def test_attack_duration(self):
        html = (
            '<span class="relative_time" data-duration="3600">x</span>'
        )
        self.assertEqual(
            Extractor.attack_duration(make_response(html)), 3600)

    def test_attack_duration_missing(self):
        self.assertEqual(
            Extractor.attack_duration(make_response("<html></html>")), 0)

    def test_report_table_extracts_ids(self):
        html = (
            '<a class="report-link" data-id="100">x</a>'
            '<a class="report-link" data-id="200">x</a>'
        )
        result = Extractor.report_table(make_response(html))
        self.assertEqual(result, ["100", "200"])

    def test_farm_assistant_loot_limit(self):
        html = (
            '<div>Zrabowane surowce:</strong> '
            '<span>1500</span>/<span>10000</span>.</div>'
        )
        result = Extractor.farm_assistant_loot_limit(make_response(html))
        self.assertEqual(result, {"current": 1500, "limit": 10000})


# ---------------------------------------------------------------------------
# Test scenariusza end-to-end (bez realnego HTTP)
# ---------------------------------------------------------------------------

class TestEndToEndVillageExtraction(unittest.TestCase):
    """
    Symuluje pełny cykl odczytu stanu wioski z ekranu overview.
    Weryfikuje, że wszystkie pola potrzebne do dalszych obliczeń (resources,
    population, buildings) są prawidłowo odczytywane.
    """

    def test_population_calculations(self):
        """Wyliczanie dostępnej populacji (pop_max - pop)."""
        result = Extractor.game_state(make_response(SAMPLE_OVERVIEW_HTML))
        village = result["village"]
        free_pop = village["pop_max"] - village["pop"]
        self.assertEqual(free_pop, 117)

    def test_storage_capacity_for_resources(self):
        """Pojemność magazynu powinna być dostępna."""
        result = Extractor.game_state(make_response(SAMPLE_OVERVIEW_HTML))
        self.assertEqual(result["village"]["storage_max"], 50000)

    def test_all_resources_present(self):
        """Wszystkie trzy surowce muszą być dostępne (wood/stone/iron)."""
        result = Extractor.game_state(make_response(SAMPLE_OVERVIEW_HTML))
        for r in ("wood", "stone", "iron"):
            self.assertIn(r, result["village"])
            self.assertIsInstance(result["village"][r], int)
            self.assertGreaterEqual(result["village"][r], 0)

    def test_all_buildings_present(self):
        """Budynki powinny być dostępne z prawidłowymi poziomami."""
        result = Extractor.game_state(make_response(SAMPLE_OVERVIEW_HTML))
        buildings = result["village"]["buildings"]
        # Co najmniej podstawowe budynki powinny być dostępne
        for b in ("main", "barracks", "stable", "farm"):
            self.assertIn(b, buildings)
            self.assertIsInstance(buildings[b], int)


if __name__ == "__main__":
    unittest.main(verbosity=2)