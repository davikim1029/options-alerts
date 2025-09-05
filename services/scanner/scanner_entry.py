# services/scanner/start_scanner.py
from services.threading.thread_manager import ThreadManager
from services.scanner.scanner import run_scan
from pathlib import Path
import threading

def start_scanner(debug=False):
    manager = ThreadManager.instance()

    # Create a stop_event for the parent thread
    parent_stop_event = threading.Event()

    # Add the run_scan function as the top-level "parent" thread
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
        parent=None  # top-level
    )

    # Start watcher for hot-reload
    manager.start_watcher(Path("services"))

    # Block until shutdown
    manager.wait_for_shutdown()
