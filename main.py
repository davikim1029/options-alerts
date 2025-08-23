# main.py
import os
import argparse
from dotenv import load_dotenv
from services.apitest import run_api_test
from services.scanner import run_scan
from services.etrade_consumer import EtradeConsumer
from services.modeltest import validate_api_model
from encryption.encryptItems import encryptEtradeKeySecret
from strategy.buy import OptionBuyStrategy
from services.utils import get_boolean_input

def get_mode_from_prompt():
    modes = [
        ("scan", "Run scanner (alerts only)"),
        ("paper", "Run scanner + sandbox trades"),
        ("live", "Run scanner + real trades"),
        ("generate-models", "Generate all API models"),
        ("new-model", "Generate model for specific API URL"),
        ("test-api", "Interactive test of E*TRADE API functions"),
        ("test-model", "Validate if API response matches a model"),
        ("encrypt-etrade", "Encrypt Etrade Key And Secret")
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
    parser.add_argument("--url", help="Required for 'new-model' or 'test-model'")
    parser.add_argument("--model", help="Required for 'test-model'")
    parser.add_argument("--sandbox", type=str, help="Use Sandbox credentials? true/false")
    args = parser.parse_args()

    mode = args.mode.lower() if args.mode else get_mode_from_prompt()
    debug = False

    # Convert sandbox argument to boolean
    if args.sandbox is not None:
        useSandbox = args.sandbox.lower() in ["true", "1", "yes"]
    else:
        useSandbox = get_boolean_input("Run in Sandbox mode? (Default is False)")  # defaults False if Enter

    if mode in ["scan", "paper", "live"]:
        consumer = EtradeConsumer(sandbox=useSandbox,debug=debug)
        run_scan(mode=mode, consumer=consumer,debug=debug)

    elif mode == "generate-models":
        from classgenerator.cli import generate_from_all_known_endpoints
        generate_from_all_known_endpoints()

    elif mode == "new-model":
        url = args.url or input("Enter API URL: ").strip()
        from classgenerator.cli import generate_from_url
        generate_from_url(url, output_dir="./models/generated")

    elif mode == "test-api":
        consumer = EtradeConsumer(sandbox=useSandbox)
        run_api_test(consumer)

    elif mode == "test-model":
        url = args.url or input("Enter API URL: ").strip()
        model = args.model or input("Enter model class name: ").strip()
        validate_api_model(url, model)

    elif mode == "encrypt-etrade":
        encryptEtradeKeySecret(useSandbox)

    else:
        print("Invalid mode selected.")

if __name__ == "__main__":
    main()
