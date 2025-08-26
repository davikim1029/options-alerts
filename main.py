# main.py
import os
import argparse
from dotenv import load_dotenv
from services.apitest import run_api_test
from services.scanner import run_scan
from services.etrade_consumer import EtradeConsumer
from services.news_aggregator import aggregate_headlines_smart
from strategy.sentiment import SectorSentimentStrategy
from services.scanner_utils import get_active_tickers
from encryption.encryptItems import encryptEtradeKeySecret
import json
from services.utils import get_boolean_input

def get_mode_from_prompt():
    modes = [
        ("scan", "Run scanner (alerts only)"),
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
    load_dotenv()
    parser = argparse.ArgumentParser(description="OptionsAlerts CLI")
    parser.add_argument("--mode", help="Mode to run")
    parser.add_argument("--sandbox", type=str, help="Use Sandbox credentials? true/false")
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
            useSandbox = get_boolean_input("Run in Sandbox mode? (Default is False)")  # defaults False if Enter

        if mode in ["scan"]:
            consumer = EtradeConsumer(sandbox=useSandbox,debug=debug)
            run_scan(mode=mode, consumer=consumer,debug=debug)

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
