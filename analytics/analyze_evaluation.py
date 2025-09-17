import json
from collections import Counter
from pathlib import Path

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
            primary = info["Value"]["PrimaryStrategy"]["OptionBuyStrategy"]
            secondary = list(info["Value"]["SecondaryStrategy"].values())[0]

            # --- Primary evaluation ---
            if not primary["Result"]:
                if primary.get("Score") != "N/A":
                    score_counts[primary["Score"]] += 1
                reason = f"Primary - {primary['Message']}"
                failure_reasons.append(reason)

            # --- Secondary evaluation (only if not suppressed) ---
            if (
                not secondary["Result"]
                and secondary["Message"] != "Primary Strategy did not pass, secondary not evaluated"
            ):
                if secondary.get("Score") != "N/A":
                    score_counts[secondary["Score"]] += 1
                failure_reasons.append(f"Secondary - {secondary['Message']}")

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
    print(f"{len(files)+1}. Enter custom file path")

    while True:
        choice = input("Select an option: ").strip()
        if choice.isdigit():
            choice = int(choice)
            if 1 <= choice <= len(files):
                return str(files[choice - 1])
            elif choice == len(files) + 1:
                return input("Enter file path: ").strip()
        print("Invalid selection, try again.")


def analysis_entry():
    file_path = prompt_for_file()
    analyze_failures(file_path)