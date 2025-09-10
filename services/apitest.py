# apitest.py

def run_api_test(consumer):
    print("\n E*TRADE API Testing Mode\n")
    print("Choose an action:")
    print("1. Get account balance")
    print("2. Get current holdings")
    print("3. Lookup stock & option info")
    print("q. Quit")

    while True:
        choice = input("\nEnter choice (1–5 or q): ").strip()

        if choice == "1":
            accts = consumer.get_accounts()
            for idx, acct in enumerate(accts):
                print(f"Account #{idx + 1}")
                for key, value in acct.items():
                    print(f"  {key}: {value}")
                print("-" * 20)
                acct_id = acct["accountId"]
                acct_id_key = acct["accountIdKey"]
                print(f"Balances for Acct: {acct_id}")
                inst_type = acct["institutionType"]
                balanceResponse = consumer.get_balance(acct_id_key,inst_type)
                for key, value in balanceResponse.items():
                    print(f"  {key}: {value}")
        elif choice == "2":
            positions = consumer.get_positions()
            print(f"\n{len(positions)} positions:")
            for p in positions:
                print(p)

        elif choice == "3":
            symbol = input("Enter stock symbol: ").strip().upper()
            quote = consumer.get_quote(symbol)
            chain = consumer.get_option_chain(symbol)
            print("QUOTE:", quote)
            print("")
            print(f"Options ({len(chain)}):")
            for opt in chain[:5]:
                print(opt)

        elif choice.lower() == "q":
            print("Exiting test mode.")
            break
        else:
            print("Invalid choice.")
