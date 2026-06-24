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
        Gets quest data on almost any page
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
        Detects if there are rewards available for quests
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
        # Return all off them
        return rewards

    @staticmethod
    def map_data(res):
        """
        Detects other villages on the map page
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
        Gets smith data
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
        Detects data on the premium exchange page
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
        Fetches recruit data for the current building
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
        Detects all units in the village
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
        Detects queued building entries
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
        Detects active recruitment entries
        """
        if type(res) != str:
            res = res.text
        builder = re.findall(r'(?s)TrainOverview\.cancelOrder\((\d+)\)', res)
        return builder

    @staticmethod
    def village_ids_from_overview(res):
        """
        Fetches villages from the overview page
        """
        if type(res) != str:
            res = res.text
        villages = re.findall(r'<span class="quickedit-vn" data-id="(\w+)"', res)
        return list(set(villages))

    @staticmethod
    def units_in_total(res):
        """
        Gets total amount of units in a village
        """
        if type(res) != str:
            res = res.text
        # hide units from other villages
        res = re.sub(r'(?s)<span class="village_anchor.+?</tr>', '', res)
        data = re.findall(r'(?s)class=\Wunit-item unit-item-([a-z]+)\W.+?(\d+)</td>', res)
        return data

    @staticmethod
    def attack_form(res):
        """
        Detects input fiels in the attack form
        ... because there are many :)
        """
        if type(res) != str:
            res = res.text
        data = re.findall(r'(?s)<input.+?name="(.+?)".+?value="(.*?)"', res)
        return data

    @staticmethod
    def farm_assistant_pagination(res):
        """
        Detects additional farm assistant pages from pagination
        """
        if type(res) != str:
            res = res.text
        return re.findall(r'<a[^>]+class="[^"]*paged-nav-item[^"]*"[^>]+href="([^"]+)"', res)

    @staticmethod
    def farm_assistant_targets(res):
        """
        Extracts available farm assistant target links and wall levels
        """
        if type(res) != str:
            res = res.text
        targets = {}
        # try to detect current village id from page to build proper place links
        cur_vid = None
        m_vid = re.search(r'"village"\s*:\s*\{[^}]*?"id"\s*:\s*(\d+)', res)
        if m_vid:
            cur_vid = m_vid.group(1)
        rows = re.findall(r'(?s)<tr[^>]*>(.*?)</tr>', res)
        for row in rows:
            # quick skip if no farm related tokens
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

            # find all anchor tags in the row including attributes and inner HTML
            anchors = re.findall(r'(?s)<a([^>]*)>(.*?)</a>', row)
            for attrs, inner in anchors:
                action = None
                href = None
                onclick = None
                # extract attributes
                href_m = re.search(r'href="([^"\']*)"', attrs)
                if href_m:
                    href = href_m.group(1)
                onclick_m = re.search(r'onclick="([^"\']*)"', attrs)
                if onclick_m:
                    onclick = onclick_m.group(1)

                # detect action letter from class attribute or from attributes string
                class_m = re.search(r'class="([^"]*)"', attrs)
                if class_m:
                    cls = class_m.group(1)
                    m = re.search(r'farm[_-]?icon[_-]?([abc])', cls, re.I)
                    if m:
                        action = m.group(1)

                # fallback: look inside inner HTML or the whole row
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
                # prefer onclick pattern that contains sendUnits(village, template)
                if onclick:
                    m = re.search(r'sendUnits\s*\(\s*this\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', onclick)
                    if not m:
                        # sometimes this is without 'this'
                        m = re.search(r'sendUnits\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)', onclick)
                    if m:
                        vid = m.group(1)
                        # template = m.group(2)  # template id if needed

                # if no vid from onclick, try common href params
                if not vid and href:
                    for regex in [r'farm[_-]?icon[_-]?[abc]=(\d+)', r'target=(\d+)', r'village=(\d+)', r'target_id=(\d+)']:
                        mm = re.search(regex, href)
                        if mm:
                            vid = mm.group(1)
                            break
                # fallback: any 4-7 digit number in href
                if not vid and href:
                    mm2 = re.search(r'(\d{4,7})', href)
                    if mm2:
                        vid = mm2.group(1)

                if not vid:
                    continue

                # build a usable link: use place screen so the attacker can load the normal attack form
                if href and href != '#':
                    usable_link = href
                else:
                    if cur_vid:
                        usable_link = f"game.php?village={cur_vid}&screen=place&target={vid}"
                    else:
                        usable_link = f"game.php?village=0&screen=place&target={vid}"
                # store raw attributes so caller can choose how to trigger the click
                target = targets.setdefault(str(vid), {'wall': wall, 'links': {}})
                target['links'][action.upper()] = {
                    'href': href,
                    'onclick': onclick,
                    'usable': usable_link,
                }

                # try to detect safety/report status within the row
                # default to safe=True unless we detect hostile markers
                safe = True
                # look for common classes or text that indicate danger/unsafe
                if re.search(r'report[-_ ]?(state|status)[^>]*>([^<]+)', row, re.I):
                    mtxt = re.search(r'report[-_ ]?(state|status)[^>]*>([^<]+)', row, re.I)
                    if mtxt and re.search(r'red|danger|enemy|hostile|units|niebezpie', mtxt.group(2), re.I):
                        safe = False
                if re.search(r'class="[^"]*(report|report-state|report-icon)[^"]*(red|danger|bad)[^"]*"', row, re.I):
                    safe = False

                # extract simple resource heuristics: find up to 3 numbers in the row which often correspond to wood/stone/iron
                resources = {}
                nums = re.findall(r'>(\d{1,7})<', row)
                if len(nums) >= 3:
                    try:
                        resources = {
                            'wood': int(nums[0]),
                            'stone': int(nums[1]),
                            'iron': int(nums[2])
                        }
                    except Exception:
                        resources = {}
                # attach detected metadata to target
                if 'meta' not in target:
                    target['meta'] = {}
                target['meta'].update({'safe': safe, 'resources': resources})

        return targets

    @staticmethod
    def attack_duration(res):
        """
        Detects the duration of an attack
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
        Fetches information from a report
        """
        if type(res) != str:
            res = res.text
        data = re.findall(r'(?s)class="report-link" data-id="(\d+)"', res)
        return data

    @staticmethod
    def get_daily_reward(res):
        """
        Detects if there are unopened daily rewards
        """
        if type(res) != str:
            res = res.text
        get_daily = re.search(r'DailyBonus.init\((\s+\{.*\}),', res)
        res = json.loads(get_daily.group(1))
        reward_count_unlocked = str(res["reward_count_unlocked"])
        if reward_count_unlocked and res["chests"][reward_count_unlocked]["is_collected"]:
            return reward_count_unlocked
        return None
