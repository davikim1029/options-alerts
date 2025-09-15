def run_buy_scan(stop_event, consumer=None, caches=None, debug=False):
    logger = getLogger()
    logger.logMessage("[Buy Scanner] Starting run_buy_scan")
    _reset_globals()

    # Config
    news_cache = getattr(caches, "news", None)
    rate_cache = getattr(caches, "rate", None)
    ticker_cache = getattr(caches, "ticker", None)
    last_ticker_cache = getattr(caches, "last_seen", None)

    buy_strategies = {
        "Primary": [OptionBuyStrategy()],
        "Secondary": [SectorSentimentStrategy(news_cache=news_cache, rate_cache=rate_cache)],
    }

    tickers_map = get_active_tickers(ticker_cache=ticker_cache)
    ticker_keys = list(tickers_map.keys())
    if not ticker_keys:
        logger.logMessage("[Buy Scanner] No tickers to process.")
        return

    start_index = 0
    last_seen = last_ticker_cache.get("lastSeen") if last_ticker_cache else None
    if last_seen and last_seen in ticker_keys:
        start_index = ticker_keys.index(last_seen) + 1
    if start_index >= len(ticker_keys) - 1:
        start_index = 0

    remaining_tickers = ticker_keys[start_index:]
    global total_tickers, remaining_ticker_count
    total_tickers = remaining_ticker_count = len(remaining_tickers)

    logger.logMessage(f"[Buy Scanner] {start_index} tickers processed earlier. {remaining_ticker_count} remaining.")

    context = {"consumer": consumer}
    try:
        context["exposure"] = consumer.get_open_exposure()
    except TokenExpiredError:
        logger.logMessage("[Buy Scanner] Token expired gathering exposure, pausing scanner.")
        send_alert("E*TRADE token expired. Please re-authenticate.")
        token_status.wait_until_valid(check_interval=30)
        consumer.load_tokens(generate_new_token=False)
        context["exposure"] = consumer.get_open_exposure()
    except Exception as e:
        logger.logMessage(f"[Buy Scanner] Error getting open exposure: {e}")

    # Threading config
    scanner_cfg = getattr(caches, "scanner_config", {}) or {}
    num_api_threads = int(scanner_cfg.get("api_threads", 4))
    num_analysis_threads = int(scanner_cfg.get("analysis_threads", max(2, num_api_threads)))
    api_semaphore_limit = int(scanner_cfg.get("api_semaphore", 4))

    fetch_q, result_q = queue.Queue(), queue.Queue()
    api_semaphore = threading.Semaphore(api_semaphore_limit)

    def api_worker(stop_evt):
        logger.logMessage(f"[Buy Scanner] API worker {threading.current_thread().name} started")
        while not stop_evt.is_set():
            try:
                ticker = fetch_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if ticker is None:
                fetch_q.task_done()
                break
            with api_semaphore:
                try:
                    options, has_options = consumer.get_option_chain(ticker)
                    result_q.put((ticker, options, bool(has_options)))
                except TokenExpiredError:
                    logger.logMessage("[Buy Scanner] TokenExpiredError in api_worker.")
                    send_alert("E*TRADE token expired. Please re-authenticate.")
                    token_status.wait_until_valid(check_interval=30)
                    consumer.load_tokens(generate_new_token=False)
                    fetch_q.put(ticker)
                except Exception as e:
                    logger.logMessage(f"[Buy Scanner] Error fetching {ticker}: {e}")
                    result_q.put((ticker, None, False))
                finally:
                    fetch_q.task_done()
        logger.logMessage(f"[Buy Scanner] API worker {threading.current_thread().name} exiting")

    def analysis_worker(stop_evt):
        logger.logMessage(f"[Buy Scanner] Analysis worker {threading.current_thread().name} started")
        while not stop_evt.is_set():
            try:
                item = result_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                result_q.task_done()
                break
            ticker, options, has_options = item
            if has_options and options:
                try:
                    analyze_ticker(ticker, options, context, buy_strategies, caches, {}, debug)
                except Exception as e:
                    logger.logMessage(f"[Buy Scanner] analyze_ticker {ticker} error: {e}")
            else:
                (getattr(caches, "ignore", None) or IgnoreTickerCache()).add(ticker, "")
            result_q.task_done()
        logger.logMessage(f"[Buy Scanner] Analysis worker {threading.current_thread().name} exiting")

    # Start workers
    api_threads = [
        threading.Thread(target=api_worker, args=(stop_event,), name=f"BuyAPIT{i}", daemon=True)
        for i in range(num_api_threads)
    ]
    for t in api_threads:
        t.start()
    analysis_threads = [
        threading.Thread(target=analysis_worker, args=(stop_event,), name=f"BuyAnalysis{i}", daemon=True)
        for i in range(num_analysis_threads)
    ]
    for t in analysis_threads:
        t.start()

    # Feed tickers
    for t in remaining_tickers:
        fetch_q.put(t)

    # Monitor queues until done OR stop_event triggered
    while not stop_event.is_set():
        if fetch_q.unfinished_tasks == 0 and result_q.unfinished_tasks == 0:
            break
        stop_event.wait(0.5)

    # If stopping early, drain queues so joins don’t hang
    if stop_event.is_set():
        while not fetch_q.empty():
            try:
                fetch_q.get_nowait()
                fetch_q.task_done()
            except queue.Empty:
                break
        while not result_q.empty():
            try:
                result_q.get_nowait()
                result_q.task_done()
            except queue.Empty:
                break

    # Stop workers gracefully
    for _ in api_threads:
        fetch_q.put(None)
    for _ in analysis_threads:
        result_q.put(None)

    for t in api_threads + analysis_threads:
        t.join(timeout=2)

    try:
        post_process_results([], caches, stop_event)
    except Exception as e:
        logger.logMessage(f"[Buy Scanner] post_process_results error: {e}")

    logger.logMessage("[Buy Scanner] Run complete")
    
  
  
