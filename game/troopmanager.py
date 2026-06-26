"""
Wszystko co ma związek z rekrutacją wojsk
"""
import logging
import math
import random
import time

from core.extractors import Extractor
from game.resources import ResourceManager


class TroopManager:
    """
    Klasa menedżera wojsk
    """
    can_recruit = True
    can_attack = True
    can_dodge = False
    can_scout = True
    can_farm = True
    can_gather = True
    can_fix_queue = True
    randomize_unit_queue = True

    queue = []
    troops = {}

    total_troops = {}

    _research_wait = 0

    wrapper = None
    village_id = None
    recruit_data = {}
    game_data = {}
    logger = None
    max_batch_size = 50
    wait_for = {}

    _waits = {}

    wanted = {"barracks": {}}

    # Mapuje wojska na budynek, z którego są tworzone
    unit_building = {
        "spear": "barracks",
        "sword": "barracks",
        "axe": "barracks",
        "archer": "barracks",
        "spy": "stable",
        "light": "stable",
        "marcher": "stable",
        "heavy": "stable",
        "ram": "garage",
        "catapult": "garage",
    }

    wanted_levels = {}

    last_gather = 0

    resman = None
    template = None

    def __init__(self, wrapper=None, village_id=None):
        """
        Create the troop manager
        """
        self.wrapper = wrapper
        self.village_id = village_id
        self.wait_for[village_id] = {"barracks": 0, "stable": 0, "garage": 0}
        if not self.resman:
            self.resman = ResourceManager(
                wrapper=self.wrapper, village_id=self.village_id
            )

    def update_totals(self):
        """
        Aktualizuje całkowitą liczbę zrekrutowanych jednostek
        """
        main_data = self.wrapper.get_action(
            action="overview", village_id=self.village_id
        )
        self.game_data = Extractor.game_state(main_data)

        if self.resman:
            if "research" in self.resman.requested:
                # new run, remove request
                self.resman.requested["research"] = {}

        if not self.logger:
            village_name = self.game_data["village"]["name"]
            self.logger = logging.getLogger(f"Rekrutacja: {village_name}")
        self.troops = {}

        get_all = (
                f"game.php?village={self.village_id}&screen=place&mode=units&display=units"
        )
        result_all = self.wrapper.get_url(get_all)

        for u in Extractor.units_in_village(result_all):
            k, v = u
            self.troops[k] = v

        self.logger.debug("Units in village: %s", str(self.troops))
        self.logger.info("Rozpoczęto odświeżanie rekrutacji dla wsi %s", self.village_id)

        if not self.can_recruit:
            return

        self.total_troops = {}
        for u in Extractor.units_in_total(result_all):
            k, v = u
            if k in self.total_troops:
                self.total_troops[k] = self.total_troops[k] + int(v)
            else:
                self.total_troops[k] = int(v)
        self.logger.debug("Village units total: %s", str(self.total_troops))

    def start_update(self, building="barracks", disabled_units=[]):
        """
        Rozpoczyna aktualizację jednostek dla budynku
        """
        if self.wait_for[self.village_id][building] > time.time():
            human_ts = self.readable_ts(self.wait_for[self.village_id][building])
            self.logger.info(
                "%s nadal zajęty przez %s",
                building, human_ts
            )
            return False

        self.logger.info("Rozpoczęcie aktualizacji rekrutacji dla %s", building)
        run_selection = list(self.wanted[building].keys())
        if self.randomize_unit_queue:
            random.shuffle(run_selection)

        for wanted in run_selection:
            # Ignore disabled units
            if wanted in disabled_units:
                continue

            if wanted not in self.total_troops:
                if self.recruit(
                        wanted, self.wanted[building][wanted], building=building
                ):
                    return True
                continue

            if self.wanted[building][wanted] > self.total_troops[wanted]:
                if self.recruit(
                        wanted,
                        self.wanted[building][wanted] - self.total_troops[wanted],
                        building=building,
                ):
                    return True

        self.logger.info("Rekrutacja: %s aktualna", building)
        return False

    def get_min_possible(self, entry):
        """
        Oblicza, które jednostki są najbardziej potrzebne
        Aby uzyskać pewną równowagę całkowitej ilości
        """
        return min(
            [
                math.floor(self.game_data["village"]["wood"] / entry["wood"]),
                math.floor(self.game_data["village"]["stone"] / entry["stone"]),
                math.floor(self.game_data["village"]["iron"] / entry["iron"]),
                math.floor(
                    (
                            self.game_data["village"]["pop_max"]
                            - self.game_data["village"]["pop"]
                    )
                    / entry["pop"]
                ),
            ]
        )

    def get_template_action(self, levels):
        """
        Odczytuje dane z szablonów i określa wojska na podstawie progresji budynków
        """
        last = None
        wanted_upgrades = {}
        for x in self.template:
            if x["building"] not in levels:
                return last

            if x["level"] > levels[x["building"]]:
                return last

            last = x
            if "upgrades" in x:
                for unit in x["upgrades"]:
                    if (
                            unit not in wanted_upgrades
                            or x["upgrades"][unit] > wanted_upgrades[unit]
                    ):
                        wanted_upgrades[unit] = x["upgrades"][unit]

            self.wanted_levels = wanted_upgrades
        return last

    def research_time(self, time_str):
        """
        Oblicza czas badania jednostki
        """
        parts = [int(x) for x in time_str.split(":")]
        return parts[2] + (parts[1] * 60) + (parts[0] * 60 * 60)

    def attempt_upgrade(self):
        """
        Próbuje ulepszyć lub zbadać (nowy) typ jednostki
        """
        self.logger.debug("Zarządzanie ulepszeniami")
        if self._research_wait > time.time():
            self.logger.debug(
                "Kuźnia zajęta przez %d sekund", int(self._research_wait - time.time())
            )
            return
        unit_levels = self.wanted_levels
        if not unit_levels:
            self.logger.debug("Bez ulepszania, ponieważ nic nie jest żądane")
            return
        result = self.wrapper.get_action(village_id=self.village_id, action="smith")
        smith_data = Extractor.smith_data(result)
        if not smith_data:
            self.logger.debug("Błąd odczytu danych kuźni")
            return False
        for unit_type in unit_levels:
            if not smith_data or unit_type not in smith_data["available"]:
                self.logger.warning(
                    "Jednostka %s nie wydaje się dostępna lub kuźnia nie jest jeszcze zbudowana", unit_type
                )
                continue
            wanted_level = unit_levels[unit_type]
            current_level = int(smith_data["available"][unit_type]["level"])
            data = smith_data["available"][unit_type]

            if (
                    current_level < wanted_level
                    and "can_research" in data
                    and data["can_research"]
            ):
                if "research_error" in data and data["research_error"]:
                    self.logger.debug(
                        "Pomijanie badania %s z powodu błędu badania", unit_type
                    )
                    # Dodać potrzebne zasoby do menedżera zasobów?
                    r = True
                    if data["wood"] > self.game_data["village"]["wood"]:
                        req = data["wood"] - self.game_data["village"]["wood"]
                        self.resman.request(source="research", resource="wood", amount=req)
                        r = False
                    if data["stone"] > self.game_data["village"]["stone"]:
                        req = data["stone"] - self.game_data["village"]["stone"]
                        self.resman.request(source="research", resource="stone", amount=req)
                        r = False
                    if data["iron"] > self.game_data["village"]["iron"]:
                        req = data["iron"] - self.game_data["village"]["iron"]
                        self.resman.request(source="research", resource="iron", amount=req)
                        r = False
                    if not r:
                        self.logger.debug("Badanie wymaga zasobów")
                    continue
                if "error_buildings" in data and data["error_buildings"]:
                    self.logger.debug(
                        "Pomijanie badania %s z powodu błędu budynku", unit_type
                    )
                    continue

                attempt = self.attempt_research(unit_type, smith_data=smith_data)
                if attempt:
                    self.logger.info(
                        "Rozpoczęto ulepszanie w kuźni %s %d -> %d",
                        unit_type, current_level, current_level + 1
                    )
                    self.wrapper.reporter.report(
                        self.village_id,
                        "TWB_UPGRADE",
                        "Rozpoczęto ulepszanie w kuźni %s %d -> %d"
                        % (unit_type, current_level, current_level + 1),
                    )
                    return True
        return False

    def attempt_research(self, unit_type, smith_data=None):
        if not smith_data:
            result = self.wrapper.get_action(village_id=self.village_id, action="smith")
            smith_data = Extractor.smith_data(result)
        if not smith_data or unit_type not in smith_data["available"]:
            self.logger.warning(
                "Jednostka %s nie wydaje się dostępna lub kuźnia nie jest jeszcze zbudowana", unit_type
            )
            return
        data = smith_data["available"][unit_type]
        if "can_research" in data and data["can_research"]:
            if "research_error" in data and data["research_error"]:
                self.logger.debug(
                    "Ignorowanie badania %s z powodu błędu zasobów %s", unit_type, str(data["research_error"])
                )
                # Dodać potrzebne zasoby do menedżera zasobów?
                r = True
                if data["wood"] > self.game_data["village"]["wood"]:
                    req = data["wood"] - self.game_data["village"]["wood"]
                    self.resman.request(source="research", resource="wood", amount=req)
                    r = False
                if data["stone"] > self.game_data["village"]["stone"]:
                    req = data["stone"] - self.game_data["village"]["stone"]
                    self.resman.request(source="research", resource="stone", amount=req)
                    r = False
                if data["iron"] > self.game_data["village"]["iron"]:
                    req = data["iron"] - self.game_data["village"]["iron"]
                    self.resman.request(source="research", resource="iron", amount=req)
                    r = False
                if not r:
                    self.logger.info("Badanie wymaga zasobów, zażądano: %s", self.resman.requested)
                return False
            if "error_buildings" in data and data["error_buildings"]:
                self.logger.debug(
                    "Ignorowanie badania %s z powodu błędu budynku %s", unit_type, str(data["error_buildings"])
                )
                return False
            if (
                    "level" in data
                    and "level_highest" in data
                    and data["level_highest"] != 0
                    and data["level"] == data["level_highest"]
            ):
                return False
            res = self.wrapper.get_api_action(
                village_id=self.village_id,
                action="research",
                params={"screen": "smith"},
                data={
                    "tech_id": unit_type,
                    "source": self.village_id,
                    "h": self.wrapper.last_h,
                },
            )
            if res:
                if "research_time" in data:
                    self._research_wait = time.time() + self.research_time(
                        data["research_time"]
                    )
                self.logger.info("Rozpoczęto badanie %s", unit_type)
                # self.resman.update(res["game_data"])
                return True
        self.logger.info("Badanie %s jeszcze niemożliwe", unit_type)

    def gather(self, selection=1, disabled_units=[], advanced_gather=True):
        """
        Używane do funkcji zbierania zasobów, gdzie używa dwóch opcji:
        - Podstawowa: wszystkie wojska zbierają na wybranym poziomie
        - Zaawansowana: wojska są dzielone
        """
        if not self.can_gather:
            return False
        url = f"game.php?village={self.village_id}&screen=place&mode=scavenge"
        result = self.wrapper.get_url(url=url)
        village_data = Extractor.village_data(result)

        sleep = 0
        available_selection = 0

        self.troops = {}

        get_all = f"game.php?village={self.village_id}&screen=place&mode=units&display=units"
        result_all = self.wrapper.get_url(get_all)

        for u in Extractor.units_in_village(result_all):
            k, v = u
            self.troops[k] = v

        troops = dict(self.troops)

        haul_dict = [
            "spear:25",
            "sword:15",
            "heavy:50",
            "axe:10",
            "light:80"
        ]
        if "archer" in self.total_troops:
            haul_dict.extend(["archer:10", "marcher:50"])

        # ZAAWANSOWANE ZBIERANIE: Przechodzi od gather_selection do 1, próbując uzyskać ten sam czas (w przybliżeniu) dla każdego zbierania. Aktywne godziny wykluczają LK i topory, w nocy wszystko jest używane do zbierania (z wyjątkiem Paladyna)

        if advanced_gather:
            selection_map = [15, 21, 24,
                             26]  # Dzielnik do podziału całkowitej pojemności transportowej wojsk na kawałki, które mieszczą się w mniej więcej tym samym przedziale czasowym

            batch_multiplier = [15, 6, 3,
                                2]  # Mnożnik dla równego rozmieszczenia wojsk. Czas(zbieranie1) = Czas(zbieranie2) jeśli zbieranie2 = 2.5 * zbieranie1

            troops = {key: int(value) for key, value in troops.items()}
            total_carry = 0
            for item in haul_dict:
                item, carry = item.split(":")
                if item == "knight":
                    continue
                if item in disabled_units:
                    continue
                if item in troops and int(troops[item]) > 0:
                    total_carry += int(carry) * int(troops[item])
                else:
                    pass
            gather_batch = math.floor(total_carry / selection_map[selection - 1])

            for option in list(reversed(sorted(village_data['options'].keys())))[4 - selection:]:
                self.logger.debug(
                    f"Opcja: {option} Zablokowana? {village_data['options'][option]['is_locked']} W toku? {village_data['options'][option]['scavenging_squad'] != None}")
                if int(option) <= selection and not village_data['options'][option]['is_locked'] and not \
                village_data['options'][option]['scavenging_squad'] != None:
                    available_selection = int(option)
                    self.logger.info(f"Operacja zbierania {available_selection} jest gotowa do rozpoczęcia.")

                    payload = {
                        "squad_requests[0][village_id]": self.village_id,
                        "squad_requests[0][option_id]": str(available_selection),
                        "squad_requests[0][use_premium]": "false",
                    }

                    curr_haul = gather_batch * batch_multiplier[available_selection - 1]
                    temp_haul = curr_haul

                    self.logger.debug(
                        f"Bieżący ładunek: {curr_haul} = Partia zbierania ({gather_batch}) * Mnożnik partii {available_selection} ({batch_multiplier[available_selection - 1]})")

                    for item in haul_dict:
                        item, carry = item.split(":")
                        if item == "knight":
                            continue
                        if item in disabled_units:
                            continue

                        if item in troops and int(troops[item]) > 0:
                            troops_int = int(troops[item])
                            troops_selected = 0
                            for troop in range(troops_int):
                                if (temp_haul - int(carry) < 0):
                                    break
                                else:
                                    troops_selected += 1
                                    temp_haul -= int(carry)
                            troops_int -= troops_selected
                            troops[item] = str(troops_int)
                            payload["squad_requests[0][candidate_squad][unit_counts][%s]" % item] = str(troops_selected)
                        else:
                            payload["squad_requests[0][candidate_squad][unit_counts][%s]" % item] = "0"
                    payload["squad_requests[0][candidate_squad][carry_max]"] = str(curr_haul)
                    payload["h"] = self.wrapper.last_h
                    self.wrapper.get_api_action(
                        action="send_squads",
                        params={"screen": "scavenge_api"},
                        data=payload,
                        village_id=self.village_id,
                    )
                    sleep += random.randint(1, 5)
                    time.sleep(sleep)
                    self.last_gather = int(time.time())
                    self.logger.info(f"Użycie wojsk do operacji zbierania: {available_selection}")
                else:
                    # Zbieranie już istnieje lub jest zablokowane
                    break

        else:
            for option in reversed(sorted(village_data['options'].keys())):
                self.logger.debug(
                    f"Opcja: {option} Zablokowana? {village_data['options'][option]['is_locked']} W toku? {village_data['options'][option]['scavenging_squad'] != None}")
                if int(option) <= selection and not village_data['options'][option]['is_locked'] and not \
                village_data['options'][option]['scavenging_squad'] != None:
                    available_selection = int(option)
                    self.logger.info(f"Operacja zbierania {available_selection} jest gotowa do rozpoczęcia.")
                    selection = available_selection

                    payload = {
                        "squad_requests[0][village_id]": self.village_id,
                        "squad_requests[0][option_id]": str(available_selection),
                        "squad_requests[0][use_premium]": "false",
                    }
                    total_carry = 0
                    for item in haul_dict:
                        item, carry = item.split(":")
                        if item == "knight":
                            continue
                        if item in disabled_units:
                            continue
                        if item in troops and int(troops[item]) > 0:
                            payload[
                                "squad_requests[0][candidate_squad][unit_counts][%s]" % item
                                ] = troops[item]
                            total_carry += int(carry) * int(troops[item])
                        else:
                            payload[
                                "squad_requests[0][candidate_squad][unit_counts][%s]" % item
                                ] = "0"
                    payload["squad_requests[0][candidate_squad][carry_max]"] = str(total_carry)
                    if total_carry > 0:
                        payload["h"] = self.wrapper.last_h
                        self.wrapper.get_api_action(
                            action="send_squads",
                            params={"screen": "scavenge_api"},
                            data=payload,
                            village_id=self.village_id,
                        )
                        self.last_gather = int(time.time())
                        self.logger.info(f"Użycie wojsk do operacji zbierania: {selection}")
                else:
                    # Zbieranie już istnieje lub jest zablokowane
                    break
        self.logger.info("Wszystkie dostępne poziomy zbieractwa są w użyciu.")
        return True

    def _recruit_screen(self, building):
        """
        Zwraca rzeczywisty ekran używany do rekrutacji z budynku.
        """
        if building in ["barracks", "stable", "garage"]:
            return "train"
        return building

    def cancel(self, building, id):
        """
        Anuluje akcję rekrutacji wojsk
        """
        screen = self._recruit_screen(building)
        self.wrapper.get_api_action(
            action="cancel",
            params={"screen": screen},
            data={"id": id},
            village_id=self.village_id,
        )

    def recruit(self, unit_type, amount=10, wait_for=False, building="barracks"):
        """
        Rekrutuje x ilości x z określonego budynku
        """
        screen = self._recruit_screen(building)
        data = self.wrapper.get_action(action=screen, village_id=self.village_id)

        existing = Extractor.active_recruit_queue(data)
        if existing:
            self.logger.warning(
                "W kolejce rekrutacji wsi %s %s brak synchronizacji"
                % (self.village_id, building)
            )
            self.logger.info(
                "Kolejka rekrutacji budynku %s jest niezsynchronizowana; anulowanie ręcznych wpisów w celu ponownej synchronizacji",
                building,
            )
            if not self.can_fix_queue:
                return True
            for entry in existing:
                self.cancel(building=building, id=entry)
                self.logger.info(
                    "Anulowano element rekrutacji %s w budynku %s" % (entry, building)
                )
            return self.recruit(unit_type, amount, wait_for, building)

        self.recruit_data = Extractor.recruit_data(data)
        self.game_data = Extractor.game_state(data)
        self.logger.info("Próba rekrutacji %d %s" % (amount, unit_type))

        max_batch_size = self.max_batch_size
        if isinstance(max_batch_size, dict):
            max_batch_size = max_batch_size.get(building, max_batch_size.get("default", 50))
        if amount > max_batch_size:
            amount = max_batch_size

        if unit_type not in self.recruit_data:
            self.logger.warning(
                "Rekrutacja %d %s nie powiodła się, ponieważ jednostka nie jest zbadana."
                % (amount, unit_type)
            )
            self.attempt_research(unit_type)
            return False

        resources = self.recruit_data[unit_type]
        if not resources:
            self.logger.warning(
                "Rekrutacja %d %s nie powiodła się z powodu nieprawidłowego identyfikatora"
                % (amount, unit_type)
            )
            return False
        if not resources["requirements_met"]:
            self.logger.info(
                "Rekrutacja %d %s zakolejkowana na później, ponieważ wymagania nie są spełnione",
                amount, unit_type
            )
            self.attempt_research(unit_type)
            return False

        get_min = self.get_min_possible(resources)
        if get_min == 0:
            self.logger.info(
                "Rekrutacja %d %s nie powiodła się z powodu braku zasobów, rezerwowanie brakujących ilości",
                amount, unit_type
            )
            self.reserve_resources(resources, amount, get_min, unit_type)
            return False

        needed_reserve = False
        if get_min < amount:
            if wait_for:
                self.logger.info(
                    "Rekrutacja %d %s odroczona z powodu braku zasobów",
                    amount, unit_type
                )
                self.reserve_resources(resources, amount, get_min, unit_type)
                needed_reserve = True
                return False
            if get_min > 0:
                self.logger.info(
                    "Rekrutacja %d %s zmniejszona do %d z powodu dostępnych zasobów",
                    amount, unit_type, get_min
                )
                self.reserve_resources(resources, amount, get_min, unit_type)
                amount = get_min
                needed_reserve = True

        if not needed_reserve:
            # Nie trzeba już rezerwować zasobów!
            if f"recruitment_{unit_type}" in self.resman.requested:
                self.resman.requested.pop(f"recruitment_{unit_type}", None)

        result = self.wrapper.get_api_action(
            village_id=self.village_id,
            action="train",
            params={"screen": screen, "mode": "train"},
            data={"units[%s]" % unit_type: str(amount)},
        )
        if "game_data" in result:
            self.resman.update(result["game_data"])
            self.wait_for[self.village_id][building] = int(time.time()) + (
                    amount * int(resources["build_time"])
            )
            # self.troops[unit_type] = str((int(self.troops[unit_type]) if unit_type in self.troops else 0) + amount)
            self.logger.info(
                "Rekrutacja %d %s rozpoczęta (%s bezczynny do %d)",
                    amount,
                    unit_type,
                    building,
                    self.wait_for[self.village_id][building],
            )
            self.wrapper.reporter.report(
                self.village_id,
                "TWB_RECRUIT",
                "Rekrutacja %d %s rozpoczęta (%s bezczynny do %d)"
                % (
                    amount,
                    unit_type,
                    building,
                    self.wait_for[self.village_id][building],
                ),
            )
            return True
        return False

    def reserve_resources(self, resources, wanted_times, has_times, unit_type):
        """
        Rezerwuje zasoby dla określonej akcji rekrutacji
        """
        # Zasoby na jednostkę, żądana partia, już rekrutowana partia
        create_amount = wanted_times - has_times
        self.logger.debug(f"Żądanie zasobów do rekrutacji %d %s", create_amount, unit_type)
        for res in ["wood", "stone", "iron"]:
            req = resources[res] * (wanted_times - has_times)
            self.resman.request(source=f"recruitment_{unit_type}", resource=res, amount=req)

    def readable_ts(self, seconds):
        """
        Czytelny dla człowieka znacznik czasu
        """
        seconds -= time.time()
        seconds = seconds % (24 * 3600)
        hour = seconds // 3600
        seconds %= 3600
        minutes = seconds // 60
        seconds %= 60

        return "%d:%02d:%02d" % (hour, minutes, seconds)
