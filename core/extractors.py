"""
Plik używany do ekstrakcji danych
"""

import json
import re


class Extractor:
    """
    Definiuje różne niekompilowane wyrażenia regularne do pobierania danych
    TODO: uży skompilowanych dla efektywności CPU
    """
    @staticmethod
    def village_data(res):
        """
        Wykrywa dane wsi na stronie
        """
        if type(res) != str:
            res = res.text
        grabber = re.search(r'var village = (.+);', res)
        if grabber:
            data = grabber.group(1)
            return json.loads(data, strict=False)

    @staticmethod
    def game_state(res):
        """
        Wykrywa stan gry dostepny na większości stron
        """
        if type(res) != str:
            res = res.text
        grabber = re.search(r'TribalWars\.updateGameData\((.+?)\);', res)
        if grabber:
            data = grabber.group(1)
            return json.loads(data, strict=False)

    @staticmethod
    def building_data(res):
        """
        Pobiera dane budynków z głównego budynku
        """
        if type(res) != str:
            res = res.text
        dre = re.search(r'(?s)BuildingMain.buildings = (\{.+?\});', res)
        if dre:
            return json.loads(dre.group(1), strict=False)

        return None

    @staticmethod
    def get_quests(res):
        """
        Pobiera dane zadań z prawie każdej strony
        """
        if type(res) != str:
            res = res.text
        get_quests = re.search(r'Quests.setQuestData\((\{.+?\})\);', res)
        if get_quests:
            result = json.loads(get_quests.group(1), strict=False)
            for quest in result:
                data = result[quest]
                if data['goals_completed'] == data['goals_total']:
                    return quest
        return None

    @staticmethod
    def get_quest_rewards(res):
        """
        Wykrywa, czy są dostępne nagrody za zadania
        """
        if type(res) != str:
            res = res.text
        get_rewards = re.search(r'RewardSystem\.setRewards\(\s*(\[\{.+?\}\]),', res)
        rewards = []
        if get_rewards:
            result = json.loads(get_rewards.group(1), strict=False)
            for reward in result:
                if reward['status'] == "unlocked":
                    rewards.append(reward)
        # Zwróć wszystkie z nich
        return rewards

    @staticmethod
    def map_data(res):
        """
        Wykrywa inne wsie na stronie mapy
        """
        if type(res) != str:
            res = res.text
        data = re.search(r'(?s)TWMap.sectorPrefech = (\[(.+?)\]);', res)
        if data:
            result = json.loads(data.group(1), strict=False)
            return result

    @staticmethod
    def smith_data(res):
        """
        Pobiera dane kuźni
        """
        if type(res) != str:
            res = res.text
        data = re.search(r'(?s)BuildingSmith.techs = (\{.+?\});', res)
        if data:
            result = json.loads(data.group(1), strict=False)
            return result
        return None

    @staticmethod
    def premium_data(res):
        """
        Wykrywa dane na stronie wymiany premium
        """
        if type(res) != str:
            res = res.text
        data = re.search(r'(?s)PremiumExchange.receiveData\((.+?)\);', res)
        if data:
            result = json.loads(data.group(1), strict=False)
            return result
        return None

    @staticmethod
    def recruit_data(res):
        """
        Pobiera dane rekrutacji dla bieżącego budynku
        """
        if type(res) != str:
            res = res.text
        data = re.search(r'(?s)unit_managers.units = (\{.+?\});', res)
        if data:
            raw = data.group(1)
            quote_keys_regex = r'([\{\s,])(\w+)(:)'
            processed = re.sub(quote_keys_regex, r'\1"\2"\3', raw)
            result = json.loads(processed, strict=False)
            return result

    @staticmethod
    def units_in_village(res):
        """
        Wykrywa wszystkie jednostki we wsi
        """
        if type(res) != str:
            res = res.text
        matches = re.search(r'<table id="units_home".*?</tr>(.*?)</tr>', res, re.DOTALL)
        # We get the start of the table and grab the 2nd row (Where "From this village" troops are located)
        if matches:
            table_content = matches.group(1)
            unit_matches = re.findall(r'class=\'unit-item unit-item-(.*?)\'[^>]*>(\d+)</td>', table_content)
            # Find all the tuples (name, quantity) under the class "unit-item unit-item-*troop_name*"
            units = [(re.sub(r'\s*tooltip\s*', '', unit_name), unit_quantity) for unit_name, unit_quantity in
                     unit_matches if int(unit_quantity) > 0]
            # Filter units with quantity = 0, also for the Paladin,
            # the name would be "knight tooltip", so we had to remove that.
            return units
        return []

    @staticmethod
    def active_building_queue(res):
        """
        Wykrywa wpisy budynków w kolejce
        """
        if type(res) != str:
            res = res.text
        builder = re.search('(?s)<table id="build_queue"(.+?)</table>', res)
        if not builder:
            return 0

        return builder.group(1).count('<a class="btn btn-cancel"')

    @staticmethod
    def active_recruit_queue(res):
        """
        Wykrywa aktywne wpisy rekrutacji
        """
        if type(res) != str:
            res = res.text
        builder = re.findall(r'(?s)TrainOverview\.cancelOrder\((\d+)\)', res)
        return builder

    @staticmethod
    def village_ids_from_overview(res):
        """
        Pobiera wsie ze strony przeglądu
        """
        if type(res) != str:
            res = res.text
        villages = re.findall(r'<span class="quickedit-vn" data-id="(\w+)"', res)
        return list(set(villages))

    @staticmethod
    def units_in_total(res):
        """
        Pobiera całkowitą liczbę jednostek we wsi
        """
        if type(res) != str:
            res = res.text
        # ukryj jednostki z innych wiosek
        res = re.sub(r'(?s)<span class="village_anchor.+?</tr>', '', res)
        data = re.findall(r'(?s)class=\Wunit-item unit-item-([a-z]+)\W.+?(\d+)</td>', res)
        return data

    @staticmethod
    def attack_form(res):
        """
        Wykrywa pola wejściowe w formularzu ataku
        ... ponieważ jest ich wiele :)
        """
        if type(res) != str:
            res = res.text
        data = re.findall(r'(?s)<input.+?name="(.+?)".+?value="(.*?)"', res)
        return data

    @staticmethod
    def farm_assistant_pagination(res):
        """
        Wykrywa dodatkowe strony farm assistenta z paginacji
        """
        if type(res) != str:
            res = res.text
        return re.findall(r'<a[^>]+class="[^"]*paged-nav-item[^"]*"[^>]+href="([^"]+)"', res)

    @staticmethod
    def farm_assistant_targets(res):
        """
        Wyodrębnia dostępne linki celów farm assistenta i poziomy muru
        """
        if type(res) != str:
            res = res.text
        targets = {}
        # spróbuj wykryć ID bieżącej wsi ze strony, aby zbudować prawidłowe linki place
        cur_vid = None
        m_vid = re.search(r'"village"\s*:\s*\{[^}]*?"id"\s*:\s*(\d+)', res)
        if m_vid:
            cur_vid = m_vid.group(1)
        rows = re.findall(r'(?s)<tr[^>]*>(.*?)</tr>', res)
        for row in rows:
            # szybko pomiń, jeśli nie ma tokenów związanych z farmą
            if 'farm' not in row and 'farm_icon' not in row and 'am_farm' not in row:
                continue
            tds = re.findall(r'(?s)<td[^>]*>(.*?)</td>', row)
            wall = 0
            if len(tds) > 6:
                wall_text = re.sub(r'<.*?>', '', tds[6]).strip()
                digits = re.findall(r'-?\d+', wall_text)
                if digits:
                    try:
                        wall = int(digits[0])
                    except Exception:
                        wall = 0

            # znajdź wszystkie znaczniki zakotwiczenia w wierszu, łącznie z atrybutami i wewnętrznym HTML
            anchors = re.findall(r'(?s)<a([^>]*)>(.*?)</a>', row)
            for attrs, inner in anchors:
                action = None
                href = None
                onclick = None
                # wyodrębnij atrybuty
                href_m = re.search(r'href="([^"\']*)"', attrs)
                if href_m:
                    href = href_m.group(1)
                onclick_m = re.search(r'onclick="([^"\']*)"', attrs)
                if onclick_m:
                    onclick = onclick_m.group(1)

                # wykryj literę akcji z atrybutu class lub z ciągu atrybutów
                class_m = re.search(r'class="([^"]*)"', attrs)
                disabled = False
                if class_m:
                    cls = class_m.group(1)
                    m = re.search(r'farm[_-]?icon[_-]?([abc])', cls, re.I)
                    if m:
                        action = m.group(1)
                    if re.search(r'farm_icon_disabled|start_locked|\bdone\b', cls, re.I):
                        disabled = True

                # awaryjnie: szukaj w wewnętrznym HTML lub całym wierszu
                if not action:
                    m2 = re.search(r'farm[_-]?icon[_-]?([abc])', inner, re.I)
                    if m2:
                        action = m2.group(1)
                    else:
                        m3 = re.search(r'farm[_-]?icon[^\w]*([abc])', row, re.I)
                        if m3:
                            action = m3.group(1)

                if not action:
                    continue

                vid = None
                # preferuj wzorzec onclick zawierający sendUnits(village, template)
                if onclick:
                    m = re.search(r'sendUnits\s*\(\s*this\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', onclick)
                    if not m:
                        # czasami jest to bez 'this'
                        m = re.search(r'sendUnits\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)', onclick)
                    if m:
                        vid = m.group(1)
                        template_id = None
                        try:
                            template_id = m.group(2)
                        except Exception:
                            template_id = None

                # jeśli brak vid z onclick, spróbuj typowych parametrów href
                if not vid and href:
                    for regex in [r'farm[_-]?icon[_-]?[abc]=(\d+)', r'target=(\d+)', r'village=(\d+)', r'target_id=(\d+)']:
                        mm = re.search(regex, href)
                        if mm:
                            vid = mm.group(1)
                            break
                # awaryjnie: dowolna 4-7-cyfrowa liczba w href
                if not vid and href:
                    mm2 = re.search(r'(\d{4,7})', href)
                    if mm2:
                        vid = mm2.group(1)

                if not vid:
                    continue

                # zbuduj użyteczny link: użyj ekranu place, aby atakujący mógł załadować normalny formularz ataku
                if href and href != '#':
                    usable_link = href
                else:
                    if cur_vid:
                        usable_link = f"game.php?village={cur_vid}&screen=place&target={vid}"
                    else:
                        usable_link = f"game.php?village=0&screen=place&target={vid}"
                # przechowuj surowe atrybuty, aby wywołujący mógł wybrać sposób wywołania kliknięcia
                target = targets.setdefault(str(vid), {'wall': wall, 'links': {}})
                target['links'][action.upper()] = {
                    'href': href,
                    'onclick': onclick,
                    'usable': usable_link,
                    'disabled': disabled,
                }

                # spróbuj wykryć status bezpieczeństwa/raportu w wierszu
                # domyślnie safe=True, chyba że wykryto oznaczenia wroga
                safe = True
                if re.search(r'report[-_ ]?(state|status)[^>]*>([^<]+)', row, re.I):
                    mtxt = re.search(r'report[-_ ]?(state|status)[^>]*>([^<]+)', row, re.I)
                    if mtxt and re.search(r'red|danger|enemy|hostile|units|niebezpie', mtxt.group(2), re.I):
                        safe = False
                if re.search(r'class="[^"]*(report|report-state|report-icon)[^"]*(red|danger|bad)[^"]*"', row, re.I):
                    safe = False

                # wykryj typ wyniku łupu z ikon lub tytułów wiersza
                loot_type = 'unknown'
                if re.search(r'max_loot/(?:1|full)\.(?:webp|png|jpg)', row, re.I) or re.search(r'full[_-]?loot', row, re.I):
                    loot_type = 'full'
                elif re.search(r'max_loot/(?:0|partial)\.(?:webp|png|jpg)', row, re.I) or re.search(r'partial[_-]?loot', row, re.I):
                    loot_type = 'partial'

                # wyodrębnij dane współrzędnych z tekstu wiersza
                coords = None
                coords_match = re.search(r'\((\d+)\|(\d+)\)', row)
                if coords_match:
                    coords = {'x': int(coords_match.group(1)), 'y': int(coords_match.group(2))}

                # wyodrębnij czas ostatniego ataku z wiersza
                last_attack = None
                time_match = re.search(r'(\d{2}:\d{2}:\d{2})', row)
                if time_match:
                    last_attack = time_match.group(1)

                # wyodrębnij podstawowe zasoby z wiersza; preferuj komórkę zasobów, jeśli obecna
                resources = {}
                try:
                    tds = re.findall(r'(?s)<td[^>]*>(.*?)</td>', row)
                    if len(tds) > 5:
                        resource_text = tds[5]
                        nums = re.findall(r'(\d{1,7})', resource_text)
                        if len(nums) >= 3:
                            resources = {
                                'wood': int(nums[0]),
                                'stone': int(nums[1]),
                                'iron': int(nums[2]),
                            }
                except Exception:
                    resources = {}

                # wykryj mur i odległość z wiersza farm assistenta
                wall_value = wall
                distance_value = None
                if len(tds) > 6:
                    try:
                        wall_text = re.sub(r'<.*?>', '', tds[6]).strip()
                        wall_digits = re.findall(r'-?\d+', wall_text)
                        if wall_digits:
                            wall_value = int(wall_digits[0])
                    except Exception:
                        pass
                if len(tds) > 7:
                    try:
                        dist_text = re.sub(r'<.*?>', '', tds[7]).strip()
                        if dist_text and dist_text != '?':
                            distance_value = float(dist_text.replace(',', '.'))
                    except Exception:
                        pass

                # dołącz wykryte metadane do celu
                if 'meta' not in target:
                    target['meta'] = {}
                target['meta'].update({
                    'safe': safe,
                    'loot_type': loot_type,
                    'coords': coords,
                    'last_attack': last_attack,
                    'resources': resources,
                    'wall': wall_value,
                    'distance': distance_value,
                })

                # dołącz identyfikator szablonu, jeśli został sparsowany
                if 'links' in target and action.upper() in target['links']:
                    try:
                        if template_id:
                            target['links'][action.upper()].update({'template': template_id})
                    except Exception:
                        pass

        return targets

    @staticmethod
    def farm_assistant_templates(res):
        """
        Wyodrębnia szablony farm assistenta z JavaScript strony farm assistenta.
        """
        if type(res) != str:
            res = res.text
        templates = {}
        for match in re.findall(r"Accountmanager\.farm\.templates\['t_(\d+)'\]\s*=\s*\{\s*\};", res):
            templates[match] = {}
        for tmpl_id, unit, value in re.findall(r"Accountmanager\.farm\.templates\['t_(\d+)'\]\['([^']+)'\]\s*=\s*(\d+);", res):
            templates.setdefault(tmpl_id, {})[unit] = int(value)
        return templates

    @staticmethod
    def farm_assistant_units(res):
        """
        Wyodrębnia dostępne jednostki ze strony farm assistenta.
        """
        if type(res) != str:
            res = res.text
        units = {}
        for unit in [
                'spear', 'sword', 'axe', 'archer', 'spy',
                'light', 'marcher', 'heavy', 'ram', 'catapult',
                'knight', 'snob', 'militia']:
            m = re.search(rf'<td[^>]*id="{unit}"[^>]*data-unit-count="(\d+)"', res)
            if m:
                try:
                    units[unit] = int(m.group(1))
                except Exception:
                    units[unit] = 0
        if not units:
            for unit in [
                    'spear', 'sword', 'axe', 'archer', 'spy',
                    'light', 'marcher', 'heavy', 'ram', 'catapult',
                    'knight', 'snob', 'militia']:
                m = re.search(rf'<td[^>]*id="{unit}"[^>]*>(\d+)</td>', res)
                if m:
                    try:
                        units[unit] = int(m.group(1))
                    except Exception:
                        units[unit] = 0
        return units

    @staticmethod
    def farm_assistant_loot_limit(res):
        """
        Wyodrębnia informacje o limicie łupu ze strony farm assistenta.
        """
        if type(res) != str:
            res = res.text
        match = re.search(r'Zrabowane surowce:\s*</strong>\s*<span>(\d+)</span>/(\d+)\.', res)
        if match:
            try:
                return {
                    'current': int(match.group(1)),
                    'limit': int(match.group(2)),
                }
            except Exception:
                return {}
        return {}

    @staticmethod
    def attack_duration(res):
        """
        Wykrywa czas trwania ataku
        """
        if type(res) != str:
            res = res.text
        data = re.search(r'<span class="relative_time" data-duration="(\d+)"', res)
        if data:
            return int(data.group(1))
        return 0

    @staticmethod
    def report_table(res):
        """
        Pobiera informacje z raportu
        """
        if type(res) != str:
            res = res.text
        data = re.findall(r'(?s)class="report-link" data-id="(\d+)"', res)
        return data

    @staticmethod
    def get_daily_reward(res):
        """
        Wykrywa, czy są nieodebrane codzienne nagrody
        """
        if type(res) != str:
            res = res.text
        get_daily = re.search(r'DailyBonus.init\((\s+\{.*\}),', res)
        res = json.loads(get_daily.group(1))
        reward_count_unlocked = str(res["reward_count_unlocked"])
        if reward_count_unlocked and res["chests"][reward_count_unlocked]["is_collected"]:
            return reward_count_unlocked
        return None
