"""
Menedżer ataków
Brzmmi niebezpiecznie, ale to tylko wysyła farmy
"""

from core.extractors import Extractor
import re
import logging
import time
from datetime import datetime
from datetime import timedelta

from core.filemanager import FileManager


class AttackManager:
    """
    Klasa menedżera ataków
    """
    map = None
    village_id = None
    troopmanager = None
    wrapper = None
    targets = {}
    logger = logging.getLogger("Attacks")
    max_farms = 15
    template = {}
    extra_farm = []
    repman = None
    target_high_points = False
    farm_radius = 50
    farm_minpoints = 0
    farm_maxpoints = 1000
    ignored = []
    farm_assistant = False
    farm_assistant_targets = {}
    farm_assistant_targets_loaded = False
    farm_assistant_templates = {}
    farm_assistant_units = {}
    farm_assistant_loot_limit = {}
    farm_assistant_rules = []

    # Konfiguruje liczbę zwiadowców używanych do wykrycia, czy wsie są bezpieczne do farmy
    scout_farm_amount = 5

    forced_peace_time = None

    # blokuje wsie, które nie mogą być atakowane w tej chwili (zbyt niskie punkty, ochrona początkujących itp..)
    _unknown_ignored = []

    # Nie mieszaj z nimi, są w pliku konfiguracyjnym
    farm_high_prio_wait = 1200
    farm_default_wait = 3600
    farm_low_prio_wait = 7200

    def __init__(self, wrapper=None, village_id=None, troopmanager=None, map=None):
        """
        Utwórz menedżera ataków
        """
        self.wrapper = wrapper
        self.village_id = village_id
        self.troopmanager = troopmanager
        self.map = map

    def enough_in_village(self, units):
        """
        Checks if there are enough troops in a village
        """
        for unit in units:
            if unit not in self.troopmanager.troops:
                return f"{unit} (0/{units[unit]})"
            if units[unit] > int(self.troopmanager.troops[unit]):
                return f"{unit} ({self.troopmanager.troops[unit]}/{units[unit]})"
        return False

    def run(self):
        """
        Run the farming logic
        """
        if not self.troopmanager.can_attack or self.troopmanager.troops == {}:
            # Disable farming is disabled in config or no troops available
            return False
        self.get_targets()
        ignored = []
        # Limits the amount of villages that are farmed from the current village
        for target in self.targets[0: self.max_farms]:
            if type(self.template) == list:
                f = False
                for template in self.template:
                    if template in ignored:
                        continue
                    out_res = self.send_farm(target, template)
                    if out_res == 1:
                        f = True
                        break
                    elif out_res == -1:
                        ignored.append(template)
                if not f:
                    continue
            else:
                out_res = self.send_farm(target, self.template)
                if out_res == -1:
                    break

    def send_farm(self, target, template):
        """
        Send a farming run
        """
        target, _ = target
        missing = self.enough_in_village(template)
        if not missing:
            cached = self.can_attack(vid=target["id"], clear=False)
            if cached:
                if self.farm_assistant:
                    attack_result = self.attack_with_assistant(target["id"], troops=template)
                else:
                    attack_result = self.attack(target["id"], troops=template)
                if attack_result == "forced_peace":
                    return 0
                self.logger.info(
                    "Attacking %s -> %s (%s)" ,self.village_id, target["id"], str(template)
                )
                self.wrapper.reporter.report(
                    self.village_id,
                    "TWB_FARM",
                    "Attacking %s -> %s (%s)"
                    % (self.village_id, target["id"], str(template)),
                )
                if attack_result:
                    for u in template:
                        self.troopmanager.troops[u] = str(
                            int(self.troopmanager.troops[u]) - template[u]
                        )
                    # this was an actual attack send (not a scout), mark as such
                    self.attacked(
                        target["id"],
                        scout=False,
                        safe=True,
                        high_profile=cached["high_profile"]
                        if type(cached) == dict
                        else False,
                        low_profile=cached["low_profile"]
                        if type(cached) == dict and "low_profile" in cached
                        else False,
                    )
                    return 1
                else:
                    self.logger.debug(
                        "Ignoring target %s because unable to attack", target["id"]
                    )
                    self._unknown_ignored.append(target["id"])
        else:
            self.logger.debug(
                "Not sending additional farm because not enough units: %s", missing
            )
            return -1
        return 0

    def get_targets(self):
        """
        Gets all possible farming targets based on distance
        """
        output = []
        my_village = (
            self.map.villages[self.village_id]
            if self.village_id in self.map.villages
            else None
        )
        for vid in self.map.villages:
            village = self.map.villages[vid]
            if village["owner"] != "0" and vid not in self.extra_farm:
                if vid not in self.ignored:
                    self.logger.debug(
                        "Ignoring village %s because player owned, add to additional_farms to auto attack", vid
                    )
                    self.ignored.append(vid)
                continue
            if my_village and "points" in my_village and "points" in village:
                if village["points"] >= self.farm_maxpoints:
                    if vid not in self.ignored:
                        self.logger.debug(
                            "Ignoring village %s because points %d exceeds limit %d",
                            vid, village["points"], self.farm_maxpoints
                        )
                        self.ignored.append(vid)
                    continue
                if village["points"] <= self.farm_minpoints:
                    if vid not in self.ignored:
                        self.logger.debug(
                            "Ignoring village %s because points %d below limit %d",
                            vid, village["points"], self.farm_minpoints
                        )
                        self.ignored.append(vid)
                    continue
                if (
                        village["points"] >= my_village["points"]
                        and not self.target_high_points
                ):
                    if vid not in self.ignored:
                        self.logger.debug(
                            "Ignoring village %s because of higher points %d -> %d",
                            vid, my_village["points"], village["points"]
                        )
                        self.ignored.append(vid)
                    continue
                if vid in self._unknown_ignored:
                    continue
            if village["owner"] != "0":
                get_h = time.localtime().tm_hour
                if get_h in range(0, 8) or get_h == 23:
                    self.logger.debug(
                        "Village %s will be ignored because it is player owned and attack between 23h-8h", vid
                    )
                    continue
            distance = self.map.get_dist(village["location"])
            if distance > self.farm_radius:
                if vid not in self.ignored:
                    self.logger.debug(
                        "Village %s will be ignored because it is too far away: distance is %f, max is %d",
                        vid, distance, self.farm_radius
                    )
                    self.ignored.append(vid)
                continue
            if vid in self.ignored:
                self.logger.debug("Removed %s from farm ignore list", vid)
                self.ignored.remove(vid)

            output.append([village, distance])
        self.logger.info(
            "Farm targets: %d Ignored targets: %d", len(output), len(self.ignored)
        )
        self.targets = sorted(output, key=lambda x: x[1])

    def attacked(self, vid, scout=False, high_profile=False, safe=True, low_profile=False):
        """
        The farm was sent and this is a callback on what happened
        """
        cache_entry = {
            "scout": scout,
            "safe": safe,
            "high_profile": high_profile,
            "low_profile": low_profile,
            "last_attack": int(time.time()),
        }
        AttackCache.set_cache(vid, cache_entry)

    def scout(self, vid):
        """
        Attempt to send scouts to a farm
        """
        if "spy" not in self.troopmanager.troops or int(self.troopmanager.troops["spy"]) < self.scout_farm_amount:
            self.logger.debug(
                "Cannot scout %s at the moment because insufficient unit: spy", vid
            )
            return False
        troops = {"spy": self.scout_farm_amount}
        if self.attack(vid, troops=troops):
            self.attacked(vid, scout=True, safe=False)

    def can_attack(self, vid, clear=False):
        """
        Checks if it is safe en engage
        If not an amount of 5 scouts will be sent
        """
        cache_entry = AttackCache.get_cache(vid)

        # If farm assistant mode is enabled, prefer using data from am_farm
        if self.farm_assistant:
            try:
                self.ensure_farm_assistant_targets()
                ta = self.farm_assistant_targets.get(str(vid))
                if ta:
                    # compute min_time similar to normal cache logic
                    min_time = self.farm_default_wait
                    if cache_entry:
                        if cache_entry.get('high_profile'):
                            min_time = self.farm_high_prio_wait
                        if cache_entry.get('low_profile'):
                            min_time = self.farm_low_prio_wait
                        if cache_entry.get('last_attack') and cache_entry['last_attack'] + min_time > int(time.time()):
                            self.logger.debug(
                                "%s will be ignored because of previous attack (%d sec delay between attacks)",
                                vid, min_time
                            )
                            return False

                    safe = True
                    if 'meta' in ta and 'safe' in ta['meta']:
                        safe = ta['meta']['safe']

                    if safe:
                        self.logger.debug("%s considered safe by farm assistant data", vid)
                        return True
                    else:
                        self.logger.info("%s considered unsafe by farm assistant data, skipping", vid)
                        return False
            except Exception:
                # on any parsing error, fall back to existing behaviour
                pass

        if cache_entry and cache_entry["last_attack"]:
            last_attack = datetime.fromtimestamp(cache_entry["last_attack"])
            now = datetime.now()
            if last_attack < now - timedelta(hours=12):
                self.logger.debug(f"Attacked long ago %s, trying scout attack", {last_attack})
                if self.scout(vid):
                    return False

        if not cache_entry:
            status = self.repman.safe_to_engage(vid)
            if status == 1:
                return True

            # only attempt to scout if we actually have spies available
            troops = getattr(self.troopmanager, 'troops', {}) or {}
            try:
                spy_count = int(troops.get('spy', 0))
            except Exception:
                spy_count = 0

            if self.troopmanager.can_scout and spy_count >= self.scout_farm_amount:
                self.scout(vid)
                return False

            # no scouts available to perform a safe check; warn and proceed blind
            self.logger.warning(
                "%s will be attacked but scouting not possible (insufficient spies), proceeding blind!", vid
            )
            return True

        if not cache_entry["safe"] or clear:
            if cache_entry["scout"] and self.repman:
                status = self.repman.safe_to_engage(vid)
                if status == -1:
                    self.logger.info(
                        "Checking %s: scout report not yet available", vid
                    )
                    return False
                if status == 0:
                    if cache_entry["last_attack"] + self.farm_low_prio_wait * 2 > int(time.time()):
                        self.logger.info(f"{vid}: Old scout report found ({cache_entry['last_attack']}), re-scouting")
                        self.scout(vid)
                        return False
                    else:
                        self.logger.info(
                            "%s: scout report noted enemy units, ignoring", vid
                        )
                        return False
                self.logger.info(
                    "%s: scout report noted no enemy units, attacking", vid
                )
                return True

            self.logger.debug(
                "%s will be ignored for attack because unsafe, set safe:true to override", vid
            )
            return False

        if not cache_entry["scout"] and self.troopmanager.can_scout:
            self.scout(vid)
            return False
        min_time = self.farm_default_wait
        if cache_entry["high_profile"]:
            min_time = self.farm_high_prio_wait
        if "low_profile" in cache_entry and cache_entry["low_profile"]:
            min_time = self.farm_low_prio_wait

        if cache_entry and self.repman:
            res_left, res = self.repman.has_resources_left(vid)
            total_loot = 0
            for x in res:
                total_loot += int(res[x])

            if res_left and total_loot > 100:
                self.logger.debug(f"Draining farm of resources! Sending attack to get {res}.")
                min_time = int(self.farm_high_prio_wait / 2)

        if cache_entry["last_attack"] + min_time > int(time.time()):
            self.logger.debug(
                "%s will be ignored because of previous attack (%d sec delay between attacks)",
                vid, min_time
            )
            return False
        return cache_entry

    def has_troops_available(self, troops):
        for t in troops:
            if (
                    t not in self.troopmanager.troops
                    or int(self.troopmanager.troops[t]) < troops[t]
            ):
                return False
        return True

    def attack(self, vid, troops=None):
        """
        Send a TW attack
        """
        url = f"game.php?village={self.village_id}&screen=place&target={vid}"
        pre_attack = self.wrapper.get_url(url)
        pre_data = {}
        for u in Extractor.attack_form(pre_attack):
            k, v = u
            pre_data[k] = v
        if troops:
            pre_data.update(troops)
        else:
            pre_data.update(self.troopmanager.troops)

        if vid not in self.map.map_pos:
            return False

        x, y = self.map.map_pos[vid]
        post_data = {"x": x, "y": y, "target_type": "coord", "attack": "Aanvallen"}
        pre_data.update(post_data)

        confirm_url = f"game.php?village={self.village_id}&screen=place&try=confirm"
        conf = self.wrapper.post_url(url=confirm_url, data=pre_data)
        if '<div class="error_box">' in conf.text:
            return False
        duration = Extractor.attack_duration(conf)
        if self.forced_peace_time:
            now = datetime.now()
            if now + timedelta(seconds=duration) > self.forced_peace_time:
                self.logger.info("Attack would arrive after the forced peace timer, not sending attack!")
                return "forced_peace"

        self.logger.info(
            "[Attack] %s -> %s duration %f.1 h", self.village_id, vid, duration / 3600
        )

        confirm_data = {}
        for u in Extractor.attack_form(conf):
            k, v = u
            if k == "support":
                continue
            confirm_data[k] = v
        new_data = {"building": "main", "h": self.wrapper.last_h}
        confirm_data.update(new_data)
        # The extractor doesn't like the empty cb value, and mistakes its value for x. So I add it here.
        if "x" not in confirm_data:
            confirm_data["x"] = x

        result = self.wrapper.get_api_action(
            village_id=self.village_id,
            action="popup_command",
            params={"screen": "place"},
            data=confirm_data,
        )

        return result

    def ensure_farm_assistant_targets(self):
        if self.farm_assistant_targets_loaded:
            return
        self.farm_assistant_targets = {}
        self.farm_assistant_templates = {}
        url = f"game.php?village={self.village_id}&screen=am_farm"
        page = self.wrapper.get_url(url)
        if not page:
            return
        # capture Accountmanager AJAX endpoints if available for direct farm sends
        try:
            txt = page.text if hasattr(page, 'text') else str(page)
            m = re.search(r"Accountmanager\.send_units_link\s*=\s*'([^']+)'", txt)
            if m:
                link = m.group(1)
                # normalize leading slash
                if link.startswith('/'):
                    link = link[1:]
                self.send_units_link = link
            else:
                self.send_units_link = None
        except Exception:
            self.send_units_link = None

        self.farm_assistant_targets.update(Extractor.farm_assistant_targets(page))
        self.farm_assistant_templates.update(Extractor.farm_assistant_templates(page))
        self.farm_assistant_units.update(Extractor.farm_assistant_units(page))
        loot_limit = Extractor.farm_assistant_loot_limit(page)
        if loot_limit:
            self.farm_assistant_loot_limit = loot_limit
        # if no targets found, dump the page for inspection
        if not self.farm_assistant_targets:
            try:
                FileManager.save_text_file(page.text if hasattr(page, 'text') else str(page), f"cache/debug/farm_assistant_{self.village_id}.html")
                self.logger.debug("Saved farm assistant page to cache/debug/farm_assistant_%s.html for inspection", self.village_id)
            except Exception:
                pass
        # debug: log how many targets were found on first page
        try:
            self.logger.debug("Loaded %d farm assistant targets from %s", len(self.farm_assistant_targets), url)
            self.logger.debug("Loaded %d farm assistant templates from %s", len(self.farm_assistant_templates), url)
            self.logger.debug("Loaded %d farm assistant available units from %s", len(self.farm_assistant_units), url)
            self.logger.debug("Farm assistant loot limit for %s: %s", self.village_id, self.farm_assistant_loot_limit)
        except Exception:
            pass
        for pagination_url in Extractor.farm_assistant_pagination(page):
            next_page = self.wrapper.get_url(pagination_url)
            if next_page:
                self.farm_assistant_targets.update(Extractor.farm_assistant_targets(next_page))
                self.farm_assistant_templates.update(Extractor.farm_assistant_templates(next_page))
                try:
                    self.logger.debug("Loaded %d farm assistant targets after page %s", len(self.farm_assistant_targets), pagination_url)
                except Exception:
                    pass
        self.farm_assistant_targets_loaded = True
        target_keys = list(self.farm_assistant_targets.keys())
        if target_keys:
            self.logger.info(
                "Farm assistant targets loaded for village %s: %d (%s%s)",
                self.village_id,
                len(target_keys),
                ", ".join(target_keys[:10]),
                "..." if len(target_keys) > 10 else "",
            )
        else:
            self.logger.info("No farm assistant targets found for village %s on am_farm", self.village_id)
        template_keys = list(self.farm_assistant_templates.keys())
        if template_keys:
            self.logger.debug(
                "Farm assistant templates loaded for village %s: %d (%s%s)",
                self.village_id,
                len(template_keys),
                ", ".join(template_keys[:10]),
                "..." if len(template_keys) > 10 else "",
            )
        if self.farm_assistant_units:
            self.logger.debug(
                "Farm assistant available units for village %s: %s",
                self.village_id,
                self.farm_assistant_units,
            )
        if self.farm_assistant_loot_limit:
            self.logger.debug(
                "Farm assistant loot limit for village %s: %s",
                self.village_id,
                self.farm_assistant_loot_limit,
            )

        # Log per-target metadata counts for farm assistant targets
        for vid, target in self.farm_assistant_targets.items():
            if isinstance(target, dict):
                meta = target.get('meta', {})
                self.logger.debug(
                    "Farm assistant target %s meta fields processed: %d %s",
                    vid,
                    len(meta),
                    sorted(meta.keys()) if isinstance(meta, dict) else meta,
                )

    def get_farm_assistant_link(self, vid):
        self.ensure_farm_assistant_targets()
        vid = str(vid)
        target = self.farm_assistant_targets.get(vid)
        if not target:
            self.logger.debug("No farm assistant target entry for %s", vid)
            return None
        wall = target.get("wall", 0)
        # Evaluate conditional rules first (if any)
        try:
            rules = getattr(self, 'farm_assistant_rules', []) or []
            def _cmp(op, left, right):
                try:
                    if op == '<':
                        return left < right
                    if op == '>':
                        return left > right
                    if op == '<=':
                        return left <= right
                    if op == '>=':
                        return left >= right
                    if op == '==':
                        return left == right
                except Exception:
                    return False
                return False

            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                match = True
                # Legacy style rules using min_/max_ keys
                if 'min_wall' in rule and wall < int(rule.get('min_wall', 0)):
                    match = False
                if 'max_wall' in rule and wall > int(rule.get('max_wall', 0)):
                    match = False

                dist = None
                target_meta = target.get('meta', {}) if isinstance(target, dict) else {}
                if 'distance' in target_meta and target_meta['distance'] is not None:
                    try:
                        dist = float(target_meta['distance'])
                    except Exception:
                        dist = None
                elif getattr(self, 'map', None) and vid in getattr(self.map, 'map_pos', {}):
                    try:
                        coords = self.map.map_pos[vid]
                        dist = self.map.get_dist(coords)
                    except Exception:
                        dist = None

                # Legacy distance
                if 'min_distance' in rule and (dist is None or dist < float(rule.get('min_distance'))):
                    match = False
                if 'max_distance' in rule and (dist is None or dist > float(rule.get('max_distance'))):
                    match = False

                # Legacy last_attack
                since = None
                if 'min_last_attack' in rule or 'max_last_attack' in rule:
                    try:
                        cache_entry = AttackCache.get_cache(vid)
                        last = cache_entry.get('last_attack', 0) if cache_entry else 0
                        import time as _time
                        since = int(_time.time()) - int(last) if last else None
                    except Exception:
                        since = None
                    if 'min_last_attack' in rule and (since is None or since < int(rule.get('min_last_attack', 0))):
                        match = False
                    if 'max_last_attack' in rule and (since is None or since > int(rule.get('max_last_attack', 0))):
                        match = False

                # New style: field/op/value
                if 'field' in rule and 'op' in rule and 'value' in rule:
                    field = rule.get('field')
                    op = rule.get('op')
                    val = rule.get('value')
                    if field == 'wall':
                        if not _cmp(op, wall, float(val)):
                            match = False
                    elif field == 'distance':
                        if dist is None or not _cmp(op, dist, float(val)):
                            match = False
                    elif field == 'last_attack':
                        try:
                            cache_entry = AttackCache.get_cache(vid)
                            last = cache_entry.get('last_attack', 0) if cache_entry else 0
                            import time as _time
                            since = int(_time.time()) - int(last) if last else None
                        except Exception:
                            since = None
                        if since is None or not _cmp(op, since, float(val)):
                            match = False

                if match and 'button' in rule:
                    desired = str(rule.get('button')).upper()
                    if desired in target.get('links', {}):
                        self.logger.debug("Rule matched for %s -> using button %s (%s)", vid, desired, rule)
                        return desired, target['links'][desired]
        except Exception:
            pass

        def _is_disabled(link):
            if not isinstance(link, dict):
                return False
            return bool(link.get('disabled'))

        for option in ["A", "B", "C"]:
            link = target["links"].get(option)
            if link and not _is_disabled(link):
                self.logger.debug("Using farm assistant link for %s button %s -> %s", vid, option, link)
                return option, link

        self.logger.debug("No enabled farm assistant button available for %s", vid)
        return None

    def _save_farm_assistant_debug(self, vid, target, report):
        """Save a farm assistant debug report for later analysis."""
        filename = f"cache/debug/farm_assistant_debug_{self.village_id}_{vid}_{int(time.time())}.json"
        payload = {
            'village': self.village_id,
            'target': vid,
            'target_meta': target.get('meta', {}) if isinstance(target, dict) else None,
            'target_links': target.get('links', {}) if isinstance(target, dict) else None,
            'report': report,
            'timestamp': int(time.time()),
        }
        try:
            FileManager.save_json_file(payload, filename)
            self.logger.debug("Zapisano farm assistant debug do %s", filename)
        except Exception as e:
            self.logger.warning("Nie udało się zapisać debugu farm assistant dla %s: %s", vid, e)

    def _debug_failed_farm_assistant_send(self, vid, target, buttons):
        report = []
        for btn in buttons:
            link = target['links'][btn] if isinstance(target, dict) and target.get('links') else None
            attempts = []
            success = self._attempt_link(btn, link, vid, attempts)
            report.append({'button': btn, 'success': success, 'attempts': attempts})
            if success:
                self.logger.info("Farm assistant debug retry dla %s powiodła się przy użyciu %s", vid, btn)
                self._save_farm_assistant_debug(vid, target, report)
                return True
        self.logger.warning("Farm assistant debug dla %s nie powiódł się. Zapisuję raport.", vid)
        self._save_farm_assistant_debug(vid, target, report)
        return False

    def _attempt_link(self, button, link, target_vid, debug_capture=None):
        href = link.get('href') if isinstance(link, dict) else None
        onclick = link.get('onclick') if isinstance(link, dict) else None
        tpl = link.get('template') if isinstance(link, dict) else None
        if getattr(self, 'send_units_link', None) and tpl:
            send_url = self.send_units_link
            payloads = [
                {'target': target_vid, 'template': tpl},
                {'target': target_vid, 'template_id': tpl},
                {'id': target_vid, 'template_id': tpl},
                {'village': self.village_id, 'target': target_vid, 'template_id': tpl},
                {'source_village': self.village_id, 'target': target_vid, 'template_id': tpl},
            ]
            for data in payloads:
                try:
                    resp = self.wrapper.post_url(url=send_url, data=data)
                    if debug_capture is not None:
                        entry = {
                            'method': 'POST',
                            'url': send_url,
                            'data': data,
                            'status_code': getattr(resp, 'status_code', None) if resp else None,
                            'response_text': (resp.text[:2000] if resp and hasattr(resp, 'text') else None),
                        }
                    if not resp:
                        if debug_capture is not None:
                            entry['error'] = 'no response'
                            debug_capture.append(entry)
                        continue
                    json_ok = False
                    try:
                        j = resp.json()
                        if debug_capture is not None:
                            entry['json'] = j
                    except Exception:
                        j = None
                        if debug_capture is not None:
                            entry['json_error'] = True
                    if debug_capture is not None:
                        debug_capture.append(entry)
                    if isinstance(j, dict):
                        if j.get('error'):
                            self.logger.debug(
                                "Farm assistant AJAX %s for %s payload %s returned error: %s",
                                send_url,
                                target_vid,
                                data,
                                j,
                            )
                            continue
                        if 'success' in j and bool(j.get('success')):
                            self.logger.debug(
                                "Triggered farm assistant AJAX %s for %s with payload %s (json success)",
                                send_url,
                                target_vid,
                                data,
                            )
                            return True
                        if 'data' in j:
                            self.logger.debug(
                                "Triggered farm assistant AJAX %s for %s with payload %s (json data)",
                                send_url,
                                target_vid,
                                data,
                            )
                            return True
                    if resp.status_code == 200 and not json_ok and 'error' not in (resp.text or '').lower():
                        self.logger.debug(
                            "Triggered farm assistant AJAX %s for %s with payload %s (text success)",
                            send_url,
                            target_vid,
                            data,
                        )
                        return True
                    if resp.status_code == 200 and json_ok:
                        self.logger.debug(
                            "Farm assistant AJAX %s for %s payload %s returned non-success json: %s",
                            send_url,
                            target_vid,
                            data,
                            resp.text,
                        )
                except Exception as e:
                    if debug_capture is not None:
                        debug_capture.append({
                            'method': 'POST',
                            'url': send_url,
                            'data': data,
                            'error': str(e),
                        })
                    self.logger.debug(
                        "Farm assistant AJAX request failed for %s with payload %s: %s",
                        target_vid,
                        data,
                        e,
                    )
                    continue
        attempts = []
        if isinstance(link, dict):
            if link.get('href') and 'screen=am_farm' in (link.get('href') or ''):
                attempts.append(link.get('href'))
            if link.get('onclick') and re.search(r'sendUnits', link.get('onclick')):
                attempts.append(f"game.php?village={self.village_id}&screen=am_farm&farm_icon_{button.lower()}={target_vid}")
                if tpl:
                    attempts.append(f"game.php?village={self.village_id}&screen=am_farm&template={tpl}")
                    attempts.append(f"game.php?village={self.village_id}&screen=am_farm&send=1&target={target_vid}&template={tpl}")
                attempts.append(f"game.php?village={self.village_id}&screen=am_farm&farm_village={target_vid}")
        ajax_headers = dict(self.wrapper.headers)
        ajax_headers.update({
            'Accept': "application/json, text/javascript, */*; q=0.01",
            'X-Requested-With': "XMLHttpRequest",
            'TribalWars-Ajax': "1",
            'tribalwars-ajax': "1",
        })
        for url in attempts:
            try:
                resp = self.wrapper.get_url(url, headers=ajax_headers)
                if debug_capture is not None:
                    entry = {
                        'method': 'GET',
                        'url': url,
                        'status_code': getattr(resp, 'status_code', None) if resp else None,
                        'response_text': (resp.text[:2000] if resp and hasattr(resp, 'text') else None),
                    }
                if not resp:
                    if debug_capture is not None:
                        entry['error'] = 'no response'
                        debug_capture.append(entry)
                    continue
                text = resp.text if hasattr(resp, 'text') else ''
                ctype = ''
                try:
                    ctype = resp.headers.get('Content-Type', '')
                except Exception:
                    pass
                is_json = False
                if 'application/json' in ctype or text.strip().startswith('{') or text.strip().startswith('['):
                    is_json = True
                if is_json or 'json=1' in url or 'ajaxaction' in url:
                    try:
                        j = resp.json()
                        if debug_capture is not None:
                            entry['json'] = j
                    except Exception:
                        j = None
                        if debug_capture is not None:
                            entry['json_error'] = True
                    if debug_capture is not None:
                        debug_capture.append(entry)
                    if isinstance(j, dict):
                        if j.get('error'):
                            self.logger.debug("Farm assistant URL %s for %s returned error %s", url, target_vid, j)
                            continue
                        if 'success' in j and bool(j.get('success')):
                            self.logger.debug("Triggered farm assistant URL %s for %s (json success)", url, target_vid)
                            return True
                        if 'data' in j:
                            self.logger.debug("Triggered farm assistant URL %s for %s (json data)", url, target_vid)
                            return True
                    if 'ok' in text.lower() or 'success' in text.lower():
                        self.logger.debug("Triggered farm assistant URL %s for %s (text ok)", url, target_vid)
                        return True
                else:
                    if debug_capture is not None:
                        entry['note'] = 'ignored non-AJAX GET'
                        debug_capture.append(entry)
                    self.logger.debug("Ignored non-AJAX GET %s for %s (not treated as send)", url, target_vid)
                    continue
            except Exception as e:
                if debug_capture is not None:
                    debug_capture.append({
                        'method': 'GET',
                        'url': url,
                        'error': str(e),
                    })
                continue
        return False

    def attack_with_assistant(self, vid, troops=None):
        res = self.get_farm_assistant_link(vid)
        if not res:
            self.logger.info("Brak dostępnego farm assistant linku dla %s, nie można wysłać ataku", vid)
            return False
        # farm assistant helper moved to a class method

        button, link = res
        target = self.farm_assistant_targets.get(str(vid)) if hasattr(self, 'farm_assistant_targets') else None
        buttons = []
        if not (getattr(self, 'farm_assistant_rules', None) or []):
            if isinstance(target, dict):
                buttons = [b for b in ['A', 'B', 'C'] if b in target.get('links', {}) and not target['links'][b].get('disabled')]
            else:
                buttons = [button]
        else:
            buttons = [button]

        coord_text = None
        if isinstance(target, dict) and 'meta' in target and isinstance(target['meta'], dict):
            coords = target['meta'].get('coords')
            if coords and 'x' in coords and 'y' in coords:
                coord_text = f"({coords['x']}|{coords['y']})"
        if not coord_text:
            coord_text = str(vid)

        if not buttons:
            self.logger.info("Brak dostępnych przycisków farm assistant dla %s, nie można wysłać ataku", coord_text)
            return False

        for btn in buttons:
            link = target['links'][btn] if isinstance(target, dict) and target.get('links') else link
            tpl = link.get('template') if isinstance(link, dict) else None
            if tpl and tpl in self.farm_assistant_templates and self.troopmanager:
                template_units = self.farm_assistant_templates.get(tpl, {})
                missing = self.enough_in_village(template_units)
                if missing:
                    self.logger.info(
                        "Brak jednostek dla szablonu farm assistant %s przy celu %s: %s",
                        tpl,
                        coord_text,
                        missing,
                    )
                    continue

            self.logger.info("Próba ataku wioski %s przy użyciu %s", coord_text, btn)
            self.logger.debug(
                "Trying farm assistant button %s for %s, target meta fields: %d %s",
                btn,
                vid,
                len(target.get('meta', {}) if isinstance(target, dict) else {}),
                sorted(target.get('meta', {}).keys()) if isinstance(target, dict) else {},
            )
            if _attempt_link(btn, link, vid):
                tpl = link.get('template') if isinstance(link, dict) else None
                if tpl and tpl in self.farm_assistant_templates and self.troopmanager:
                    template_units = self.farm_assistant_templates.get(tpl, {})
                    for u, amount in template_units.items():
                        if u in self.troopmanager.troops:
                            try:
                                self.troopmanager.troops[u] = str(
                                    int(self.troopmanager.troops[u]) - int(amount)
                                )
                            except Exception:
                                pass
                return True

        if self.farm_assistant:
            self.logger.warning("Błąd wysyłki farm assistant dla %s, uruchamiam debug i zapisuję raport", coord_text)
            self._debug_failed_farm_assistant_send(vid, target, buttons)
            return False

        if self.farm_assistant:
            self.logger.debug("Unable to trigger farm assistant action for %s via am_farm patterns", vid)
            return False

        # fallback: use the usable place link (old behaviour)
        usable = link.get('usable') if isinstance(link, dict) else link
        pre_attack = self.wrapper.get_url(usable)
        self.logger.debug("Fetched assistant pre-attack page for %s via %s", vid, usable)
        if not pre_attack:
            return False
        pre_data = {}
        for u in Extractor.attack_form(pre_attack):
            k, v = u
            pre_data[k] = v
        if troops:
            pre_data.update(troops)
        if vid not in self.map.map_pos:
            return False
        x, y = self.map.map_pos[vid]
        if "x" not in pre_data or "y" not in pre_data:
            pre_data.update({"x": x, "y": y, "target_type": "coord"})
        confirm_url = f"game.php?village={self.village_id}&screen=place&try=confirm"
        conf = self.wrapper.post_url(url=confirm_url, data=pre_data)
        if not conf or '<div class="error_box">' in conf.text:
            return False
        confirm_data = {}
        for u in Extractor.attack_form(conf):
            k, v = u
            if k == "support":
                continue
            confirm_data[k] = v
        confirm_data.update({"building": "main", "h": self.wrapper.last_h})
        if "x" not in confirm_data:
            confirm_data["x"] = x
        return self.wrapper.get_api_action(
            village_id=self.village_id,
            action="popup_command",
            params={"screen": "place"},
            data=confirm_data,
        )


class AttackCache:
    @staticmethod
    def get_cache(village_id):
        return FileManager.load_json_file(f"cache/attacks/{village_id}.json")

    @staticmethod
    def set_cache(village_id, entry):
        return FileManager.save_json_file(entry, f"cache/attacks/{village_id}.json")

    @staticmethod
    def cache_grab():
        output = {}

        for existing in FileManager.list_directory("cache/attacks", ends_with=".json"):
            output[existing.replace(".json", "")] = FileManager.load_json_file(f"cache/attacks/{existing}")
        return output
