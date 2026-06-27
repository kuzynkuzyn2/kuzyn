"""
Klasa do używania jednego generycznego słoika ciastek, emulująca jedną kartę
"""

import requests

from core.filemanager import FileManager
from core.notification import Notification

import logging
import re
import time
import random
from urllib.parse import urljoin, urlencode

from core.reporter import ReporterObject


class WebWrapper:
    """
    Obiekt WebWrapper do wysyłania żądań HTTP
    """
    web = None
    headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0.3904.97 Safari/537.36',
        'upgrade-insecure-requests': '1'
    }
    endpoint = None
    logger = logging.getLogger("Żądania")
    server = None
    last_response = None
    last_h = None
    priority_mode = False
    auth_endpoint = None
    reporter = None
    delay = 1.0

    def __init__(self, url, server=None, endpoint=None, reporter_enabled=False, reporter_constr=None):
        """
        Skonstruuj sesję i wykryj zmienne
        """
        self.web = requests.session()
        self.auth_endpoint = url
        self.server = server
        self.endpoint = endpoint
        self.reporter = ReporterObject(enabled=reporter_enabled, connection_string=reporter_constr)

    def post_process(self, response):
        """
        Przetwarzanie powyżej wszystkich żądań i przechowywanie danych używanych w następnym żądaniu
        """
        xsrf = re.search('<meta content="(.+?)" name="csrf-token"', response.text)
        if xsrf:
            self.headers['x-csrf-token'] = xsrf.group(1)
            self.logger.debug("Ustawiony token CSRF")
        elif 'x-csrf-token' in self.headers:
            del self.headers['x-csrf-token']
        self.headers['Referer'] = response.url
        self.last_response = response
        get_h = re.search(r'&h=(\w+)', response.text)
        if get_h:
            self.last_h = get_h.group(1)

    def get_url(self, url, headers=None, _captcha_retries=0):
        """
        Pobiera adres URL za pomocą podstawowego żądania GET.
        Loguje akcję na customowym poziomie "get" (21), widocznym w konsoli.
        """
        self.headers['Origin'] = (self.endpoint if self.endpoint else self.auth_endpoint).rstrip('/')
        if not self.priority_mode:
            time.sleep(random.randint(int(3 * self.delay), int(7 * self.delay)))
        url = urljoin(self.endpoint if self.endpoint else self.auth_endpoint, url)
        if not headers:
            headers = self.headers
        # POPRAWIONE: loguj na customowym poziomie "get" (21), nie debug.
        # Dzięki temu akcje HTTP są widoczne w konsoli niebieskim tłem.
        self.logger.get("GET %s", url)
        try:
            res = self.web.get(url=url, headers=headers)
            self.logger.debug("GET %s [%d]", url, res.status_code)
            self.post_process(res)
            if 'data-bot-protect="forced"' in res.text:
                # Ogranicz liczbę prób, aby uniknąć nieskończonej rekurencji
                max_captcha_retries = 3
                if _captcha_retries >= max_captcha_retries:
                    self.logger.error(
                        "Ochrona przed botami nadal aktywna po %d próbach, przerywam",
                        max_captcha_retries,
                    )
                    return res
                self.logger.warning(
                    "Ochrona przed botami uruchomiona! próba %d/%d",
                    _captcha_retries + 1, max_captcha_retries,
                )
                try:
                    self.reporter.report(
                        0, "TWB_RECAPTCHA",
                        "Zatrzymywanie bota, naciśnij dowolny klawisz po rozwiązaniu captchy",
                    )
                except Exception:
                    pass
                try:
                    Notification.send("Ochrona przed botami uruchomiona! nie można kontynuować")
                except Exception:
                    pass
                try:
                    print("Naciśnij dowolny klawisz...")
                    input()
                except (EOFError, KeyboardInterrupt):
                    return res
                return self.get_url(url, headers, _captcha_retries=_captcha_retries + 1)
            return res
        except Exception as e:
            self.logger.warning("GET %s: %s", url, str(e))
            return None

    def post_url(self, url, data, headers=None):
        """
        Wysyła podstawowe żądanie POST z danymi zakodowanymi w URL.
        Loguje akcję na customowym poziomie "get" (21), widocznym w konsoli.
        """
        if not self.priority_mode:
            time.sleep(
                random.randint(int(3 * self.delay), int(7 * self.delay))
            )
        self.headers['Origin'] = (self.endpoint if self.endpoint else self.auth_endpoint).rstrip('/')
        url = urljoin(self.endpoint if self.endpoint else self.auth_endpoint, url)
        enc = urlencode(data)
        if not headers:
            headers = self.headers
        # POPRAWIONE: loguj POST na customowym poziomie "get" (21).
        self.logger.get("POST %s | data=%s", url, enc[:200])
        try:
            res = self.web.post(url=url, data=data, headers=headers)
            self.logger.debug("POST %s %s [%d]", url, enc, res.status_code)
            self.post_process(res)
            return res
        except Exception as e:
            self.logger.warning("POST %s %s: %s", url, enc, str(e))
            return None

    def start(self, ):
        """
        Uruchom bota i sprawdź, czy ostatnia sesja jest nadal ważna
        """
        session_data = FileManager.load_json_file("cache/session.json")
        if session_data:
            if session_data.get('endpoint') and session_data.get('endpoint') != self.endpoint:
                self.logger.warning(
                    "Ignoring session cache because stored endpoint %s does not match current endpoint %s",
                    session_data.get('endpoint'),
                    self.endpoint,
                )
            elif session_data.get('server') and session_data.get('server') != self.server:
                self.logger.warning(
                    "Ignoring session cache because stored server %s does not match current server %s",
                    session_data.get('server'),
                    self.server,
                )
            else:
                self.web.cookies.update(session_data.get('cookies', {}))
                get_test = self.get_url("game.php?screen=overview")
                if get_test is not None and "game.php" in get_test.url:
                    return True
                self.logger.warning("Current session cache not valid")

        self.web.cookies.clear()
        print("Wprowadź ciąg cookie z przeglądarki>")
        cinp = input()
        cookies = {}
        cinp = cinp.strip()
        for itt in cinp.split(';'):
            itt = itt.strip()
            kvs = itt.split("=")
            k = kvs[0]
            v = '='.join(kvs[1:])
            cookies[k] = v
        self.web.cookies.update(cookies)
        self.logger.info("Game Endpoint: %s", self.endpoint)

        for c in self.web.cookies:
            cookies[c.name] = c.value

        FileManager.save_json_file({
            'endpoint': self.endpoint,
            'server': self.server,
            'cookies': cookies
        }, "cache/session.json")

    def get_action(self, village_id, action):
        """
        Uruchamia akcję w konkretnej wsi
        """
        url = "game.php?village=%s&screen=%s" % (village_id, action)
        response = self.get_url(url)
        return response

    def get_api_data(self, village_id, action, params={}):

        custom = dict(self.headers)
        custom['accept'] = "application/json, text/javascript, */*; q=0.01"
        custom['x-requested-with'] = "XMLHttpRequest"
        custom['tribalwars-ajax'] = "1"
        req = {
            'ajax': action,
            'village': village_id,
            'screen': 'api'
        }
        req.update(params)
        payload = f"game.php?{urlencode(req)}"
        url = urljoin(self.endpoint, payload)
        res = self.get_url(url, headers=custom)
        if res is not None and getattr(res, 'status_code', None) == 200:
            try:
                return res.json()
            except Exception:
                return res
        return None

    def post_api_data(self, village_id, action, params={}, data={}):
        """
        Symuluje żądanie API
        """
        custom = dict(self.headers)
        custom['accept'] = "application/json, text/javascript, */*; q=0.01"
        custom['x-requested-with'] = "XMLHttpRequest"
        custom['tribalwars-ajax'] = "1"
        req = {
            'ajax': action,
            'village': village_id,
            'screen': 'api'
        }
        req.update(params)
        payload = f"game.php?{urlencode(req)}"
        url = urljoin(self.endpoint, payload)
        if 'h' not in data:
            data['h'] = self.last_h
        res = self.post_url(url, data=data, headers=custom)
        if res is not None and getattr(res, 'status_code', None) == 200:
            try:
                return res.json()
            except Exception:
                return res
        return None

    def get_api_action(self, village_id, action, params={}, data={}):
        """
        Symuluje uruchamianą akcję API
        """
        custom = dict(self.headers)
        custom['Accept'] = "application/json, text/javascript, */*; q=0.01"
        custom['X-Requested-With'] = "XMLHttpRequest"
        custom['TribalWars-Ajax'] = "1"
        req = {
            'ajaxaction': action,
            'village': village_id,
            'screen': 'api'
        }
        req.update(params)
        payload = f"game.php?{urlencode(req)}"
        url = urljoin(self.endpoint, payload)
        if 'h' not in data:
            data['h'] = self.last_h
        res = self.post_url(url, data=data, headers=custom)
        if res is not None and getattr(res, 'status_code', None) == 200:
            try:
                return res.json()
            except Exception:
                return res
        return None
