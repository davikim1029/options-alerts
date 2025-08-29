# logger_singleton.py
from services.logging.logger import Logger
from services.core.shutdown_handler import ShutdownManager
logger = Logger()
ShutdownManager.register(lambda reason=None: logger._log_exit(reason))
