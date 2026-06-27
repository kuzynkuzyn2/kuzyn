import asyncio

try:
    import telegram
    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False
    telegram = None

from core.filemanager import FileManager
from core.exceptions import InvalidJSONException


class _Notification:
    bot = None
    enabled = False
    channel_id = None
    token = None

    def __init__(self):
        self.get_config()

        if self.enabled and HAS_TELEGRAM:
            try:
                self.loop = asyncio.new_event_loop()
                self.bot = telegram.Bot(token=self.token)
            except Exception:
                # Pozwalamy botowi działać bez powiadomień, jeśli telegram nie jest dostępny
                self.bot = None
                self.enabled = False

    def get_config(self):
        """
        Wczytuje konfigurację powiadomień z pliku config.json
        """
        try:
            config = FileManager.load_json_file("config.json")
        except InvalidJSONException:
            config = None
            self.enabled = False
        except Exception:
            config = None
            self.enabled = False
        if config:
            notification_config = config.get("notifications", {})
            self.enabled = bool(notification_config.get("enabled", False))
            self.channel_id = notification_config.get("channel_id")
            self.token = notification_config.get("token")

    def send(self, message):
        if not self.enabled or not self.bot:
            return

        try:
            task = self.loop.create_task(self.send_async(message))
            self.loop.run_until_complete(task)
        except Exception:
            # Powiadomienia są opcjonalne - nie mogą blokować bota
            pass

    async def send_async(self, message):
        try:
            await self.bot.send_message(chat_id=self.channel_id, text=message)
        except Exception:
            pass


Notification = _Notification()
