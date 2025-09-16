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

    for ticker, info in data.items():
        try:
            primary = info["Value"]["PrimaryStrategy"]
            secondary = info["Value"]["SecondaryStrategy"]

            primary_key, primary_val = next(iter(primary.items()))
            secondary_key, secondary_val = next(iter(secondary.items()))

            if not primary_val["Result"]:  # Failed primary
                reason = f"Primary - {primary_val['Message']}"
            else:  # Passed primary, check secondary
                if not secondary_val["Result"]:
                    if secondary_val["Message"] != "Failed Primary Evaluation":
                        reason = f"Secondary - {secondary_val['Message']}"
                    else:
                        continue
                else:
                    continue  # Passed both → not a failure
            failure_reasons.append(reason)

        except Exception as e:
            print(f"Error processing {ticker}: {e}")

    counter = Counter(failure_reasons)

    if not counter:
        print("No failures found!")
        return counter

    # Top 3 reasons
    top_3 = counter.most_common(3)
    print("\nTop 3 Failure Reasons:")
    for idx, (reason, count) in enumerate(top_3, start=1):
        print(f"{idx}. {reason} ({count} tickers)")

    # Breakdown sorted: Primary first, then Secondary
    print("\nFull Breakdown by Reason:")
    for reason, count in sorted(counter.items(), key=lambda x: (0 if x[0].startswith("Primary") else 1, -x[1])):
        print(f"{reason}: {count}")

    print(f"\nTotal Failed Tickers: {len(failure_reasons)} / {len(data)}")

    return counter


def prompt_for_file(default_folder: str = "."):
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
    default_folder = "data/ticker_eval"  # change to your cache folder
    file_path = prompt_for_file(default_folder)
    analyze_failures(file_path)
