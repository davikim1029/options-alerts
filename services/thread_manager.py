import threading
import time
from datetime import datetime

class ThreadManager:
    _instance = None
    _started_once = False
    _stopped_once = False

    def __init__(self):
        self.stop_event = threading.Event()
        self.threads = []  # list of (thread, target_name)
        self.lock = threading.Lock()

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, target, name, *args, **kwargs):
        """Register a runnable (function with stop_event) as a managed thread."""
        thread = threading.Thread(
            target=target, 
            args=(self.stop_event, *args), 
            kwargs=kwargs,
            name=name,
            daemon=True
        )
        with self.lock:
            self.threads.append(thread)

    def start_all(self):
        if not ThreadManager._started_once:
            print("Starting workers...")
            ThreadManager._started_once = True
            ThreadManager._stopped_once = False #Mark stopped as false
       
        self.stop_event.clear()
        with self.lock:
            if not self.threads:
                print("No threads to start.")
                return

            for i, t in enumerate(self.threads, 1):
                if not t.is_alive():
                    print(f"Starting thread {i}: {t.name}")
                    t.start()
                    print(f"Thread {i} started.")
                else:
                    print(f"Thread {i}: {t.name} is already running (pulse check).")

    def stop_all(self):
        if not ThreadManager._stopped_once:
            print("Stopping workers...")
            ThreadManager._stopped_once = True
            ThreadManager._started_once = False #Mark started as false
            
        self.stop_event.set()
        with self.lock:
            for t in self.threads:
                if t.is_alive():
                    t.join()
            self.threads.clear()

    def manage(self, start_hour=8, start_minute=30, end_hour=16, end_minute=30):
        """Keeps workers active only during market hours."""
        while True:
            now = datetime.now()
            within_hours = (
                (now.hour > start_hour or (now.hour == start_hour and now.minute >= start_minute))
                and (now.hour < end_hour or (now.hour == end_hour and now.minute < end_minute))
            )
            if within_hours:
                self.start_all()
            else:
                self.stop_all()
            time.sleep(60)
