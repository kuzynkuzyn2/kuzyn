import json
import os
import sys
import traceback
import re
# Ensure project root is on sys.path regardless of current working directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from flask import Flask, jsonify, send_from_directory, request, render_template
import logging
import importlib.util

# Try package import first, fallback to loading the module file directly
try:
    from webmanager.logbuffer import bot_log_handler, http_log_handler, get_logs as lb_get_logs
except Exception:
    try:
        # load from same directory as this file
        lb_path = os.path.join(os.path.dirname(__file__), 'logbuffer.py')
        spec = importlib.util.spec_from_file_location('webmanager.logbuffer', lb_path)
        lb_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lb_mod)
        bot_log_handler = getattr(lb_mod, 'bot_log_handler')
        http_log_handler = getattr(lb_mod, 'http_log_handler')
        lb_get_logs = getattr(lb_mod, 'get_logs')
    except Exception:
        # final fallback: no-op implementations
        class _Dummy:
            def get_logs(self, n=0):
                return []

        bot_log_handler = logging.NullHandler()
        http_log_handler = logging.NullHandler()
        lb_get_logs = _Dummy().get_logs

try:
    from webmanager.helpfile import help_file, buildings
    from webmanager.utils import DataReader, BotManager, MapBuilder, BuildingTemplateManager
except ImportError:
    from helpfile import help_file, buildings
    from utils import DataReader, BotManager, MapBuilder, BuildingTemplateManager

bm = BotManager()

app = Flask(__name__)
app.config["DEBUG"] = True

# Attach in-memory log handlers: bot logs and HTTP logs
try:
    # Bot logs should be delivered to bot_log_handler; the bot subprocess logger uses 'BotSubprocess'
    logging.getLogger('BotSubprocess').addHandler(bot_log_handler)
    logging.getLogger('BotSubprocess').setLevel(logging.DEBUG)

    # HTTP/werkzeug logs -> http_log_handler and prevent propagation to root
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.addHandler(http_log_handler)
    werkzeug_logger.setLevel(logging.INFO)
    werkzeug_logger.propagate = False
except Exception:
    pass


def pre_process_bool(key, value, village_id=None):
    if village_id:
        if value:
            return '<button class="btn btn-sm btn-block btn-success" data-village-id="%s" data-type-option="%s" data-type="toggle">Włączony</button>' % (
            village_id, key)
        else:
            return '<button class="btn btn-sm btn-block btn-danger" data-village-id="%s" data-type-option="%s" data-type="toggle">Wyłączony</button>' % (
            village_id, key)
    if value:
        return '<button class="btn btn-sm btn-block btn-success" data-type-option="%s" data-type="toggle">Włączony</button>' % key
    else:
        return '<button class="btn btn-sm btn-block btn-danger" data-type-option="%s" data-type="toggle">Wyłączony</button>' % key


def preprocess_select(key, value, templates, village_id=None):
    output = '<select data-type-option="%s" data-type="select" class="form-control">' % key
    if village_id:
        output = '<select data-type-option="%s" data-village-id="%s" data-type="select" class="form-control">' % (
        key, village_id)

    for template in DataReader.template_grab(templates):
        output += '<option value="%s" %s>%s</option>' % (template, 'selected' if template == value else '', template)
    output += '</select>'
    return output


