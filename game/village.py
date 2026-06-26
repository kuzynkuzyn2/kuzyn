import json
import logging
import time
from codecs import decode
from datetime import datetime

from core.extractors import Extractor
from core.filemanager import FileManager
from core.templates import TemplateManager
from core.twstats import TwStats
from game.attack import AttackManager
from game.buildingmanager import BuildingManager
from game.defence_manager import DefenceManager
from game.map import Map
from game.reports import ReportManager
from game.resources import ResourceManager
from game.snobber import SnobManager
from game.troopmanager import TroopManager
from core.exceptions import *


class Village:
    village_id = None
    builder = None
    units = None
    wrapper = None
    resources = {}
    game_data = {}
    logger = None
    force_troops = False
    area = None
    snobman = None
    attack = None
    resman = None
    def_man = None
    config = None
    forced_peace_today = False
    village_set_name = None
    last_attack = None
    build_config = None
    current_unit_entry = None
    forced_peace = False
    forced_peace_today_start = None
    disabled_units = []

    twp = TwStats()

    def __init__(self, village_id=None, wrapper=None):
        self.village_id = village_id
        self.wrapper = wrapper

    def get_config(self, section, parameter, default=None):
        if section not in self.config:
            self.logger.warning("Sekcja konfiguracji %s nie istnieje!" % section)
            return default
        if parameter not in self.config[section]:
            self.logger.warning(
                "Parametr konfiguracji %s:%s nie istnieje!" % (section, parameter)
            )
            return default
        return self.config[section][parameter]

    def get_village_config(self, village_id, parameter, default=None):
        if village_id not in self.config["villages"]:
            return default
        vdata = self.config["villages"][village_id]
        if parameter not in vdata:
            if parameter == "managed":
                return True
            self.logger.warning(
                "Parametr konfiguracji wsi %s: %s nie istnieje!",
                village_id, parameter
            )
            return default
        return vdata[parameter]

    def village_init(self):
        """
        Inicjuj wpis wsi i wyślij pierwsze żądanie
        """
        if not self.village_id:
            data = self.wrapper.get_url("game.php?screen=overview&intro")
            if data:
                self.game_data = Extractor.game_state(data)
            if self.game_data:
                self.village_id = str(self.game_data["village"]["id"])
                self.logger = logging.getLogger(
                    "Village %s" % self.game_data["village"]["name"]
                )
                self.logger.info("Odczytano stan gry dla wsi")
        else:
            self.logger = logging.getLogger("Village %s" % self.village_id)
            self.logger.info("Pobieram informacje o wiosce %s przed wykonaniem cyklu", self.village_id)
            data = self.wrapper.get_url(
                f"game.php?village={self.village_id}&screen=overview"
            )
            if data:
                self.game_data = Extractor.game_state(data)
                if self.game_data:
                    self.logger = logging.getLogger(
                        "Village %s" % self.game_data["village"]["name"]
                    )
                    self.logger.info("Odczytano stan gry dla wsi")
                    self.logger.info("Pobrano dane wioski %s przed przetwarzaniem", self.game_data["village"]["name"])
                    self.wrapper.reporter.report(
                        self.village_id,
                        "TWB_START",
                        "Rozpoczęcie przebiegu dla wsi: %s" % self.game_data["village"]["name"],
                    )
        if (
                self.village_set_name
                and self.game_data["village"]["name"] != self.village_set_name
        ):
            self.logger.name = f"Village {self.village_set_name}"
        return data

    def set_world_config(self):
        """
        Ustaw podstawowe opcje świata
        """
        self.disabled_units = []
        if not self.get_config(
                section="world", parameter="archers_enabled", default=True
        ):
            self.disabled_units.extend(["archer", "marcher"])

        if not self.get_config(
                section="world", parameter="building_destruction_enabled", default=True
        ):
            self.disabled_units.extend(["ram", "catapult"])

        if self.get_config(
                section="server", parameter="server_on_twstats", default=False
        ):
            self.twp.run(world=self.get_config(section="server", parameter="server"))

    def update_pre_run(self):
        """
        Zarządzaj obroną, zasobami i raportami
        """
        if not self.resman:
            self.resman = ResourceManager(
                wrapper=self.wrapper, village_id=self.village_id
            )

        self.resman.update(self.game_data)
        self.wrapper.reporter.report(
            self.village_id, "TWB_PRE_RESOURCE", str(self.resman.actual)
        )

        if not self.def_man:
            self.def_man = DefenceManager(
                wrapper=self.wrapper, village_id=self.village_id
            )
            self.def_man.map = self.area

        if not self.def_man.units and self.units:
            self.def_man.units = self.units

    def setup_defence_manager(self, data):
        """
        Konfiguruje menedżera obrony
        """
        self.def_man.manage_flags_enabled = self.get_config(
            section="world", parameter="flags_enabled", default=False
        )
        self.def_man.support_factor = self.get_village_config(
            self.village_id, "support_others_factor", default=0.25
        )

        self.def_man.allow_support_send = self.get_village_config(
            self.village_id, parameter="support_others", default=False
        )
        self.def_man.allow_support_recv = self.get_village_config(
            self.village_id, parameter="request_support_on_attack", default=False
        )
        self.def_man.auto_evacuate = self.get_village_config(
            self.village_id, parameter="evacuate_fragile_units_on_attack", default=False
        )
        self.def_man.update(
            data.text,
            with_defence=self.get_config(
                section="units", parameter="manage_defence", default=False
            ),
        )
        if self.def_man.under_attack and not self.last_attack:
            self.logger.warning("Wieś pod atakiem!")
            self.wrapper.reporter.report(
                self.village_id,
                "TWB_ATTACK",
                "Wieś: %s pod atakiem" % self.game_data["village"]["name"],
            )
        self.last_attack = self.def_man.under_attack

    def run_quest_actions(self, config):
        if self.get_config(section="world", parameter="quests_enabled", default=False):
            if self.get_quests():
                self.logger.info("Były ukończone zadania, ponowne uruchomienie funkcji")
                self.wrapper.reporter.report(
                    self.village_id, "TWB_QUEST", "Ukończono zadanie"
                )
                return self.run(config=config)

            if self.get_quest_rewards():
                self.wrapper.reporter.report(
                    self.village_id, "TWB_QUEST", " Zebrano nagrody za zadania"
                )

    def units_get_template(self):
        """
        Pobiera szablon jednostek
        """
        if not self.units:
            self.units = TroopManager(wrapper=self.wrapper, village_id=self.village_id)
            self.units.resman = self.resman
        batch_size_default = self.get_config(
            section="units", parameter="batch_size", default=25
        )
        self.units.max_batch_size = {
            "barracks": self.get_config(
                section="units", parameter="batch_size_barracks", default=batch_size_default
            ),
            "stable": self.get_config(
                section="units", parameter="batch_size_stable", default=batch_size_default
            ),
            "garage": self.get_config(
                section="units", parameter="batch_size_workshop", default=batch_size_default
            ),
            "default": batch_size_default,
        }

        # set village templates
        unit_config = self.get_village_config(
            self.village_id, parameter="units", default=None
        )
        if not unit_config:
            self.logger.warning(
                "Wieś %d nie ma nadpisania konfiguracji 'units'!", self.village_id
            )
            unit_config = self.get_config(
                section="units", parameter="default", default="basic"
            )
        try:
            self.units.template = TemplateManager.get_template(
                category="troops", template=unit_config, output_json=True
            )
        except Exception as e:
            self.logger.error(
                "Wygląda na to, że plik szablonu jednostek %s nie istnieje lub jest uszkodzony", unit_config
            )
            raise InvalidUnitTemplateException

    def run_builder(self):
        """
        Uruchamia akcje budowy konstrukcji
        """
        if not self.builder:
            self.builder = BuildingManager(
                wrapper=self.wrapper, village_id=self.village_id
            )
            self.builder.resman = self.resman
            # zarządzaj budynkami (musi zawsze działać, ponieważ sprawdzanie rekrutacji zależy od poziomów budynków)
        self.build_config = self.get_village_config(
            self.village_id, parameter="building", default=None
        )
        if self.build_config is False:
            self.logger.debug("Builder jest wyłączony dla wsi %s", self.village_id)
            return
        if not self.build_config:
            self.logger.warning(
                "Wieś %d nie ma nadpisania konfiguracji 'building'!", self.village_id
            )
            self.build_config = self.get_config(
                section="building", parameter="default", default="purple_predator"
            )
        new_queue = TemplateManager.get_template(
            category="builder", template=self.build_config
        )
        if not self.builder.raw_template or self.builder.raw_template != new_queue:
            self.builder.queue = new_queue
            self.builder.raw_template = new_queue
            if not self.get_config(
                    section="world", parameter="knight_enabled", default=False
            ):
                self.builder.queue = [
                    x for x in self.builder.queue if "statue" not in x
                ]
        self.builder.max_lookahead = self.get_config(
            section="building", parameter="max_lookahead", default=2
        )
        self.builder.max_queue_len = self.get_config(
            section="building", parameter="max_queued_items", default=2
        )
        self.builder.start_update(
            build=self.get_config(
                section="building", parameter="manage_buildings", default=True
            ),
            set_village_name=self.village_set_name,
        )

    def run_snob_recruit(self):
        """
        Używa szlachcica do tworzenia monet, przechowywania zasobów i rekrutacji szlachty
        """
        if (
                self.get_village_config(self.village_id, parameter="snobs", default=None)
                and self.builder.levels["snob"] > 0
        ):
            if not self.snobman:
                self.snobman = SnobManager(
                    wrapper=self.wrapper, village_id=self.village_id
                )
                self.snobman.troop_manager = self.units
                self.snobman.resman = self.resman
            self.snobman.wanted = self.get_village_config(
                self.village_id, parameter="snobs", default=0
            )
            self.snobman.building_level = self.builder.get_level("snob")
            self.snobman.run()

    def check_forced_peace(self):
        """
        Sprawdza, czy farmienie jest wyłączone w bieżącym czasie
        """
        # Set timeslots in order to prevent farming during events like national holidays
        forced_peace_times = self.get_config(section="farm_assistant", parameter="forced_peace_times", default=[])
        self.forced_peace = False
        self.forced_peace_today = False
        self.forced_peace_today_start = None
        for time_pairs in forced_peace_times:
            start_dt = datetime.strptime(time_pairs["start"], "%d.%m.%y %H:%M:%S")
            end_dt = datetime.strptime(time_pairs["end"], "%d.%m.%y %H:%M:%S")
            now = datetime.now()
            if start_dt.date() == datetime.today().date():
                forced_peace_today = True
                forced_peace_today_start = start_dt
            if start_dt < now < end_dt:
                self.logger.debug("Currently in a forced peace time! No attacks will be send.")
                self.forced_peace = True
                break

    def set_unit_wanted_levels(self):
        """
        Pobiera potrzebne jednostki dla bieżących budynków
        """
        self.current_unit_entry = self.units.get_template_action(self.builder.levels)

        if self.current_unit_entry and self.units.wanted != self.current_unit_entry["build"]:
            # update wanted units if template has changed
            self.logger.info(
                "%s as wanted units for current village", str(self.current_unit_entry["build"])
            )
            self.units.wanted = self.current_unit_entry["build"]

        if self.units.wanted_levels != {}:
            # Remove disabled units
            for disabled in self.disabled_units:
                self.units.wanted_levels.pop(disabled, None)
            self.logger.info(
                "%s as wanted upgrades for current village", str(self.units.wanted_levels)
            )

    def run_unit_upgrades(self):
        """
        Używa kuźni do badania lub ulepszania jednostek
        """
        if (
                self.get_config(section="units", parameter="upgrade", default=False)
                and self.units.wanted_levels != {}
        ):
            self.units.attempt_upgrade()

    def do_recruit(self):
        """
        Rekrutuje nowe jednostki
        """
        if self.get_config(section="units", parameter="recruit", default=False):
            self.units.can_fix_queue = self.get_config(
                section="units", parameter="remove_manual_queued", default=False
            )
            self.units.randomize_unit_queue = self.get_config(
                section="units", parameter="randomize_unit_queue", default=True
            )
            # prioritize_building: will only recruit when builder has sufficient funds for queue items
            if (
                    self.get_village_config(
                        self.village_id, parameter="prioritize_building", default=False
                    )
                    and not self.resman.can_recruit()
            ):
                self.logger.info(
                    "Bez rekrutacji, ponieważ budowniczy ma niewystarczające fundusze"
                )
                for x in list(self.resman.requested.keys()):
                    if "recruitment_" in x:
                        self.resman.requested.pop(f"{x}", None)
            elif (
                    self.get_village_config(
                        self.village_id, parameter="prioritize_snob", default=False
                    )
                    and self.snobman
                    and self.snobman.can_snob
                    and self.snobman.is_incomplete
            ):
                self.logger.info("Bez rekrutacji, ponieważ szlachcic ma niewystarczające fundusze")
                for x in list(self.resman.requested.keys()):
                    if "recruitment_" in x:
                        self.resman.requested.pop(f"{x}", None)
            else:
                # do a build run for every
                for building in self.units.wanted:
                    if not self.builder.get_level(building):
                        self.logger.debug(
                            "Rekrutacja %s zostanie zignorowana, ponieważ budynek nie jest (jeszcze) dostępny", building
                        )
                        continue
                    self.units.start_update(building, self.disabled_units)

    def manage_local_resources(self):
        to_dell = []
        for x in self.resman.requested:
            if all(res == 0 for res in self.resman.requested[x].values()):
                # remove empty requests!
                to_dell.append(x)

        for x in to_dell:
            self.resman.requested.pop(x)

        self.logger.debug("Current resources: %s", str(self.resman.actual))
        self.logger.debug("Requested resources: %s", str(self.resman.requested))

    def set_farm_options(self):
        """
        Ustawia różne opcje zarządzania farmieniem
        """
        # Ensure attack manager exists
        if not self.attack:
            self.attack = AttackManager(wrapper=self.wrapper, village_id=self.village_id, troopmanager=self.units)
            # attach report manager used for safe checks
            self.attack.repman = ReportManager(wrapper=self.wrapper, village_id=self.village_id)

        self.attack.target_high_points = self.get_config(
            section="farm_assistant", parameter="attack_higher_points", default=False
        )
        self.attack.farm_minpoints = self.get_config(
            section="farm_assistant", parameter="min_points", default=24
        )

        assistant_conf = self.config.get("farm_assistant") if isinstance(self.config, dict) else None

        def _get_assistant(key, default=None):
            if assistant_conf and key in assistant_conf:
                return assistant_conf.get(key, default)
            return default

        # apply defaults or configured values from farm_assistant
        self.attack.farm_maxpoints = _get_assistant("max_points", 1080)
        self.attack.farm_radius = _get_assistant("search_radius", 50)
        self.attack.farm_default_wait = _get_assistant("default_away_time", 1200)
        self.attack.farm_high_prio_wait = _get_assistant("full_loot_away_time", 1800)
        self.attack.farm_low_prio_wait = _get_assistant("low_loot_away_time", 7200)
        self.attack.scout_farm_amount = _get_assistant("farm_scout_amount", 5)
        # enable farm assistant per-village when explicitly enabled or via legacy auto_send_assistant_attacks
        self.attack.farm_assistant = False
        if assistant_conf:
            self.attack.farm_assistant = assistant_conf.get("enabled", False) or assistant_conf.get("auto_send_assistant_attacks", False)
        self.logger.debug("Farm assistant włączony dla wsi %s = %s", self.village_id, self.attack.farm_assistant)

        # load optional conditional rules for selecting assistant icon/button
        raw_rules = _get_assistant("farm_assistant_rules", [])
        parsed_rules = []
        try:
            if isinstance(raw_rules, str):
                parsed_rules = json.loads(raw_rules) or []
            else:
                parsed_rules = raw_rules or []
        except Exception:
            parsed_rules = []

        # also read three separate rule settings for A/B/C (field/op/value)
        for btn in ['A', 'B', 'C']:
            fkey = f"farm_assistant_rule_{btn}_field"
            okey = f"farm_assistant_rule_{btn}_op"
            vkey = f"farm_assistant_rule_{btn}_value"
            f = _get_assistant(fkey, 'none')
            op = _get_assistant(okey, 'none')
            val = _get_assistant(vkey, 0)
            try:
                # normalize numeric
                if isinstance(val, str) and val.isdigit():
                    valn = int(val)
                else:
                    valn = int(val)
            except Exception:
                valn = 0
            if f and f != 'none' and op and op != 'none':
                parsed_rules.append({'button': btn, 'field': f, 'op': op, 'value': valn})

        self.attack.farm_assistant_rules = parsed_rules
        self.attack.max_farms = _get_assistant("max_farms", 25)
        if self.attack.farm_assistant:
            self.attack.template = None
            self.logger.debug(
                "Farm assistant włączony dla wsi %s, lokalne szablony wojsk zostaną zignorowane", self.village_id
            )
        elif self.current_unit_entry:
            self.attack.template = self.current_unit_entry["farm"]
        self.logger.debug("Szablon farmy dla wsi %s: %s", self.village_id, getattr(self.attack, 'template', None))
        self.logger.debug("Szablony farm assistenta dla wsi %s: %s", self.village_id, getattr(self.attack, 'farm_assistant_templates', None))

    def run_farming(self):
        """
        Uruchamia logikę farmienia
        """
        # Farm assistant jest włączony, gdy attack.farm_assistant jest true
        if not self.attack or not self.attack.farm_assistant:
            self.logger.debug("Farm assistant nie jest włączony dla wsi %s", self.village_id)
            return

        # upewnij się, że cele farm assistenta są załadowane
        self.attack.ensure_farm_assistant_targets()

        # pobierz świeżą lokalną mapę (potrzebną do współrzędnych) tylko jeśli nie używasz farm_assistant
        try:
            if not self.attack.farm_assistant:
                m = Map(wrapper=self.wrapper, village_id=self.village_id)
                m.get_map()
                self.attack.map = m
            else:
                # przy użyciu farm_assistant wyzwalane ataki bezpośrednio z am_farm
                self.logger.debug("Pomijanie pobierania mapy, ponieważ farm_assistant jest włączony dla wsi %s", self.village_id)
        except Exception:
            self.logger.debug("Nie można pobrać mapy dla ataków farm assistenta")

        # iteruj po celach farm assistenta i wysyłaj ataki do max_farms
        sent = 0
        targets = list(self.attack.farm_assistant_targets.keys()) if self.attack.farm_assistant_targets else []
        self.logger.debug("Cele farm assistenta dla wsi %s: %s", self.village_id, targets)
        self.logger.debug("Dostępne wojska dla wsi %s: %s", self.village_id, getattr(self.units, 'troops', None))
        for vid in targets:
            if sent >= self.attack.max_farms:
                break

            # pokaż link kandydata przed sprawdzeniem bezpieczeństwa
            try:
                link = self.attack.get_farm_assistant_link(vid)
                self.logger.debug("Rozwiązany link farm assistenta dla %s -> %s", vid, link)
            except Exception:
                link = None

            if not link:
                self.logger.info("Brak dostępnego przycisku dla %s, pomijam cel", vid)
                continue

            cached = self.attack.can_attack(vid=vid, clear=False)
            if not cached:
                self.logger.info("Cel %s pominięty przez sprawdzenie bezpieczeństwa lub cache", vid)
                continue

            res = self.attack.attack_with_assistant(vid)
            if not res:
                self.logger.info("Farm assistant nie wysłał ataku dla %s", vid)
                continue

            hp = cached["high_profile"] if type(cached) == dict and "high_profile" in cached else False
            lp = cached["low_profile"] if type(cached) == dict and "low_profile" in cached else False
            self.attack.attacked(vid, scout=False, safe=True, high_profile=hp, low_profile=lp)
            sent += 1

        if sent:
            self.logger.info("Wysłano %d ataków farm assistenta z wsi %s", sent, self.village_id)

    def do_gather(self):
        """
        Uruchamia zbieranie, jeśli odblokowane i aktywne
        """
        self.units.can_gather = self.get_config(
            section="gather",
            parameter="enabled",
            default=False
        )
        if not self.def_man or not self.def_man.under_attack:
            self.units.gather(
                selection=self.get_config(
                    section="gather",
                    parameter="selection",
                    default=1
                ),
                disabled_units=self.disabled_units,
                advanced_gather=self.get_config(
                    section="gather",
                    parameter="advanced",
                    default=True
                )
            )

    def go_manage_market(self):
        """
        Zarządza rynkiem
        """
        if self.get_config(
                section="market", parameter="auto_trade", default=False
        ) and self.builder.get_level("market"):
            self.logger.info("Zarządzanie rynkiem")
            self.resman.trade_max_per_hour = self.get_config(
                section="market", parameter="trade_max_per_hour", default=1
            )
            self.resman.trade_max_duration = self.get_config(
                section="market", parameter="max_trade_duration", default=1
            )
            if self.get_config(
                    section="market", parameter="trade_multiplier", default=False
            ):
                self.resman.trade_bias = self.get_config(
                    section="market", parameter="trade_multiplier_value", default=1.0
                )
            self.resman.manage_market(
                drop_existing=self.get_config(
                    section="market", parameter="auto_remove", default=True
                )
            )

        res = self.wrapper.get_action(village_id=self.village_id, action="overview")
        self.game_data = Extractor.game_state(res)
        self.resman.update(self.game_data)
        if self.get_config(
                section="world", parameter="trade_for_premium", default=False
        ) and self.get_village_config(
            self.village_id, parameter="trade_for_premium", default=False
        ):
            # Ustaw parametr poprawnie, gdy konfiguracja tak mówi.
        self.config = config
        self.wrapper.delay = self.get_config(
            section="bot", parameter="delay_factor", default=1.0
        )

        data = self.village_init()

        if not self.game_data:
            self.logger.error(
                "Błąd odczytu danych gry dla wsi %s", self.village_id
            )
            raise VillageInitException

        self.set_world_config()

        if not self.get_config(section="villages", parameter=self.village_id):
            raise VillageInitException

        vdata = self.get_config(section="villages", parameter=self.village_id)
        if not self.get_village_config(
                self.village_id, parameter="managed", default=False
        ):
            return False
        if not self.game_data:
            raise InvalidGameStateException

        self.update_pre_run()

        self.setup_defence_manager(data=data)
        self.run_quest_actions(config=config)

        self.run_builder()
        self.units_get_template()
        self.set_unit_wanted_levels()

        self.units.update_totals()
        self.run_unit_upgrades()
        self.run_snob_recruit()
        self.do_recruit()
        self.manage_local_resources()

        # ensure farm options are configured for this village before running farming
        try:
            self.set_farm_options()
        except Exception:
            self.logger.debug("Error setting farm options for village %s", self.village_id)

        self.run_farming()

        self.do_gather()
        self.go_manage_market()

        self.set_cache_vars()
        self.logger.info("Cykl wsi zakończony, powrót do przeglądu")
        self.wrapper.reporter.report(
            self.village_id, "TWB_POST_RESOURCE", str(self.resman.actual)
        )
        self.wrapper.reporter.add_data(
            self.village_id,
            data_type="village.resources",
            data=json.dumps(self.resman.actual),
        )
        self.wrapper.reporter.add_data(
            self.village_id,
            data_type="village.buildings",
            data=json.dumps(self.builder.levels),
        )
        self.wrapper.reporter.add_data(
            self.village_id,
            data_type="village.troops",
            data=json.dumps(self.units.total_troops),
        )
        self.wrapper.reporter.add_data(
            self.village_id, data_type="village.config", data=json.dumps(vdata)
        )

    def get_quests(self):
        result = Extractor.get_quests(self.wrapper.last_response)
        if result:
            qres = self.wrapper.get_api_action(
                action="quest_complete",
                village_id=self.village_id,
                params={"quest": result, "skip": "false"},
            )
            if qres:
                self.logger.info("Ukończono zadanie: %s", str(result))
                return True
        self.logger.debug("Nie ukończono żadnych zadań")
        return False

    def get_quest_rewards(self):
        result = self.wrapper.get_api_data(
            action="quest_popup",
            village_id=self.village_id,
            params={"screen": 'new_quests', "tab": "main-tab", "quest": 0},
        )
        # Dane są escapowane dla JS, więc od-escapujemy je przed wysłaniem do ekstraktora.
        rewards = Extractor.get_quest_rewards(decode(result["response"]["dialog"], 'unicode-escape'))
        for reward in rewards:
            # Najpierw sprawdź, czy jest wystarczająco miejsca na przechowanie nagrody
            for t_resource in reward["reward"]:
                if self.resman.storage - self.resman.actual[t_resource] < reward["reward"][t_resource]:
                    self.logger.info("Za mało miejsca, aby przechować część nagrody: %s", t_resource)
                    return False

            qres = self.wrapper.post_api_data(
                action="claim_reward",
                village_id=self.village_id,
                params={"screen": "new_quests"},
                data={"reward_id": reward["id"]}
            )
            if qres:
                if not qres['response']:
                    self.logger.debug("Błąd pobierania nagrody! %s", qres)
                    return False
                else:
                    self.logger.info("Otrzymano nagrodę za zadanie: %s", str(reward))
                    for t_resource in reward["reward"]:
                        self.resman.actual[t_resource] += reward["reward"][t_resource]

        self.logger.debug("Nie ma (więcej) nagród za zadania")
        return len(rewards) > 0

    def set_cache_vars(self):
        village_entry = {
            "name": self.game_data["village"]["name"],
            "public": self.area.in_cache(self.village_id) if self.area else None,
            "resources": self.resman.actual,
            "required_resources": self.resman.requested,
            "available_troops": self.units.troops,
            "buidling_levels": self.builder.levels,
            "building_queue": self.builder.queue,
            "troops": self.units.total_troops,
            "under_attack": self.def_man.under_attack,
            "last_run": int(time.time()),
        }
        FileManager.save_json_file(village_entry, f"cache/managed/{self.village_id}.json")
