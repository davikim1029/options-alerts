import json
from collections import Counter
from pathlib import Path
from datetime import datetime

def analyze_failures(file_path: str):
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path, "r") as f:
        data = json.load(f)

    failure_reasons = []
    score_counts = Counter()

    for ticker, info in data.items():
        try:
            # --- Handle duplicates (list of evals) ---
            if isinstance(info, list):
                # Pick the latest evaluation based on timestamp
                latest_eval = max(
                    info,
                    key=lambda e: datetime.fromisoformat(e.get("Timestamp", "1970-01-01T00:00:00"))
                )
                value = latest_eval.get("Value", {})
            elif isinstance(info, dict):
                # Old format (single dict)
                value = info.get("Value", {})
            else:
                continue  # Skip unexpected formats

            primary = value.get("PrimaryStrategy", {}).get("OptionBuyStrategy", {})
            secondary = list(value.get("SecondaryStrategy", {}).values())[0] if value.get("SecondaryStrategy") else {}

            primary_failure = False
            # --- Primary evaluation ---
            if not primary.get("Result", True):
                score = primary.get("Score", "N/A")
                if score != "N/A":
                    score_counts[score] += 1
                else:
                    score_counts[-999] +=1
                reason = f"Primary - {primary.get('Message', 'No message')}"
                failure_reasons.append(reason)
                primary_failure = True

            # --- Secondary evaluation (only if not suppressed) ---
            if (primary_failure == False 
                and secondary
                and not secondary.get("Result", True)
                and secondary.get("Message") != "Primary Strategy did not pass, secondary not evaluated"
            ):
                score = secondary.get("Score", "N/A")
                if score != "N/A":
                    score_counts[score] += 1
                failure_reasons.append(f"Secondary - {secondary.get('Message', 'No message')}")

        except Exception as e:
            print(f"Error processing {ticker}: {e}")

    counter = Counter(failure_reasons)

    if not counter:
        print("No failures found!")
        return counter

    # --- Top 3 failure reasons ---
    top_3 = counter.most_common(3)
    print("\n=== Top 3 Failure Reasons ===")
    for idx, (reason, count) in enumerate(top_3, start=1):
        print(f"{idx}. {reason} ({count} tickers)")

    # --- Score distribution ---
    print("\n=== Score Distribution ===")
    for score, count in sorted(score_counts.items()):
        print(f"Score {score}: {count} tickers")

    print(f"\nTotal Failed Tickers: {len(failure_reasons)} / {len(data)}")

    # --- Ask if user wants full breakdown ---
    choice = input("\nWould you like to see the full detailed breakdown? (y/n): ").strip().lower()
    if choice != "y":
        return counter

    # --- Full breakdown ---
    print("\n=== Full Breakdown by Reason ===")
    for reason, count in sorted(counter.items(), key=lambda x: (0 if x[0].startswith("Primary") else 1, -x[1])):
        print(f"{reason}: {count}")

    return counter


def prompt_for_file(default_folder: str = "data/ticker_eval/cleaned") -> str:
    folder = Path(default_folder)
    files = sorted([f for f in folder.glob("*.json") if f.is_file()])

    if not files:
        print(f"No JSON files found in {default_folder}. Please enter a file path.")
        return input("Enter file path: ").strip()

    print(f"\nFiles found in {default_folder}:")
    for idx, f in enumerate(files, start=1):
        print(f"{idx}. {f.name}")
    print(f"{len(files)+1}. Current evaluation cache")
    print(f"{len(files)+2}. Enter custom file path")
    print(f"{len(files)+3}. Exit")

    while True:
        choice = input("Select an option: ").strip()
        if choice.isdigit():
            choice = int(choice)
            if 1 <= choice <= len(files):
                return str(files[choice - 1])
            elif choice == len(files) +1:
                return "cache/evaluated.json"
            elif choice == len(files) + 2:
                return input("Enter file path: ").strip()
            elif choice == len(files) + 3:
                return "exit"
        print("Invalid selection, try again.")


def analysis_entry():
    found = False
    while not found:
        try:
            file_path = prompt_for_file()
            if (file_path.lower() == "exit"):
                print("Exiting...")
                return
            path = Path(file_path)
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"File not found: {file_path}")
        except Exception as e:
            print(e)
            continue
        found = True
    analyze_failures(file_path)
