# main.py
import os
import sys
import argparse
from dotenv import load_dotenv
from services.utils import yes_no
from services.apitest import run_api_test
from services.scanner.scanner import run_scan
from services.etrade_consumer import EtradeConsumer, force_generate_new_token
from services.news_aggregator import aggregate_headlines_smart
from strategy.sentiment import SectorSentimentStrategy
from services.scanner.scanner_utils import get_active_tickers
from encryption.encryptItems import encryptEtradeKeySecret
from services.logging.logger_singleton import logger
from services.core.shutdown_handler import ShutdownManager
from services.scanner.scanner_entry import start_scanner
from services.threading.thread_manager import ThreadManager

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
        
        if choice in ("q", "quit", "6"):
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
    logger.logMessage("Script started.")
    
    # Initialize shutdown manager
    ShutdownManager.init(error_logger=logger.logMessage)

    load_dotenv()
    parser = argparse.ArgumentParser(description="OptionsAlerts CLI")
    parser.add_argument("--mode", help="Mode to run")
    parser.add_argument("--sandbox", type=str, help="Use Sandbox credentials? true/false")
    parser.add_argument("--web_browser", type=str, help="Launch browser for auth if necessary")
    args = parser.parse_args()
    
    while True:
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
            
        else:
            print("Invalid mode selected.")
          
        #force shutdown of threads  
        ThreadManager.instance().stop_all()



if __name__ == "__main__":
    main()
