from services.threading.thread_manager import ThreadManager
from services.scanner.scanner import run_scan
from pathlib import Path
from services.logging.logger_singleton import logger

def start_scanner(debug=False):
    try:
        manager = ThreadManager.instance()

        # Top-level parent thread
        manager.add_thread(
            name="ScannerParent",
            target_func=run_scan,
            kwargs={"mode": None, "debug": debug},
            daemon=True,
            reload_files=[str(Path("services/scanner/scanner.py").resolve())],
            parent=None
        )

        # Start hot-reload watcher
        manager.start_watcher(Path("services"))
        manager.wait_for_shutdown()

    except KeyboardInterrupt:
        logger.logMessage("[Main] KeyboardInterrupt, stopping threads")
        manager.stop_all()
