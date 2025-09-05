# services/scanner/start_scanner.py
from services.threading.thread_manager import ThreadManager
from services.scanner.scanner import run_scan
from pathlib import Path
import threading
from services.logging.logger_singleton import logger

def start_scanner(debug=False):
    manager = ThreadManager.instance()
    parent_stop_event = threading.Event()

    try:
        manager.add_thread(
            name="ScannerParent",
            target_func=run_scan,
            kwargs={
                "mode": None,
                "consumer": None,
                "debug": debug
            },
            daemon=True,
            reload_files=[str(Path("services/scanner/scanner.py").resolve())],
            parent=None
        )

        manager.start_watcher(Path("services"))

        logger.logMessage("[Main] Scanner started → waiting for shutdown")
        manager.wait_for_shutdown()

    except KeyboardInterrupt:
        logger.logMessage("[Main] KeyboardInterrupt → stopping threads")
        manager.stop()

    finally:
        logger.logMessage("[Main] Joining threads...")
        manager.stop_all()
        logger.logMessage("[Main] Shutdown complete")
