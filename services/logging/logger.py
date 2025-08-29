import logging
import os
from datetime import datetime
from services.core.shutdown_handler import ShutdownManager


class Logger:
    def __init__(self, log_dir="logs", prefix="log"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(log_dir, f"{prefix}_{today}.log")

        self.logger = logging.getLogger("DailyLogger")
        self.logger.setLevel(logging.INFO)

        if not self.logger.handlers:
            handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s - %(message)s", "%Y-%m-%d %H:%M:%S")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        ShutdownManager.init(error_logger=self.log)
        ShutdownManager.register(self._log_exit)

    def log(self, message):
        self.logger.info(message)

    def _log_exit(self, reason):
        self.logger.info(f"Script terminated ({reason}).")