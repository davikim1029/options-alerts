# logger_singleton.py
from services.logger import Logger
from services.shutdown_handler import ShutdownManager
logger = Logger()
ShutdownManager.register(lambda reason=None: logger._log_exit(reason))
