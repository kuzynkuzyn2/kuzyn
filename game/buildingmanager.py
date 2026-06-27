"""
Zarządza menedżerem budynków
"""
import logging
import random
import re
import time

from core.extractors import Extractor


class BuildingManager:
    """
    Podstawowa klasa do zarządzania budynkami
    """
    logger = None
    levels = {}

    # Liczba budyneków w kolejce do zajrzenia
    # Zwiększenie tego da ogromne punkty, ale niewystarczające zasoby
    max_lookahead = 2

    queue = []
    waits = []
    waits_building = []

    costs = {}

    wrapper = None
    village_id = None
    game_state = {}

    # Can be increased with a premium account
    max_queue_len = 2
    resman = None
    raw_template = None

    can_build_three_min = False

    def __init__(self, wrapper, village_id):
        """
        Utwórz menedżera budynków
        """
        self.wrapper = wrapper
        self.village_id = village_id

    def create_update_links(self, extracted_buildings):
        """
        Tworzy linki aktualizacji dla budynku
        """
        link = self.game_state["link_base_pure"] + "main&action=upgrade_building"

        for building in extracted_buildings:
            _id = extracted_buildings[building]["id"]
            _link = link + "&id=" + _id + "&type=main&h=" + self.game_state["csrf"]

            extracted_buildings[building]["build_link"] = _link

        return extracted_buildings

    def start_update(self, build=False, set_village_name=None):
        """
        Uruchamia cykl menedżera budynków
        """
        main_data = self.wrapper.get_action(village_id=self.village_id, action="main")
        self.game_state = Extractor.game_state(main_data)
        # POPRAWIONE: bezpieczny dostęp do game_state - nie crash gdy Extraction zawiedzie
        if not self.game_state or not isinstance(self.game_state, dict) or "village" not in self.game_state:
            if not self.logger:
                self.logger = logging.getLogger(
                    f"Builder: village_{self.village_id}"
                )
            self.logger.warning(
                "Nie udało się odczytać stanu gry (game_state=%s) dla wsi %s, pomijam start_update",
                type(self.game_state).__name__, self.village_id,
            )
            return False
        vname = self.game_state["village"].get("name", self.village_id)

        if not self.logger:
            self.logger = logging.getLogger(fr"Builder: {vname}")

        if self.complete_actions(main_data.text):
            return self.start_update(build=build, set_village_name=set_village_name)
        self.costs = Extractor.building_data(main_data)
        self.costs = self.create_update_links(self.costs)

        if self.resman:
            self.resman.update(self.game_state)
            if "building" in self.resman.requested:
                # nowy przebieg, usuń żądanie
                self.resman.requested["building"] = {}
        if set_village_name and vname != set_village_name:
            self.wrapper.post_url(
                url=f"game.php?village={self.village_id}&screen=main&action=change_name",
                data={"name": set_village_name, "h": self.wrapper.last_h},
            )

        self.logger.debug("Updating building levels")
        tmp = self.game_state["village"]["buildings"]
        for e in tmp:
            tmp[e] = int(tmp[e])
        self.levels = tmp
        existing_queue = Extractor.active_building_queue(main_data)
        self.logger.info(
            "Próba zakolejkowania budowy. Pozostałe budynki=%d, długość kolejki budowy=%d",
            len(self.queue), existing_queue,
        )
        if existing_queue == 0:
            self.waits = []
            self.waits_building = []
        if self.is_queued():
            self.logger.info(
                "Nie wykonano żadnej operacji budowy: kolejka pełna, pozostało %d", len(self.queue)
            )
            return False
        if not build:
            self.logger.info("Tryb budowania wyłączony dla tego przebiegu, pomijanie akcji budowy")
            return False

        if existing_queue != 0 and existing_queue != len(self.waits):
            if existing_queue > 1:
                self.logger.warning(
                    "Kolejka budowy niezsynchronizowana, oczekiwanie na zakończenie %d ręcznych akcji!",
                    existing_queue
                )
                return True
            else:
                self.logger.info(
                    "Pozostała tylko 1 ręczna akcja, próba zakolejkowania następnego budynku"
                )

        if existing_queue == 1:
            r = self.max_queue_len - 1
        else:
            r = self.max_queue_len - len(self.waits)
        for x in range(r):
            result = self.get_next_building_action()
            if not result:
                self.logger.info(
                    "Nie wykonano dalszych operacji budowy (%d bieżących, %d pozostało)",
                    len(self.waits), len(self.queue)
                )
                return False
        # Sprawdź natychmiastowe budowanie po dodaniu czegoś do kolejki
        main_data = self.wrapper.get_action(village_id=self.village_id, action="main")
        if self.complete_actions(main_data.text):
            self.can_build_three_min = True
            return self.start_update(build=build, set_village_name=set_village_name)
        return True

    def complete_actions(self, text):
        """
        Automatycznie kończy budynek, jeśli świat na to pozwala
        TODO: dodać opcje premium obniżające koszty budowy
        """
        res = re.search(
            r'(?s)(\d+),\s*\'BuildInstantFree.+?data-available-from="(\d+)"', text
        )
        if res and int(res.group(2)) <= time.time():
            quickbuild_url = f"game.php?village={self.village_id}&screen=main&ajaxaction=build_order_reduce"
            quickbuild_url += f"&h={self.wrapper.last_h}&id={res.group(1)}&destroy=0"
            result = self.wrapper.get_url(quickbuild_url)
            self.logger.debug("Szybka budowa zakończona, ponowne uruchomienie funkcji")
            return result
        return False

    def put_wait(self, wait_time):
        """
        Umieszcza element w aktywnej kolejce budowy
        Blokuje wpisy do czasu zakończenia budowy
        """
        self.is_queued()
        if len(self.waits) == 0:
            f_time = time.time() + wait_time
            self.waits.append(f_time)
            return f_time
        else:
            lastw = self.waits[-1]
            f_time = lastw + wait_time
            self.waits.append(f_time)
            self.logger.debug("Czas zakończenia budowy: %s", str(f_time))
            return f_time

    def is_queued(self):
        """
        Sprawdza, czy budynek jest już w kolejce
        """
        if len(self.waits) == 0:
            return False
        for w in list(self.waits):
            if w < time.time():
                self.waits.pop(0)
        return len(self.waits) >= self.max_queue_len

    def has_enough(self, build_item):
        """
        Sprawdza, czy jest wystarczająco zasobów, aby zakolejkować budynek
        """
        # Zabezpieczenie przed KeyError, gdy build_item nie ma oczekiwanych kluczy
        try:
            storage_level = int(self.levels.get("storage", 0))
            # POPRAWIONE: zabezpieczenie przed nieskończonym wstawianiem storage do kolejki
            # Sprawdzamy czy storage nie został już wstawiony na początku kolejki.
            if (
                    build_item.get("iron", 0) > self.resman.storage
                    or build_item.get("wood", 0) > self.resman.storage
                    or build_item.get("stone", 0) > self.resman.storage
            ):
                build_data = "storage:%d" % (storage_level + 1)
                if (
                        len(self.queue)
                        and "storage"
                        not in [x.split(":")[0] for x in self.queue[0: self.max_lookahead]]
                        and storage_level != 30
                ):
                    self.queue.insert(0, build_data)
                    self.logger.info(
                        "Dodawanie magazynu na początek kolejki, ponieważ element kolejki przekracza pojemność magazynu"
                    )
                    # Zamiast pozwalać na kontynuowanie, zwracamy False — niech get_next_building_action
                    # obsłuży wstawiony storage w następnej iteracji
                    return False
        except Exception as e:
            self.logger.debug("Błąd w has_enough storage check: %s", e)

        r = True
        try:
            village = self.game_state["village"]
            if build_item.get("wood", 0) > village.get("wood", 0):
                req = build_item["wood"] - village["wood"]
                self.resman.request(source="building", resource="wood", amount=req)
                r = False
            if build_item.get("stone", 0) > village.get("stone", 0):
                req = build_item["stone"] - village["stone"]
                self.resman.request(source="building", resource="stone", amount=req)
                r = False
            if build_item.get("iron", 0) > village.get("iron", 0):
                req = build_item["iron"] - village["iron"]
                self.resman.request(source="building", resource="iron", amount=req)
                r = False
            pop_cost = build_item.get("pop", 0)
            pop_avail = village.get("pop_max", 0) - village.get("pop", 0)
            if pop_cost > pop_avail:
                req = pop_cost - pop_avail
                self.resman.request(source="building", resource="pop", amount=req)
                r = False
        except Exception as e:
            self.logger.debug("Błąd w has_enough resource check: %s", e)
            return False

        if not r:
            self.logger.info(
                "Niewystarczające zasoby do budowy, żądane aktualizacje: %s",
                self.resman.requested,
            )
        return r

    def get_level(self, building):
        """
        Pobiera poziom budynku
        """
        if building not in self.levels:
            return 0
        return self.levels[building]

    def readable_ts(self, seconds):
        """
        Robi rzeczy bardziej czytelnymi dla człowieka
        """
        seconds -= time.time()
        seconds = seconds % (24 * 3600)
        hour = seconds // 3600
        seconds %= 3600
        minutes = seconds // 60
        seconds %= 60

        return "%d:%02d:%02d" % (hour, minutes, seconds)

    def get_next_building_action(self, index=0):
        """
        Oblicza następną najlepszą możliwą akcję budowania.
        POPRAWIONE: zlicza "pominięcia" niedostępnych budynków i po N próbach
        usuwa je z kolejki zamiast logować w kółko "Pomijanie X, ponieważ jeszcze niedostępne".
        """
        if index >= len(self.queue) or index >= self.max_lookahead:
            self.logger.debug("Nic nie buduję, ponieważ niewystarczające zasoby lub indeks poza zakresem")
            return False

        queue_check = self.is_queued()
        if queue_check:
            self.logger.info("Nie buduję z powodu elementów w kolejce: %s", self.waits)
            return False

        # POPRAWIONE: Jeśli po 3 próbach ten sam niedostępny budynek został pominięty,
        # usuń go z kolejki żeby nie blokować kolejnych cykli.
        if not hasattr(self, '_skip_counts'):
            self._skip_counts = {}

        if self.resman and self.resman.in_need_of("pop"):
            build_data = "farm:%d" % (int(self.levels["farm"]) + 1)
            if (
                    len(self.queue)
                    and "farm"
                    not in [x.split(":")[0] for x in self.queue[0: self.max_lookahead]]
                    and int(self.levels["farm"]) != 30
            ):
                self.queue.insert(0, build_data)
                self.logger.info("Dodawanie farmy na początek kolejki, ponieważ mało populacji")
                return self.get_next_building_action(0)

        if len(self.queue):
            entry = self.queue[index]
            entry_building, min_lvl = entry.split(":")
            min_lvl = int(min_lvl)
            if min_lvl <= self.levels[entry_building]:
                self.queue.pop(index)
                self._skip_counts.pop(entry_building, None)
                return self.get_next_building_action(index)
            if entry_building not in self.costs:
                # POPRAWIONE: zamiast pomijać w nieskończoność, usuń z kolejki po kilku próbach
                self._skip_counts[entry_building] = self._skip_counts.get(entry_building, 0) + 1
                if self._skip_counts[entry_building] >= 3:
                    self.logger.info(
                        "Usuwanie %s z kolejki (niedostępne od 3+ cykli, prawdopodobnie jeszcze nie zbudowano)",
                        entry_building,
                    )
                    self.queue.pop(index)
                    self._skip_counts.pop(entry_building, None)
                    return self.get_next_building_action(index)
                self.logger.info("Pomijanie %s, ponieważ jeszcze niedostępne", entry_building)
                return self.get_next_building_action(index + 1)
            check = self.costs[entry_building]
            if "max_level" in check and min_lvl > check["max_level"]:
                self.logger.info(
                    "Usuwanie wpisu %s, ponieważ przekroczono max_level", entry_building
                )
                self.queue.pop(index)
                self._skip_counts.pop(entry_building, None)
                return self.get_next_building_action(index)
            if check["can_build"] and self.has_enough(check) and "build_link" in check:
                # Sukces — resetujemy licznik pominięć dla tego budynku
                self._skip_counts.pop(entry_building, None)
                queue = self.put_wait(check["build_time"])
                self.logger.info(
                    "Budowanie %s %d -> %d (zakończy się: %s)"
                    % (
                        entry_building,
                        self.levels[entry_building],
                        self.levels[entry_building] + 1,
                        self.readable_ts(queue),
                    )
                )
                self.wrapper.reporter.report(
                    self.village_id,
                    "TWB_BUILD",
                    "Budowanie %s %d -> %d (zakończy się: %s)"
                    % (
                        entry_building,
                        self.levels[entry_building],
                        self.levels[entry_building] + 1,
                        self.readable_ts(queue),
                    ),
                )
                self.levels[entry_building] += 1
                response = self.wrapper.get_url(check["build_link"].replace("amp;", ""))
                if self.can_build_three_min:
                    # Poczekaj przez losowy czas
                    time.sleep(random.randint(3, 7) / 10)
                    result = self.complete_actions(text=response.text)
                    if result:
                        # Remove first item from the queue
                        self.queue.pop(0)
                        index -= 1
                    # Budowanie zakończone, kolejkowanie następnego
                self.game_state = Extractor.game_state(response)
                self.costs = Extractor.building_data(response)
                # Wyzwól funkcję ponownie, ponieważ stan gry się zmienił
                self.costs = self.create_update_links(self.costs)
                if self.resman and "building" in self.resman.requested:
                    # Zbuduj coś, usuń żądanie
                    self.resman.requested["building"] = {}
                return True
            else:
                return self.get_next_building_action(index + 1)
