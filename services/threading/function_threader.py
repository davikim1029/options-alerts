def start_executor(max_workers: int):
    global executor
    with _exectuor_lock:
        if executor:
            force_shutdown_executor()
        executor = ThreadPoolExecutor(max_workers=max_workers)
    return executor


def force_shutdown_executor():
    logger = getLogger()
    global executor
    with _exectuor_lock:
        if executor:
            executor.shutdown(wait=False, cancel_futures=True)
            executor=None
            logger.logMessage("[Buy Scanner] Executor force killed")
            

def _reset_globals(num_vars:[str],dicts:[str],locks:[str]):
    #for each listed arg iterate and clear
    global counter_lock, total_tickers,remaining_tickers, processed_counter, api_worker_lock,total_iterated
    global fallback_cache, executor

    # Shutdown old executor if it exists
    if executor:
        try:
            executor.shutdown(wait=True)
        except Exception:
            pass
        executor = None

    counter_lock = threading.Lock()
    api_worker_lock = threading.Lock()
    total_tickers = 0
    remaining_tickers = 0
    processed_counter = 0
    total_iterated = 0

    # Reset fallback cache
    fallback_cache = _DictCacheFallback()