def pre_process_string(key, value, village_id=None):
    templates = {
        'units.default': 'templates.troops',
        'village.units': 'templates.troops',
        'building.default': 'templates.builder',
        'village_template.units': 'templates.troops',
        'village.building': 'templates.builder',
        'village_template.building': 'templates.builder'
    }
    if key in templates:
        return preprocess_select(key, value, templates[key], village_id)

    if key == 'farm_assistant.farm_assistant_button':
        options = ['AUTO', 'A', 'B', 'C']
        output = '<select data-type-option="%s" data-type="select" class="form-control">' % key
        for option in options:
            output += '<option value="%s" %s>%s</option>' % (option, 'selected' if option == value else '', option)
        output += '</select>'
        return output

    # Render per-button rule field selects
    m_field = re.match(r'farm_assistant\.farm_assistant_rule_([ABC])_field$', key)
    m_op = re.match(r'farm_assistant\.farm_assistant_rule_([ABC])_op$', key)
    if m_field:
        options = ['none', 'wall', 'distance', 'last_attack']
        output = '<select data-type-option="%s" data-type="select" class="form-control">' % key
        for option in options:
            output += '<option value="%s" %s>%s</option>' % (option, 'selected' if option == value else '', option)
        output += '</select>'
        return output
    if m_op:
        options = ["none", "<", ">", "<=", ">=", "=="]
        labels = {"none": "none", "<": "mniejsza (<)", ">": "większa (>)", "<=": "mniejsza lub równa (<=)", ">=": "większa lub równa (>=)", "==": "równa (==)"}
        output = '<select data-type-option="%s" data-type="select" class="form-control">' % key
        for option in options:
            output += '<option value="%s" %s>%s</option>' % (option, 'selected' if option == value else '', labels.get(option, option))
        output += '</select>'
        return output

    if key == 'farm_assistant.farm_assistant_rules':
        # Provide a JSON textarea for defining conditional rules
        try:
            pretty = json.dumps(value, indent=2, ensure_ascii=False)
        except Exception:
            pretty = str(value)
        if village_id:
            return '<textarea class="form-control" rows="6" data-village-id="%s" data-type="text" data-type-option="%s">%s</textarea>' % (village_id, key, pretty)
        return '<textarea class="form-control" rows="6" data-type="text" data-type-option="%s">%s</textarea>' % (key, pretty)

    if village_id:
        return '<input type="text" class="form-control" data-village-id="%s" data-type="text" value="%s" data-type-option="%s" />' % (
        village_id, value, key)
    else:
        return '<input type="text" class="form-control" data-type="text" value="%s" data-type-option="%s" />' % (
            value, key)


def pre_process_farm_assistant_rule(button, config_section, village_id=None):
    field_key = 'farm_assistant_rule_%s_field' % button
    op_key = 'farm_assistant_rule_%s_op' % button
    value_key = 'farm_assistant_rule_%s_value' % button

    field_value = config_section.get(field_key, 'none')
    op_value = config_section.get(op_key, 'none')
    value_value = config_section.get(value_key, '')

    if village_id:
        data_attrs = ' data-village-id="%s"' % village_id
    else:
        data_attrs = ''

    field_options = ['none', 'wall', 'distance', 'last_attack']
    op_options = ['none', '<', '>', '<=', '>=', '==']
    op_labels = {
        'none': 'none',
        '<': 'mniejsza (<)',
        '>': 'większa (>)',
        '<=': 'mniejsza lub równa (<=)',
        '>=': 'większa lub równa (>=)',
        '==': 'równa (==)'
    }

    output = '<div class="form-row align-items-center">'
    output += '<div class="col-sm-3 mb-2">'
    output += '<select class="form-control" data-type="select" data-type-option="farm_assistant.%s"%s>' % (field_key, data_attrs)
    for option in field_options:
        output += '<option value="%s" %s>%s</option>' % (option, 'selected' if option == field_value else '', option)
    output += '</select></div>'

    output += '<div class="col-sm-4 mb-2">'
    output += '<select class="form-control" data-type="select" data-type-option="farm_assistant.%s"%s>' % (op_key, data_attrs)
    for option in op_options:
        output += '<option value="%s" %s>%s</option>' % (option, 'selected' if option == op_value else '', op_labels.get(option, option))
    output += '</select></div>'

    output += '<div class="col-sm-3 mb-2">'
    output += '<input type="number" class="form-control" data-type="number" data-type-option="farm_assistant.%s"%s value="%s" />' % (
        value_key, data_attrs, value_value)
    output += '</div>'
    output += '</div>'
    return output


def pre_process_number(key, value, village_id=None):
    if village_id:
        return '<input type="number" data-type="number" class="form-control" data-village-id="%s" value="%s" data-type-option="%s" />' % (
        village_id, value, key)
    return '<input type="number" data-type="number" class="form-control" value="%s" data-type-option="%s" />' % (
    value, key)


def pre_process_list(key, value, village_id=None):
    if village_id:
        return '<input type="text" data-type="list" class="form-control" data-village-id="%s" value="%s" data-type-option="%s" />' % (
        village_id, ', '.join(value), key)
    return '<input type="number" data-type="list" class="form-control" value="%s" data-type-option="%s" />' % (
    ', '.join(value), key)


def fancy(key):
    name = key
    if '.' in name:
        name = name.split('.')[1]
    name = name[0].upper() + name[1:]
    out = '<hr /><strong>%s</strong>' % name
    help_txt = None
    help_key = key
    help_key = help_key.replace('village_template', 'village')
    if help_key in help_file:
        help_txt = help_file[help_key]
    if help_txt:
        out += '<br /><i>%s</i>' % help_txt
    return out


