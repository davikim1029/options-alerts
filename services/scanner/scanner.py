# services/scanner/scanner.py
import os
import sys
import queue
import threading
from pathlib import Path
import time as pyTime
from datetime import time

from services.logging.logger_singleton import logger
from services.etrade_consumer import EtradeConsumer
from services.core.shutdown_handler import ShutdownManager
from services.core.cache_manager import Caches
import services.threading.api_worker as api_worker_mod

from services.scanner.buy_loop import buy_loop
from services.scanner.sell_loop import sell_loop

from services.threading.thread_manager import ThreadManager

# ---------------------------
# Globals: input queues
# ---------------------------
user_input_queue = queue.Queue()
input_processor_queue = queue.Queue()

# Intervals
BUY_INTERVAL_SECONDS = 300
SELL_INTERVAL_SECONDS = 1800

# Global main-stop event
_MAIN_STOP = threading.Event()

# ---------------------------
# Input listener / processor
# ---------------------------
def input_listener(stop_event):
    while not stop_event.is_set():
        try:
            if os.name == "nt":
                import msvcrt
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch == "\r":
                        user_input_queue.put("\n")
                pyTime.sleep(0.05)
            else:
                import select
                dr, _, _ = select.select([sys.stdin], [], [], 0.1)
                if dr:
                    line = sys.stdin.readline()
                    if not line:
                        pyTime.sleep(0.05)
                        continue
                    user_input_queue.put(line.rstrip("\n"))
        except Exception as e:
            logger.logMessage(f"[Input Listener] Error: {e}")
            pyTime.sleep(0.1)

def input_processor(stop_event):
    while not stop_event.is_set():
        try:
            cmd = user_input_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        except Exception as e:
            logger.logMessage(f"[Input Processor] dequeue error: {e}")
            continue

        try:
            if not cmd:
                continue
            lower = cmd.strip().lower()
            if lower == "exit":
                logger.logMessage("[Input Processor] 'exit' received → shutting down")
                _request_shutdown("User exit command")
                return
            elif lower == "stats":
                logger.logMessage("[Input Processor] stats command received (not implemented)")
            else:
                logger.logMessage(f"[Input Processor] Unknown command: {cmd}")
        except Exception as e:
            logger.logMessage(f"[Input Processor] Error handling '{cmd}': {e}")

# ---------------------------
# Cache autosave wrapper
# ---------------------------
def _autosave_loop(stop_event, cache):
    try:
        cache.autosave_loop(stop_event)
    except Exception as e:
        logger.logMessage(f"[Autosave] Error in '{getattr(cache,'name',cache)}': {e}")

# ---------------------------
# Shutdown
# ---------------------------
def _request_shutdown(reason="Unknown"):
    try:
        logger.logMessage(f"[Scanner] Shutdown requested: {reason}")
        ThreadManager.instance().stop_all()
    finally:
        _MAIN_STOP.set()

# ---------------------------
# Main scanner runner
# ---------------------------
def run_scan(mode=None, consumer=None, debug=False):
    logger.logMessage("[Scanner] Initializing...")

    if consumer is None:
        consumer = EtradeConsumer()

    caches = Caches()

    api_worker_mod.init_worker(consumer.session, min_interval=2)
    consumer.apiWorker = api_worker_mod.get_worker()

    manager = ThreadManager.instance(consumer=consumer, caches=caches)

    watch_dir = Path(__file__).parent.resolve()
    manager.start_watcher(watch_dir)
    logger.logMessage(f"[Scanner] Watchdog started in: {watch_dir}")

    def _shutdown_callback(reason=None):
        _request_shutdown(reason or "ShutdownManager")

    try:
        ShutdownManager.register(_shutdown_callback)
    except TypeError:
        ShutdownManager.init(error_logger=logger.logMessage)
        ShutdownManager.register(_shutdown_callback)

    # ---------------------------
    # Start threads with hot-reload support
    # ---------------------------
    # API Worker
    manager.add_thread(
        "HTTP Worker",
        consumer.apiWorker._worker,
        daemon=True,
        reload_files=[]
    )

    # Input
    manager.add_thread(
        "Input Listener",
        input_listener,
        daemon=True,
        reload_files=[]
    )
    manager.add_thread(
        "Input Processor",
        input_processor,
        daemon=True,
        reload_files=[]
    )

    # Cache autosave loops
    for loop_func, loop_name in caches.all_autosave_loops():
        manager.add_thread(
            loop_name,
            loop_func,
            daemon=True,
            reload_files=[]
        )

    # --- Trading loops (buy/sell) ---
    manager.add_thread(
        "Buy Scanner",
        buy_loop,
        kwargs={
            "consumer": consumer,
            "caches": caches,
            "debug": debug
        },
        reload_files=[
            "services/scanner/buy_loop.py",
            "services/scanner/buy_scanner.py"
        ],
        start_time=time(9, 30),   # 9:30 AM
        end_time=time(16, 0),     # 4:00 PM
        cooldown_seconds=300      # wait 5 minutes before restarting
    )


    manager.add_thread(
        "Sell Scanner",
        sell_loop,
        kwargs={
            "consumer": consumer,
            "caches": caches,
            "debug": debug
        },
        reload_files=[
            "services/scanner/sell_loop.py",
            "services/scanner/sell_scanner.py"
        ],
        start_time=time(9, 30),   # 9:30 AM
        end_time=time(16, 0),     # 4:00 PM
        cooldown_seconds=3600      # wait 5 minutes before restarting
    )



    logger.logMessage("[Scanner] All threads started. Press Ctrl+C or type 'exit' to stop.")

    try:
        while not _MAIN_STOP.is_set():
            pyTime.sleep(0.5)
    except KeyboardInterrupt:
        _request_shutdown("KeyboardInterrupt")
    except Exception as e:
        _request_shutdown(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        logger.logMessage("[Scanner] Exited main loop.")
