import collections
import json
import os
import subprocess
import sys

import psutil
import threading
import logging


class DataReader:
    @staticmethod
    def cache_grab(cache_location):
        output = {}
        c_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__),
            "..",
            "cache",
            cache_location
        ))
        if not os.path.isdir(c_path):
            return output
        for existing in os.listdir(c_path):
            existing = str(existing)
            if not existing.endswith(".json"):
                continue
            t_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cache", cache_location, existing))
            try:
                with open(t_path, 'r') as f:
                    output[existing.replace('.json', '')] = json.load(f)
            except FileNotFoundError:
                continue
            except Exception as e:
                print("Cache read error for %s: %s. Removing broken entry" % (t_path, str(e)))
                try:
                    os.remove(t_path)
                except OSError:
                    pass

        return output

    @staticmethod
    def template_grab(template_location):
        output = []
        template_location = template_location.replace('.', '/')
        c_path = os.path.join(os.path.dirname(__file__), "..", template_location)
        for existing in os.listdir(c_path):
            existing = str(existing)
            if not existing.endswith(".txt"):
                continue
            output.append(existing.split('.')[0])
        return output

    @staticmethod
    def config_grab():
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        example_path = os.path.join(os.path.dirname(__file__), "..", "config.example.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        if os.path.exists(example_path):
            try:
                with open(example_path, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {}

    @staticmethod
    def config_set(parameter, value):
        try:
            value = json.loads(value)
        except Exception:
            pass
        config_file_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        example_path = os.path.join(os.path.dirname(__file__), "..", "config.example.json")
        try:
            with open(config_file_path, 'r') as config_file:
                template = json.load(config_file, object_pairs_hook=collections.OrderedDict)
        except (FileNotFoundError, json.JSONDecodeError):
            try:
                with open(example_path, 'r') as example_file:
                    template = json.load(example_file, object_pairs_hook=collections.OrderedDict)
            except (FileNotFoundError, json.JSONDecodeError):
                template = collections.OrderedDict()

        if "." in parameter:
            section, param = parameter.split('.', 1)
            if section not in template or not isinstance(template[section], dict):
                template[section] = collections.OrderedDict()
            template[section][param] = value
        else:
            template[parameter] = value

        with open(config_file_path, 'w') as newcf:
            json.dump(template, newcf, indent=2, sort_keys=False)
            print("Zapisano nowy plik konfiguracyjny")
            return True

    @staticmethod
    def village_config_set(village_id, parameter, value):
        config_file_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        example_path = os.path.join(os.path.dirname(__file__), "..", "config.example.json")
        try:
            with open(config_file_path, 'r') as config_file:
                template = json.load(config_file, object_pairs_hook=collections.OrderedDict)
        except (FileNotFoundError, json.JSONDecodeError):
            try:
                with open(example_path, 'r') as example_file:
                    template = json.load(example_file, object_pairs_hook=collections.OrderedDict)
            except (FileNotFoundError, json.JSONDecodeError):
                template = collections.OrderedDict()

        if 'villages' not in template or not isinstance(template['villages'], dict):
            template['villages'] = collections.OrderedDict()

        if str(village_id) not in template['villages']:
            template['villages'][str(village_id)] = collections.OrderedDict()

        try:
            template['villages'][str(village_id)][parameter] = json.loads(value)
        except json.decoder.JSONDecodeError:
            template['villages'][str(village_id)][parameter] = value

        with open(config_file_path, 'w') as newcf:
            json.dump(template, newcf, indent=2, sort_keys=False)
            print("Zapisano nowy plik konfiguracyjny")
            return True

    @staticmethod
    def get_session():
        c_path = os.path.join(os.path.dirname(__file__), "..", "cache", "session.json")
        if not os.path.exists(c_path):
            return {"raw": "", "endpoint": "None", "server": "None", "world": "None"}
        with open(c_path, 'r') as session_file:
            session_data = json.load(session_file)
            cookies = []
            for c in session_data['cookies']:
                cookies.append("%s=%s" % (c, session_data['cookies'][c]))
            session_data['raw'] = ';'.join(cookies)
            return session_data


class BuildingTemplateManager:

    @staticmethod
    def template_cache_list():
        c_path = os.path.join(os.path.dirname(__file__), "..", "templates", "builder")
        output = {}
        for existing in os.listdir(c_path):
            if not existing.endswith(".txt"):
                continue
            with open(os.path.join(os.path.dirname(__file__), "..", "templates", "builder", existing),
                      'r') as template_file:
                output[existing] = BuildingTemplateManager.template_to_dict(
                    [x.strip() for x in template_file.readlines()])
        return output

    @staticmethod
    def template_to_dict(t_list):
        out_data = {}
        rows = []

        for entry in t_list:
            if entry.startswith('#') or ':' not in entry:
                continue
            building, next_level = entry.split(':')
            next_level = int(next_level)
            old = 0
            if building in out_data:
                old = out_data[building]
            rows.append({'building': building, 'from': old, 'to': next_level})
            out_data[building] = next_level

        return rows


class MapBuilder:

    @staticmethod
    def build(villages, current_village=None, size=None):
        out_map = {}
        min_x = 999
        max_x = 0
        min_y = 999
        max_y = 0

        current_location = None
        grid_vils = {}
        extra_data = {}

        for v in villages:
            vdata = villages[v]
            x, y = vdata['location']
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x

            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y
            if current_village and str(vdata['id']) == str(current_village):
                current_location = vdata['location']
                extra_data['owner'] = vdata['owner']
                extra_data['tribe'] = vdata['tribe']
            grid_vils["%d:%d" % (x, y)] = vdata

        if not villages:
            return {"grid": {}, "extra": extra_data}

        if current_location and size:
            min_x = current_location[0] - size
            min_y = current_location[1] - size
            max_x = current_location[0] + size
            max_y = current_location[1] + size

        for location_x in range(min_x, max_x + 1):
            if location_x not in out_map:
                out_map[location_x - min_x] = {}
            ylocs = {}
            for location_y in range(min_y, max_y + 1):
                location = "%d:%d" % (location_x, location_y)
                if location in grid_vils:
                    ylocs[location_y - min_y] = grid_vils[location]
                else:
                    ylocs[location_y - min_y] = None
            out_map[location_x - min_x] = ylocs

        return {"grid": out_map, "extra": extra_data}


class BotManager:
    """Manage bot lifecycle by running TWB as a separate subprocess."""

    def __init__(self):
        self.proc = None
        self._reader_thread = None

    def is_running(self):
        return bool(self.proc and self.proc.poll() is None)

    def start(self):
        if self.is_running():
            print("Bot jest już uruchomiony")
            return
        try:
            wd = os.path.join(os.path.dirname(__file__), "..")
            python_exe = sys.executable if hasattr(sys, 'executable') else 'python'
            # Capture stdout/stderr so we can show logs in web UI
            self.proc = subprocess.Popen([python_exe, "twb.py"], cwd=wd, shell=False,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            # start a background thread to read subprocess output
            def _reader():
                logger = logging.getLogger("BotSubprocess")
                try:
                    for line in iter(self.proc.stdout.readline, ''):
                        if not line:
                            break
                        logger.info(line.rstrip('\n'))
                except Exception:
                    logger.exception('Error reading bot subprocess output')

            self._reader_thread = threading.Thread(target=_reader, daemon=True)
            self._reader_thread.start()
            print("Bot uruchomiony pomyślnie jako proces")
        except Exception as e:
            print("Nie udało się uruchomić bota:", e)
            self.proc = None

    def stop(self):
        if not self.is_running():
            print("Bot nie jest uruchomiony")
            return
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
                print("Bot zatrzymany pomyślnie")
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
                print("Bot został zabity po przekroczeniu limitu czasu")
        except Exception as e:
            print("Błąd podczas zatrzymywania bota:", e)
        finally:
            self.proc = None
            self._reader_thread = None