def pre_process_config():
    # TODO get generic config
    config = sync()['config']
    to_hide = ["build", "villages", "reporting"]
    sections = {}
    for section in config:
        if section in to_hide:
            continue
        config_data = ""
        skip_params = set()
        for parameter in config[section]:
            if parameter in skip_params:
                continue
            value = config[section][parameter]
            kvp = "%s.%s" % (section, parameter)
            if section == 'farm_assistant':
                m_rule = re.match(r'^farm_assistant_rule_([ABC])_(field|op|value)$', parameter)
                if m_rule:
                    button = m_rule.group(1)
                    rule_keys = {
                        'farm_assistant_rule_%s_field' % button,
                        'farm_assistant_rule_%s_op' % button,
                        'farm_assistant_rule_%s_value' % button
                    }
                    config_data += '%s %s' % (
                        fancy('farm_assistant.farm_assistant_rule_%s' % button),
                        pre_process_farm_assistant_rule(button, config[section])
                    )
                    skip_params.update(rule_keys)
                    continue
            if type(value) == bool:
                config_data += '%s %s' % (fancy(kvp), pre_process_bool(kvp, value))
            if type(value) == str:
                config_data += '%s %s' % (fancy(kvp), pre_process_string(kvp, value))
            if type(value) == list:
                config_data += '%s %s' % (fancy(kvp), pre_process_list(kvp, value))
            if type(value) == int or type(value) == float:
                config_data += '%s %s' % (fancy(kvp), pre_process_number(kvp, value))
        sections[section] = config_data
    return sections


def pre_process_village_config(village_id):
    village_configs = sync()['config'].get('villages', {})
    if village_id in village_configs:
        config = village_configs[village_id]
    else:
        try:
            default_village = next(iter(village_configs))
            config = village_configs[default_village]
        except StopIteration:
            config = {}
    config_data = ""
    skip_params = set()
    for parameter in config:
        if parameter == "additional_farms":
            continue
        if parameter in skip_params:
            continue
        value = config[parameter]
        kvp = "village.%s" % parameter
        m_rule = re.match(r'^farm_assistant_rule_([ABC])_(field|op|value)$', parameter)
        if m_rule:
            button = m_rule.group(1)
            rule_keys = {
                'farm_assistant_rule_%s_field' % button,
                'farm_assistant_rule_%s_op' % button,
                'farm_assistant_rule_%s_value' % button
            }
            config_data += '%s %s' % (
                fancy('farm_assistant.farm_assistant_rule_%s' % button),
                pre_process_farm_assistant_rule(button, config, village_id)
            )
            skip_params.update(rule_keys)
            continue
        if type(value) == bool:
            config_data += '%s %s' % (fancy(kvp), pre_process_bool(kvp, value, village_id))
        if type(value) == str:
            config_data += '%s %s' % (fancy(kvp), pre_process_string(kvp, value, village_id))
        if type(value) == list:
            config_data += '%s %s' % (fancy(kvp), pre_process_list(kvp, value, village_id))
        if type(value) == int or type(value) == float:
            config_data += '%s %s' % (fancy(kvp), pre_process_number(kvp, value, village_id))
    return config_data


def sync():
    villages = DataReader.cache_grab("villages")
    attacks = DataReader.cache_grab("attacks")
    config = DataReader.config_grab()
    managed = DataReader.cache_grab("managed")
    bot_status = bm.is_running()

    out_struct = {
        "attacks": attacks,
        "villages": villages,
        "config": config,
        "bot": managed,
        "status": bot_status
    }
    return out_struct


@app.route('/api/get', methods=['GET'])
def get_vars():
    return jsonify(sync())


@app.route('/bot/start')
def start_bot():
    bm.start()
    return jsonify(bm.is_running())


@app.route('/bot/stop')
def stop_bot():
    bm.stop()
    return jsonify(not bm.is_running())


@app.route('/config', methods=['GET'])
def get_config():
    return render_template('config.html', data=sync(), config=pre_process_config(), helpfile=help_file)


@app.route('/village', methods=['GET'])
def get_village_config():
    data = sync()
    vid = request.args.get("id", None)
    return render_template('village.html', data=data, config=pre_process_village_config(village_id=vid),
                           current_select=vid, helpfile=help_file)


