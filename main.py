# main.py
import os
import sys
import argparse
import time as pyTime
from dotenv import load_dotenv
from services.utils import yes_no
from services.apitest import run_api_test
from services.scanner.scanner import run_scan
from services.etrade_consumer import EtradeConsumer, force_generate_new_token
from services.news_aggregator import aggregate_headlines_smart
from strategy.sentiment import SectorSentimentStrategy
from services.scanner.scanner_utils import get_active_tickers
from encryption.encryptItems import encryptEtradeKeySecret
from services.logging.logger_singleton import getLogger
from services.core.shutdown_handler import ShutdownManager
from services.scanner.scanner_entry import start_scanner
from services.threading.thread_manager import ThreadManager
from services.utils import is_reload_flag_set,clear_reload_flag
from analytics.analyze_evaluation import analysis_entry
from analytics.cleanup_eval import cleanup_entry
from analytics.review_ignore_cache import review_ignore
from performance.performance_comparison import perf_comp_entry

# Disable GPU / MPS fallback
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"



def get_mode_from_prompt():
    """
    Interactive mode selection for CLI.
    """
    modes = [
        ("scan", "Run scanner (alerts only)"),
        ("refresh-token", "Refresh the Etrade token"),
        ("analyze-tickers","Analyze evaluated tickers"),
        ("performance-compare","Compare performance on evaluated tickers"),
        ("cleanup-eval","Consolidate disparate eval files"),
        ("review-ignore","Review Ignored Ticker Cache"),
        ("reset-tickers", "Reset the ticker caches for full review"),
        ("test-api", "Interactive test of E*TRADE API functions"),
        ("encrypt-etrade", "Encrypt Etrade Key And Secret"),
        ("test-newsapi", "Hit a NewsApi API"),
        ("quit", "Exit program")
    ]

    while True:
        print("Available modes:")
        for i, (key, desc) in enumerate(modes, start=1):
            print(f"  {i}. {desc} [{key}]")
        
        choice = input("\nEnter mode number (default 1): ").strip()
        
        if choice in ("q", "quit"):
            print("Exiting program.")
            return "quit"
        
        if not choice:
            run_scan = yes_no("Run Scan? (default is yes)")
            if run_scan:
                return "scan"
            else:
                continue
        try:
            index = int(choice) - 1
            if 0 <= index < len(modes):
                return modes[index][0]
        except ValueError:
            pass
        print("Invalid choice, try again.")
          
    #If we somehow are here, exit
    return "quit"



def main():
    # Ensure directories exist
    os.makedirs("cache", exist_ok=True)
    logger = getLogger()
    logger.logMessage("Script started.")
    
    load_dotenv()
    parser = argparse.ArgumentParser(description="OptionsAlerts CLI")
    parser.add_argument("--mode", help="Mode to run")
    parser.add_argument("--sandbox", type=str, help="Use Sandbox credentials? true/false")
    parser.add_argument("--web_browser", type=str, help="Launch browser for auth if necessary")
    args = parser.parse_args()
    
    while True:
        
        if is_reload_flag_set():
            clear_reload_flag()
            
            #Wait for threading to reset
            manager = ThreadManager.instance()
            logger.logMessage("Resetting thread manager")
            manager.reset_for_new_scan()                      
            logger.logMessage("Scanner restarting")
            start_scanner(debug=False)
            
        else:              
            mode = args.mode.lower() if args.mode else get_mode_from_prompt()
            args.mode = None #After get it mode the first time, reset for additional iterations
            
            if mode == "quit":
                ThreadManager.instance().stop_all()
                sys.exit(0)
                break

            debug = False

            # Convert sandbox argument to boolean
            useSandbox = False
            if args.sandbox is not None:
                useSandbox = args.sandbox.lower() in ["true", "1", "yes"] 
            
            # --- Mode Handling ---
            if mode == "scan":
                # Initialize shutdown manager
                ShutdownManager.init(error_logger=logger.logMessage)
                tm = ThreadManager.instance()
                tm.reset_for_new_scan()
                start_scanner(debug=debug)
                tm.wait_for_shutdown()
                
            elif mode == "refresh-token":
                force_generate_new_token()

            elif mode == "test-api":
                consumer = EtradeConsumer(sandbox=useSandbox, debug=debug)
                run_api_test(consumer)
            

            elif mode == "test-newsapi":
                consumer = EtradeConsumer(sandbox=useSandbox, debug=debug)
                tickers = get_active_tickers()
                cnt = 0
                for ticker in tickers:
                    try:
                        headlines = aggregate_headlines_smart(ticker)
                        cnt += 1
                        print(headlines)
                    except Exception as e:
                        print(f"Error occurred for {ticker} | Error: {e}") 

            elif mode == "encrypt-etrade":
                encryptEtradeKeySecret(useSandbox)
            
            elif mode == "analyze-tickers":
                analysis_entry()
                
            elif mode == "performance-compare":
                perf_comp_entry()
                
            elif mode == "cleanup-eval":
                cleanup_entry()
                
            elif mode == "review-ignore":
                review_ignore()
                    
            elif mode == "reset-tickers":
                files_to_reset = ["evaluated","last_ticker"]
                for name in files_to_reset:
                    file_path=f"cache/{name}.json"
                    if os.path.exists(file_path):
                        # File exists, proceed with deletion
                        os.remove(file_path)
                        print(f"File '{file_path}' deleted successfully.")
                    else:
                        print(f"File '{file_path}' does not exist.")
                            
            else:
                print("Invalid mode selected.")
          
        #force shutdown of threads  
        ThreadManager.instance().stop_all()



if __name__ == "__main__":
    main()
