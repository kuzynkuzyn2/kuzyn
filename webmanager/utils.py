import collections
import json
import os
import subprocess
import sys
import time

import psutil
import threading
import logging
try:
    from webmanager.logbuffer import bot_log_handler
except Exception:
    try:
        from logbuffer import bot_log_handler
    except Exception:
        bot_log_handler = None


class DataReader:
    config_lock = threading.Lock()

    @staticmethod
    def _save_json_atomic(path, data):
        tmp_path = "%s.tmp" % path
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, sort_keys=False, ensure_ascii=False)
        os.replace(tmp_path, path)

    @staticmethod
    def _load_config_template(config_file_path, example_path):
        for _ in range(3):
            try:
                with open(config_file_path, 'r', encoding='utf-8') as config_file:
                    return json.load(config_file, object_pairs_hook=collections.OrderedDict)
            except FileNotFoundError:
                break
            except json.JSONDecodeError:
                time.sleep(0.01)
        try:
            with open(example_path, 'r', encoding='utf-8') as example_file:
                return json.load(example_file, object_pairs_hook=collections.OrderedDict)
        except (FileNotFoundError, json.JSONDecodeError):
            return collections.OrderedDict()

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
        example = {}
        if os.path.exists(example_path):
            try:
                with open(example_path, 'r') as f:
                    example = json.load(f)
            except json.JSONDecodeError:
                example = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
            except json.JSONDecodeError:
                config = {}

            if isinstance(config, dict) and isinstance(example, dict):
                merged = False
                for section, section_data in example.items():
                    if section not in config or not isinstance(config.get(section), dict):
                        config[section] = section_data
                        merged = True
                    else:
                        if isinstance(section_data, dict):
                            for param, param_value in section_data.items():
                                if param not in config[section]:
                                    config[section][param] = param_value
                                    merged = True
                if merged:
                    try:
                        with open(config_path, 'w') as f:
                            json.dump(config, f, indent=2, sort_keys=False)
                    except Exception:
                        pass
            return config
        if example:
            return example
        return {}

    @staticmethod
    def config_set(parameter, value):
        try:
            value = json.loads(value)
        except Exception:
            pass
        config_file_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        example_path = os.path.join(os.path.dirname(__file__), "..", "config.example.json")
        with DataReader.config_lock:
            template = DataReader._load_config_template(config_file_path, example_path)
            if "." in parameter:
                section, param = parameter.split('.', 1)
                if section not in template or not isinstance(template[section], dict):
                    template[section] = collections.OrderedDict()
                template[section][param] = value
            else:
                template[parameter] = value
            DataReader._save_json_atomic(config_file_path, template)
        print("Zapisano nowy plik konfiguracyjny")
        return True

    @staticmethod
    def village_config_set(village_id, parameter, value):
        config_file_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        example_path = os.path.join(os.path.dirname(__file__), "..", "config.example.json")
        with DataReader.config_lock:
            template = DataReader._load_config_template(config_file_path, example_path)
            if 'villages' not in template or not isinstance(template['villages'], dict):
                template['villages'] = collections.OrderedDict()
            if str(village_id) not in template['villages']:
                template['villages'][str(village_id)] = collections.OrderedDict()
            try:
                template['villages'][str(village_id)][parameter] = json.loads(value)
            except json.decoder.JSONDecodeError:
                template['villages'][str(village_id)][parameter] = value
            DataReader._save_json_atomic(config_file_path, template)
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
    def build(villages, current_village=None, size=None, center_coords=None):
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

        if center_coords and size:
            min_x = center_coords[0] - size
            min_y = center_coords[1] - size
            max_x = center_coords[0] + size
            max_y = center_coords[1] + size
        elif current_location and size:
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

        result = {
            "grid": out_map,
            "extra": extra_data,
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
        }

        if center_coords:
            result["center_x"] = center_coords[0]
            result["center_y"] = center_coords[1]
        elif current_location:
            result["center_x"] = current_location[0]
            result["center_y"] = current_location[1]
        else:
            result["center_x"] = None
            result["center_y"] = None

        if current_location:
            result["current_x"] = current_location[0]
            result["current_y"] = current_location[1]
        else:
            result["current_x"] = None
            result["current_y"] = None

        return result


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
            # Capture stdin/stdout/stderr so we can show logs in web UI and send commands
            self.proc = subprocess.Popen([python_exe, "twb.py"], cwd=wd, shell=False,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            # start a background thread to read subprocess output
            def _reader():
                logger = logging.getLogger("BotSubprocess")
                try:
                    cur = ''
                    partial_in_buffer = False
                    # read one char at a time so we capture prompts without newline
                    while True:
                        ch = self.proc.stdout.read(1)
                        if ch == '':
                            # stream closed
                            if cur:
                                try:
                                    if bot_log_handler is not None:
                                        # if a partial was already in buffer, replace it with final
                                        if partial_in_buffer and len(bot_log_handler.buffer) > 0:
                                            bot_log_handler.buffer.pop()
                                        bot_log_handler.buffer.append(cur)
                                    else:
                                        logger.info(cur)
                                except Exception:
                                    logger.info(cur)
                            break
                        cur += ch
                        if ch == '\n':
                            line = cur.rstrip('\n')
                            try:
                                if bot_log_handler is not None:
                                    # if we had previously appended a partial, remove it
                                    if partial_in_buffer and len(bot_log_handler.buffer) > 0:
                                        bot_log_handler.buffer.pop()
                                    bot_log_handler.buffer.append(line)
                                else:
                                    logger.info(line)
                            except Exception:
                                logger.info(line)
                            cur = ''
                            partial_in_buffer = False
                        else:
                            # update last partial entry so UI can show prompts immediately
                            try:
                                if bot_log_handler is not None:
                                    if not partial_in_buffer:
                                        # append new partial entry
                                        bot_log_handler.buffer.append(cur)
                                        partial_in_buffer = True
                                    else:
                                        # replace last partial with updated text
                                        if len(bot_log_handler.buffer) > 0:
                                            bot_log_handler.buffer.pop()
                                        bot_log_handler.buffer.append(cur)
                                else:
                                    # fallback: log partials to logger at DEBUG level to avoid clutter
                                    logger.debug(cur)
                            except Exception:
                                logger.debug('Failed to write partial bot output')
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

    def send_command(self, cmd: str):
        """Send a command line to the bot subprocess via stdin."""
        if not self.is_running() or not self.proc:
            raise RuntimeError("Bot not running")
        try:
            # ensure newline
            self.proc.stdin.write(cmd.rstrip('\n') + "\n")
            self.proc.stdin.flush()
        except Exception as e:
            raise
