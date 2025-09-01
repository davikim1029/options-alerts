import threading
import time
from datetime import datetime

class ThreadManager:
    _instance = None
    _started_once = False
    _stopped_once = False

    def __init__(self):
        self.stop_event = threading.Event()
        self.registered = [] # (target,name *args)
        self.threads = []  # list of (thread, target_name)
        self.lock = threading.Lock()

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, target, name=None, *args, **kwargs):
        """Register the function and arguments; thread object will be created later."""
        with self.lock:
            self.registered.append((target, name or target.__name__, args, kwargs))

    def start_all(self):
        if not ThreadManager._started_once:
            print("Starting workers...")
            ThreadManager._started_once = True
            ThreadManager._stopped_once = False #Mark stopped as false
       
        self.stop_event.clear()
        with self.lock:
            
            # Lazy-create threads if none exist
            if not self.threads:
                for target, name, args, kwargs in self.registered:
                    t = threading.Thread(target=target, name=name, args=(self.stop_event, *args), kwargs=kwargs)
                    self.threads.append(t)

            for i, t in enumerate(self.threads, 1):
                if not t.is_alive():
                    t.start()
                    print(f"Started thread {i}: {t.name}")



    def stop_all(self):
        if not ThreadManager._stopped_once:
            print("Stopping workers...")
            ThreadManager._stopped_once = True

        self.stop_event.set()
        with self.lock:
            threads_alive = 0
            for i, t in enumerate(self.threads, 1):
                if t.is_alive():
                    print(f"Stopping thread {i}: {t.name}")
                    t.join()
                    threads_alive +=1
                    
            self.threads.clear()
            return threads_alive
            
            
    def manage(self, start_hour=8, start_minute=50, end_hour=8, end_minute=53):
        """Keeps workers active only during market hours."""
        
        try:
          while True:
            now = datetime.now()
            within_hours = (
              (now.hour > start_hour or (now.hour == start_hour and now.minute >= start_minute))
              and (now.hour < end_hour or (now.hour == end_hour and now.minute < end_minute))
              )
              
            if within_hours:
              self.start_all()
            else:
              threads_stopping = self.stop_all()
              if threads_stopping == 0:
                print("Sleeping")
              time.sleep(60)
        except KeyboardInterrupt:
            print("Received KeyboardInterrupt, stopping all threads...")
        except Exception as e:
            print(f"Exception occurred: {e}")
            print("Stopping all threads")
        finally:
            self.stop_all()
