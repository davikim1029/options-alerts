# services/threading/thread_manager.py
import sys
import threading
import importlib
import importlib.util
import logging
from services.utils import logMessage
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

log = logging.getLogger("ThreadManager")

class ThreadWrapper:
    def __init__(self, name, target_func, args=None, kwargs=None, daemon=True, reload_files=None):
        self.name = name
        self._target_func = target_func
        self._args = args or ()
        self._kwargs = kwargs or {}
        self._daemon = daemon
        self.reload_files = reload_files or []

        # --- Store the module where the target function actually lives ---
        self._module_name = target_func.__module__

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_wrapper, name=name, daemon=daemon)

    def start(self):
        # Always create a fresh stop_event on each (re)start
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_wrapper, name=self.name, daemon=self._daemon)
        self._thread.start()

    def _run_wrapper(self):
        try:
            # Inject the fresh stop_event every time
            self._target_func(*self._args, stop_event=self._stop_event, **self._kwargs)
        except Exception as e:
            log.exception(f"[ThreadWrapper][{self.name}] Crashed with exception: {e}")

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=5)
        
        
    def join(self, timeout=None):
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)



class ThreadManager:
    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls, consumer=None, caches=None):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(consumer, caches)
        return cls._instance

    def __init__(self, consumer=None, caches=None):
        self.consumer = consumer
        self.caches = caches
        self._threads = {}
        self._observer = None
        self._watch_folder = None
        self._observer_lock = threading.Lock()

    # ----------------------------
    # Thread management
    # ----------------------------
    def add_thread(self, name, target_func, args=None, kwargs=None, daemon=True, reload_files=None):
        wrapper = ThreadWrapper(name, target_func, args=args, kwargs=kwargs, daemon=daemon, reload_files=reload_files)
        self._threads[name] = wrapper
        wrapper.start()

    def stop_all(self):
        log.info("[ThreadManager] Stopping all threads...")
        for wrapper in self._threads.values():
            wrapper.stop()
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        log.info("[ThreadManager] All threads stopped.")

    # ----------------------------
    # Hot reload
    # ----------------------------
    def start_watcher(self, folder: Path):
        with self._observer_lock:
            if self._observer is not None:
                self._observer.stop()
                self._observer.join()

            self._watch_folder = folder.resolve()
            event_handler = FileSystemEventHandler()
            event_handler.on_modified = self._on_modified
            self._observer = Observer()
            self._observer.schedule(event_handler, str(self._watch_folder), recursive=True)
            self._observer.start()
            for idx, t in enumerate(threading.enumerate()):
                if t.name.startswith("Thread-") and t.daemon:
                    t.name = f"WatchdogThread-{idx+1}"
            log.info(f"[ThreadManager] Watchdog started for folder: {self._watch_folder}")

    def _on_modified(self, event):
        # Only care about files
        if event.is_directory:
            return
        path = Path(event.src_path).resolve()
        self.hot_reload(path)


    def hot_reload(self, changed_file_path):
        #log.info(f"[ThreadManager][HotReload] Change detected: {changed_file_path}")
        matched = False

        for wrapper in list(self._threads.values()):
            for file in wrapper.reload_files:
                abs_file = str(Path(file).resolve())
                if abs_file == str(Path(changed_file_path).resolve()):
                    matched = True
                    #log.info(f"[ThreadManager][HotReload] Reloading thread '{wrapper.name}' for {changed_file_path}")

                    # --- stop old thread ---
                    wrapper.stop()
                    wrapper.join(timeout=2)

                    # Reload *all* relevant modules for this wrapper
                    for reload_file in wrapper.reload_files:
                        module_name = Path(reload_file).with_suffix("").as_posix().replace("/", ".")
                        if module_name in sys.modules:
                            log.info(f"[ThreadManager][HotReload] Reloading module {module_name}")
                            module = importlib.reload(sys.modules[module_name])
                        else:
                            spec = importlib.util.spec_from_file_location(module_name, reload_file)
                            module = importlib.util.module_from_spec(spec)
                            sys.modules[module_name] = module
                            spec.loader.exec_module(module)

                    # After reloading, grab the updated function
                    module_name = wrapper._target_func.__module__
                    func_name = wrapper._target_func.__name__
                    module = sys.modules[module_name]
                    wrapper._target_func = getattr(module, func_name)

                    # Restart the thread
                    wrapper.start()

        #if not matched:
        #    log.info(f"[ThreadManager][HotReload] No registered threads matched: {changed_file_path}")




    # ----------------------------
    # Utilities
    # ----------------------------
    def _path_to_module(self, path):
        # Convert /path/to/services/scanner/buy_scanner.py -> services.scanner.buy_scanner
        p = Path(path).resolve()
        try:
            parts = list(p.parts)
            # find 'services' in path
            idx = parts.index("services")
            mod_parts = parts[idx:-1]
            mod_parts.append(p.stem)
            return ".".join(mod_parts)
        except ValueError:
            log.warning(f"[ThreadManager] Could not convert path to module: {path}")
            return p.stem
