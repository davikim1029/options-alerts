# main.py
import os
import argparse
from dotenv import load_dotenv
from services.apitest import run_api_test
from services.scanner import run_scan
from services.etrade_consumer import EtradeConsumer,refresh_token
from services.news_aggregator import aggregate_headlines_smart
from strategy.sentiment import SectorSentimentStrategy
from services.scanner_utils import get_active_tickers
from encryption.encryptItems import encryptEtradeKeySecret
import json
from services.utils import get_boolean_input

os.environ["CUDA_VISIBLE_DEVICES"] = ""        # disable CUDA
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

def get_mode_from_prompt():
    modes = [
        ("scan", "Run scanner (alerts only)"),
        ("refresh-token","Refresh the Etrade token"),
        ("test-api", "Interactive test of E*TRADE API functions"),
        ("encrypt-etrade", "Encrypt Etrade Key And Secret"),
        ("test-newsapi","Hit a NewsApi Api"),
        ("quit","Exit program")
    ]

    print("📋 Available modes:")
    for i, (key, desc) in enumerate(modes, start=1):
        print(f"  {i}. {desc} [{key}]")
    
    choice = input("\nEnter mode number (default 1): ").strip()
    if not choice:
        return "scan"  # default
    try:
        index = int(choice) - 1
        if 0 <= index < len(modes):
            return modes[index][0]
    except ValueError:
        pass
    print("Invalid choice, defaulting to 'scan'.")
    return "scan"

def main():
    os.makedirs("cache", exist_ok=True)
    load_dotenv()
    parser = argparse.ArgumentParser(description="OptionsAlerts CLI")
    parser.add_argument("--mode", help="Mode to run")
    parser.add_argument("--sandbox", type=str, help="Use Sandbox credentials? true/false")
    parser.add_argument("--web_browser", type=str, help="Launch browser for auth if necessary")
    args = parser.parse_args()
    
    while True:
        mode = args.mode.lower() if args.mode else get_mode_from_prompt()
        
        if mode == "quit":
            break

        debug = False

        # Convert sandbox argument to boolean
        if args.sandbox is not None:
            useSandbox = args.sandbox.lower() in ["true", "1", "yes"] 
        else:
            useSandbox = False           
            
        if args.web_browser is not None:
            open_browser = args.web_browser.lower() in ["true", "1","yes"]
        else:
            open_browser = True


        if mode in ["scan"]:
            consumer = EtradeConsumer(sandbox=useSandbox,open_browser=open_browser,debug=debug)
            run_scan(mode=mode, consumer=consumer,debug=debug)
            
        elif mode in ["refresh-token"]:
            refresh_token()
            

        elif mode == "test-api":
            consumer = EtradeConsumer(sandbox=useSandbox)
            run_api_test(consumer)
            
        elif mode == "test-newsapi":
            consumer = EtradeConsumer(sandbox=useSandbox)
            tickers = get_active_tickers()
            #sentimentHandler = SectorSentimentStrategy()
            cnt = 0
            for ticker in tickers:
                try: 
                    headlines = aggregate_headlines_smart(ticker)

                    cnt = +cnt+1
                    # Convert JSON string → Python dict
                    print(headlines)
                    
                except Exception as e:
                    print(f"Error occurred for {ticker} | Error: {e}") 

        elif mode == "encrypt-etrade":
            encryptEtradeKeySecret(useSandbox)
            
        else:
            print("Invalid mode selected.")
            
if __name__ == "__main__":
    main()
