# services/threading/thread_manager.py
import sys
import threading
import importlib
import importlib.util
import time as pytime
from services.logging.logger_singleton import logger
from datetime import datetime, time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from services.core.shutdown_handler import ShutdownManager


class ThreadWrapper:
    def __init__(self, name, 
                 target_func, 
                 args=None, 
                 kwargs=None, 
                 daemon=True, 
                 reload_files=None,
                 start_time=None, 
                 end_time=None, 
                 cooldown_seconds=None,
                 parent=None,
                 update_vars=None
                 ):
        self.name = name
        self._target_func = target_func
        self._args = args or ()
        self._kwargs = kwargs or {}
        self._daemon = daemon
        self.reload_files = reload_files or []
        self.update_vars = update_vars or {}  # mapping: wrapper_attr -> module_var_name

        
        # scheduling
        self.start_time = start_time
        self.end_time = end_time
        self.cooldown_seconds = cooldown_seconds

        # parent tracking
        self.parent = parent

        # --- Store the module where the target function actually lives ---
        self._module_name = target_func.__module__

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._schedule_wrapper, name=name, daemon=daemon)

    def start(self):
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._schedule_wrapper, name=self.name, daemon=self._daemon)
        self._thread.start()
        
    def _within_schedule(self):
        now = datetime.now().time()
        if self.start_time and now < self.start_time:
            return False
        if self.end_time and now > self.end_time:
            return False
        return True
    
    def _schedule_wrapper(self):
        while not self._stop_event.is_set():
            if not self._within_schedule():
                pytime.sleep(30)
                continue

            try:
                self._target_func(*self._args, stop_event=self._stop_event, **self._kwargs)
            except Exception as e:
                logger.logMessage(f"[ThreadWrapper][{self.name}] Crashed: {e}")

            if self.cooldown_seconds:
                logger.logMessage(f"[ThreadWrapper][{self.name}] Cooling down for {self.cooldown_seconds/60} mins")
                waited = 0
                while waited < self.cooldown_seconds and not self._stop_event.is_set():
                    pytime.sleep(1)
                    waited += 1
            else:
                break

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
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
        self._parent_map = {}  # parent_name -> set of thread names

    # ----------------------------
    # Thread management
    # ----------------------------
    def add_thread(self, name, target_func, args=None, kwargs=None, daemon=True, reload_files=None,
                   start_time=None, end_time=None, cooldown_seconds=None, parent=None,update_vars=None):
        wrapper = ThreadWrapper(
            name=name,
            target_func=target_func,
            args=args,
            kwargs=kwargs,
            daemon=daemon,
            reload_files=reload_files,
            start_time=start_time,
            end_time=end_time,
            cooldown_seconds=cooldown_seconds,
            parent=parent,
            update_vars=update_vars
        )
        
        existing = self._threads.get(name)
        if existing and existing._thread and existing._thread.is_alive():
            if parent:
                # Stop and remove old thread so we can apply updated params
                logger.logMessage(f"[ThreadManager] Hot reload: stopping old thread '{name}' to apply new params")
                existing.stop()
                existing.join(timeout=5)
                del self._threads[name]
            else:
                logger.logMessage(f"[ThreadManager] Thread '{name}' already running, skipping add_thread")
                return existing


        self._threads[name] = wrapper
        if parent:
            self._parent_map.setdefault(parent, set()).add(name)
        wrapper.start()

    def reload_parent(self, parent_name):
        """Stop and restart all child threads of a parent."""
        children = self._parent_map.get(parent_name, set())
        for name in children:
            wrapper = self._threads.get(name)
            if wrapper:
                logger.logMessage(f"[ThreadManager] Hot-reloading child thread '{name}' of parent '{parent_name}'")
                wrapper.stop()
                wrapper.join(timeout=5)
                wrapper.start()

    def stop_all(self):
        logger.logMessage("[ThreadManager] Stopping all threads...")
        for wrapper in list(self._threads.values()):
            wrapper.stop()
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        logger.logMessage("[ThreadManager] All threads stopped.")

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
            event_handler.on_any_event = self._on_any_event
            self._observer = Observer()
            self._observer.schedule(event_handler, str(self._watch_folder), recursive=True)
            self._observer.start()
            for idx, t in enumerate(threading.enumerate()):
                if t.name.startswith("Thread-") and t.daemon:
                    t.name = f"WatchdogThread-{idx+1}"
            logger.logMessage(f"[ThreadManager] Watchdog started for folder: {self._watch_folder}")

    def _on_any_event(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path).resolve()
        logger.logMessage(f"[ThreadManager] Detected {event.event_type} on {path}")
        self.hot_reload(path)

    def hot_reload(self, changed_file_path):
        
        if ShutdownManager.is_shutdown_requested():
            logger.logMessage("[ThreadManager] Shutdown requested; skipping hot reload")
            return
        
        matched = False
        for wrapper in list(self._threads.values()):
            for file in wrapper.reload_files:
                abs_file = str(Path(file).resolve())
                if abs_file == str(Path(changed_file_path).resolve()):
                    matched = True

                    # Stop & join the thread
                    wrapper.stop()
                    wrapper.join(timeout=5)

                    # Reload relevant modules
                    for reload_file in wrapper.reload_files:
                        if reload_file.endswith(".pyc"):
                            continue
                        module_name = self._path_to_module(reload_file)
                        if module_name in sys.modules:
                            logger.logMessage(f"[ThreadManager][HotReload] Reloading module {module_name}")
                            module = importlib.reload(sys.modules[module_name])
                        else:
                            spec = importlib.util.spec_from_file_location(module_name, reload_file)
                            module = importlib.util.module_from_spec(spec)
                            sys.modules[module_name] = module
                            spec.loader.exec_module(module)

                    # Update function reference
                    module_name = wrapper._target_func.__module__
                    func_name = wrapper._target_func.__name__
                    module = sys.modules[module_name]
                    wrapper._target_func = getattr(module, func_name)

                    # --- Generalized scheduling param updates ---
                    if wrapper.update_vars:
                        for attr, module_var in wrapper.update_vars.items():
                            if hasattr(module, module_var):
                                new_val = getattr(module, module_var)
                                setattr(wrapper, attr, new_val)
                                logger.logMessage(f"[ThreadManager] Updated '{wrapper.name}.{attr}' = {new_val}")

                    # Restart the thread
                    wrapper.start()

                    # Also hot-reload all child threads of the same parent
                    if wrapper.parent:
                        self.reload_parent(wrapper.parent)

    # ----------------------------
    # Utilities
    # ----------------------------
    def _path_to_module(self, path):
        """
        Convert a full file path into a proper Python module name for importlib.
        Example:
        /Users/daviskim/Documents/GitHub/options/options-alerts/services/scanner/scanner.py
        -> services.scanner.scanner
        """
        p = Path(path).resolve()
        parts = list(p.parts)

        try:
            # Find 'services' folder
            idx = parts.index("services")
        except ValueError:
            logger.logMessage(f"[ThreadManager] Could not find 'services' in path: {path}")
            return p.stem  # fallback

        # Take everything from 'services' onward
        mod_parts = parts[idx:]
        # Replace last part with stem (remove .py)
        mod_parts[-1] = p.stem
        # Join with dots, no leading dot
        module_name = ".".join(mod_parts)
        return module_name



        
    def wait_for_shutdown(self):
        try:
            for wrapper in list(self._threads.values()):
                wrapper.join()
            if self._observer:
                self._observer.join()
        except KeyboardInterrupt:
            self.stop_all()
