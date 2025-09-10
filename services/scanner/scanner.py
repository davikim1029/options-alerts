#scanner.py
import os
import sys
import queue
from pathlib import Path
import time as pyTime
from datetime import datetime

from services.logging.logger_singleton import logger
from services.etrade_consumer import EtradeConsumer
from services.core.shutdown_handler import ShutdownManager
from services.core.cache_manager import Caches
import services.threading.api_worker as api_worker_mod

from services.scanner import buy_loop as buy_mod
from services.scanner import sell_loop as sell_mod


from services.threading.thread_manager import ThreadManager
from services.scanner.scanner_utils import wait_interruptible

# ---------------------------
# Globals: input queues
# ---------------------------
user_input_queue = queue.Queue()


# ---------------------------
# Input listener
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
                    elif ch.isprintable():
                        user_input_queue.put(ch)
                pyTime.sleep(0.05)
            else:
                import select
                dr, _, _ = select.select([sys.stdin], [], [], 0.1)
                if dr:
                    line = sys.stdin.readline()
                    if line:
                        user_input_queue.put(line.rstrip("\n"))
        except Exception as e:
            logger.logMessage(f"[Input Listener] Error: {e}")
            pyTime.sleep(0.1)


# ---------------------------
# Input processor
# ---------------------------
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
            lower = cmd.strip().lower()
            if lower == "exit":
                logger.logMessage("[Input Processor] Shutdown command received, signaling stop")
                ThreadManager.instance().stop_all()
                return
            elif lower == "renew_token":
                logger.logMessage("[Input Processor] Renew token command received")
                try:
                    from services.etrade_consumer import force_generate_new_token
                    force_generate_new_token()
                    logger.logMessage("[Auth] Token successfully refreshed")
                except Exception as e:
                    logger.logMessage(f"[Auth] Token renewal failed: {e}")
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
# Main scanner runner
# ---------------------------
def run_scan(stop_event, mode=None, consumer=None, debug=False):
    logger.logMessage("[Scanner] Initializing...")

    if consumer is None:
        consumer = EtradeConsumer(sandbox=False, debug=debug)

    caches = Caches()
    api_worker_mod.init_worker(consumer, min_interval=2)
    consumer.apiWorker = api_worker_mod.get_worker()

    manager = ThreadManager.instance(consumer=consumer, caches=caches)

    watch_dir = Path(__file__).parent.resolve()
    manager.start_watcher(watch_dir)
    logger.logMessage(f"[Scanner] Watchdog started in: {watch_dir}")

    # ---------------------------
    # Shutdown callback
    # ---------------------------
    def _shutdown_callback(reason=None):
        ThreadManager.instance().stop_all()

    try:
        ShutdownManager.register("Request Shutdown", _shutdown_callback)
    except TypeError:
        ShutdownManager.init(error_logger=logger.logMessage)
        ShutdownManager.register("Request Shutdown", _shutdown_callback)

    # ---------------------------
    # Start threads
    # ---------------------------
    # API Worker
    manager.add_thread("HTTP Worker", consumer.apiWorker._worker, daemon=True, reload_files=[])

    # Input
    manager.add_thread("Input Listener", input_listener, daemon=True, reload_files=[])
    manager.add_thread("Input Processor", input_processor, daemon=True, reload_files=[])

    # Cache autosave loops
    for loop_func, loop_name in caches.all_autosave_loops():
        manager.add_thread(loop_name, loop_func, daemon=True, reload_files=[])

    # Trading loops (buy/sell)
    # NOTE: reload triggers an *immediate run* with fresh defaults from loop files

    manager.add_thread(
      "Buy Scanner",
      buy_mod.buy_loop,
      kwargs={
          "consumer": consumer,
          "caches": caches,
          "debug": debug,
          "start_time": getattr(buy_mod, "DEFAULT_START_TIME", None),
          "end_time": getattr(buy_mod, "DEFAULT_END_TIME", None),
          "cooldown_seconds": getattr(buy_mod, "DEFAULT_COOLDOWN_SECONDS", 300),
          "force_first_run": False,
      },
      daemon=True,
      reload_files=[
          "services/scanner/buy_loop.py",
          "services/scanner/buy_scanner.py"
      ],
      module_dependencies=[
          "services.scanner.buy_scanner"
      ]
      )
    
    manager.add_thread(
        "Sell Scanner",
        sell_mod.sell_loop,
        kwargs={
            "consumer": consumer,
            "caches": caches,
            "debug": debug,
            "start_time": getattr(sell_mod, "DEFAULT_START_TIME", None),
            "end_time": getattr(sell_mod, "DEFAULT_END_TIME", None),
            "cooldown_seconds": getattr(sell_mod, "DEFAULT_COOLDOWN_SECONDS", 3600),
            "force_first_run": True,
        },
        daemon=True,
        reload_files=[
            "services/scanner/sell_loop.py",
            "services/scanner/sell_scanner.py"
        ]
    )

    logger.logMessage("[Scanner] All threads started. Press Ctrl+C or type 'exit' to stop.")
