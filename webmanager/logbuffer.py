import logging
from collections import deque

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class InMemoryLogHandler(logging.Handler):
    def __init__(self, max_lines=1000):
        super().__init__()
        self.buffer = deque(maxlen=max_lines)
        self.setFormatter(logging.Formatter(LOG_FORMAT))

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self.buffer.append(msg)

    def get_logs(self, last_n=None):
        if last_n is None:
            return list(self.buffer)
        buf = list(self.buffer)
        if last_n >= len(buf):
            return buf
        return buf[-last_n:]


# global handler instance used by the webmanager
log_handler = InMemoryLogHandler()


def get_logs(n=200):
    try:
        return log_handler.get_logs(n)
    except Exception:
        return []