@app.route('/map', methods=['GET'])
def get_map():
    sync_data = sync()
    center_id = request.args.get("center", None)
    center_x = request.args.get("x", None)
    center_y = request.args.get("y", None)
    center_coords = None
    if center_x is not None and center_y is not None:
        try:
            center_coords = (int(center_x), int(center_y))
        except ValueError:
            center_coords = None
    if center_id:
        center = center_id
    else:
        center = None
        if sync_data['villages']:
            center = next(iter(sync_data['villages']))
    map_payload = MapBuilder.build(sync_data['villages'], current_village=center, size=20, center_coords=center_coords)
    map_data = json.dumps(map_payload)
    return render_template('map.html', data=sync_data, map=map_data,
                           map_center_x=map_payload.get('center_x'),
                           map_center_y=map_payload.get('center_y'),
                           map_min_x=map_payload.get('min_x'),
                           map_min_y=map_payload.get('min_y'))


@app.route('/map/refresh', methods=['POST', 'GET'])
def refresh_map():
    session = DataReader.get_session()
    if not session or 'cookies' not in session:
        return jsonify({"error": "No session data. Save session first."}), 400
    try:
        from core.request import WebWrapper
        from game.map import Map as GameMap
    except Exception as e:
        tb = traceback.format_exc()
        return jsonify({"error": "Required modules not available", "detail": str(e), "traceback": tb}), 500

    wrapper = WebWrapper(session.get('endpoint', None), server=session.get('server', None), endpoint=session.get('endpoint', None))
    try:
        wrapper.web.cookies.update(session.get('cookies', {}))
    except Exception:
        pass

    # Try to refresh for managed villages first, fallback to config
    managed = DataReader.cache_grab("managed")
    refreshed = []
    if managed:
        for vid in managed:
            try:
                m = GameMap(wrapper=wrapper, village_id=vid)
                m.get_map()
                refreshed.append(vid)
            except Exception:
                continue
    else:
        config = DataReader.config_grab()
        for vid in config.get('villages', []):
            try:
                m = GameMap(wrapper=wrapper, village_id=vid)
                m.get_map()
                refreshed.append(vid)
            except Exception:
                continue

    if not refreshed:
        return jsonify({"error": "No villages refreshed (no managed/config villages or fetch failed)."}), 500
    return jsonify({"status": "ok", "refreshed": refreshed})


@app.route('/villages', methods=['GET'])
def get_village_overview():
    return render_template('villages.html', data=sync())


@app.route('/building_templates', methods=['GET', 'POST'])
def get_building_templates():
    if request.form.get('new', None):
        plain = os.path.basename(request.form.get('new'))
        if not plain.endswith('.txt'):
            plain = "%s.txt" % plain
        tempfile = '../templates/builder/%s' % plain
        if not os.path.exists(tempfile):
            with open(tempfile, 'w') as ouf:
                ouf.write("")
    selected = request.args.get('t', None)
    return render_template('templates.html',
                           templates=BuildingTemplateManager.template_cache_list(),
                           selected=selected,
                           buildings=buildings)


@app.route('/', methods=['GET'])
def get_home():
    session = DataReader.get_session()
    return render_template('bot.html', data=sync(), session=session)


@app.route('/app/js', methods=['GET'])
def get_js():
    urlpath = os.path.join(os.path.dirname(__file__), "public")
    return send_from_directory(urlpath, "js.v2.js")


@app.route('/logs', methods=['GET'])
def get_logs():
    # return last N log lines (default 200)
    try:
        n = int(request.args.get('n', 200))
    except Exception:
        n = 200
    kind = request.args.get('kind', 'bot')
    return jsonify({"logs": lb_get_logs(kind=kind, n=n)})


@app.route('/bot/command', methods=['POST'])
def bot_command():
    data = request.get_json() or {}
    cmd = data.get('cmd') or request.form.get('cmd')
    if not cmd:
        return jsonify({"error": "No cmd provided"}), 400
    try:
        bm.send_command(cmd)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/app/config/set', methods=['GET'])
def config_set():
    vid = request.args.get("village_id", None)
    if not vid:
        DataReader.config_set(parameter=request.args.get("parameter"), value=request.args.get("value", None))
    else:
        param = request.args.get("parameter")
        if param.startswith("village."):
            param = param.replace("village.", "")
        DataReader.village_config_set(village_id=vid, parameter=param, value=request.args.get("value", None))

    return jsonify(sync())


if len(sys.argv) > 1:
    try:
        port = int(sys.argv[1])
    except Exception:
        port = 5000
    app.run(host="127.0.0.1", port=port)
else:
    app.run(host="127.0.0.1", port=5000)
