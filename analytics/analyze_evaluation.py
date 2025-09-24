import json
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime


def normalize_score(score):
    """Convert score to int if possible, else None."""
    if score in (None, "N/A"):
        return None
    try:
        return int(score)
    except (ValueError, TypeError):
        return None


def analyze_failures(file_path: str):
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path, "r") as f:
        data = json.load(f)

    failure_reasons = []
    score_counts = defaultdict(lambda: defaultdict(int))
    secondary_breakdown = defaultdict(Counter)  # primary_score -> Counter of reasons

    for ticker, info in data.items():
        try:
            # --- Handle duplicates (list of evals) ---
            if isinstance(info, list):
                latest_eval = max(
                    info,
                    key=lambda e: datetime.fromisoformat(e.get("Timestamp", "1970-01-01T00:00:00"))
                )
                value = latest_eval.get("Value", {})
            elif isinstance(info, dict):
                value = info.get("Value", {})
            else:
                continue

            primary = value.get("PrimaryStrategy", {}).get("OptionBuyStrategy", {})
            secondary = list(value.get("SecondaryStrategy", {}).values())[0] if value.get("SecondaryStrategy") else {}

            primary_failure = False
            primary_score = normalize_score(primary.get("Score"))

            # --- Primary evaluation ---
            if not primary.get("Result", True):
                score_counts["Primary"][primary_score] += 1
                reason = f"Primary - {primary.get('Message', 'No message')}"
                failure_reasons.append(reason)
                primary_failure = True

            # --- Secondary evaluation ---
            if (not primary_failure
                and secondary
                and not secondary.get("Result", True)
                and secondary.get("Message") != "Primary Strategy did not pass, secondary not evaluated"
            ):
                # Secondary groups by *primary* score
                if primary_score is not None:
                    reason = secondary.get("Message", "No message")
                    secondary_breakdown[primary_score][reason] += 1
                    failure_reasons.append(f"Secondary - {reason}")
                else:
                    score_counts["Secondary"][None] += 1
                    failure_reasons.append(f"Secondary - {secondary.get('Message', 'No message')}")

        except Exception as e:
            print(f"Error processing {ticker}: {e}")

    counter = Counter(failure_reasons)

    if not counter:
        print("No failures found!")
        return counter

    # --- Top 3 failure reasons ---
    print("\n=== Top 3 Failure Reasons ===")
    for idx, (reason, count) in enumerate(counter.most_common(3), start=1):
        print(f"{idx}. {reason} ({count} options)")

    # --- Score distributions ---
    print("\n=== Primary Score Distribution ===")
    for score, count in sorted(score_counts["Primary"].items(), key=lambda x: (x[0] is None, x[0])):
        label = "N/A" if score is None else score
        print(f"Score {label}: {count} options")

    print("\n=== Secondary Score Distribution (by Primary Score) ===")
    for score in sorted(secondary_breakdown.keys(), key=lambda x: (x is None, x)):
        label = "N/A" if score is None else score
        total = sum(secondary_breakdown[score].values())
        print(f"\nPrimary Score {label}: {total} secondary failures")
        # show top 3 reasons
        for reason, count in secondary_breakdown[score].most_common(3):
            pct = (count / total) * 100 if total > 0 else 0
            print(f"  {reason}: {count} ({pct:.1f}%)")

    print(f"\nTotal Failed Options: {len(failure_reasons)} / {len(data)}")

    # --- Ask if user wants full breakdown ---
    choice = input("\nWould you like to see the full detailed breakdown? (y/n): ").strip().lower()
    if choice != "y":
        return counter

    # --- Full breakdown ---
    print("\n=== Full Breakdown by Reason ===")
    for reason, count in sorted(
        counter.items(),
        key=lambda x: (0 if x[0].startswith("Primary") else 1, -x[1])
    ):
        print(f"{reason}: {count}")

    print("\n=== Full Secondary Breakdown by Primary Score ===")
    for score in sorted(secondary_breakdown.keys(), key=lambda x: (x is None, x)):
        label = "N/A" if score is None else score
        print(f"\nPrimary Score {label}:")
        for reason, count in sorted(secondary_breakdown[score].items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}")

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


def analyze_secondary_outcomes(file_path: str, top_n: int = 3):
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path, "r") as f:
        data = json.load(f)

    secondary_passed = 0
    failure_reasons = []

    for ticker, info in data.items():
        try:
            # Handle duplicates (list of evals)
            if isinstance(info, list):
                latest_eval = max(
                    info,
                    key=lambda e: datetime.fromisoformat(e.get("Timestamp", "1970-01-01T00:00:00"))
                )
                value = latest_eval.get("Value", {})
            elif isinstance(info, dict):
                value = info.get("Value", {})
            else:
                continue

            primary = value.get("PrimaryStrategy", {}).get("OptionBuyStrategy", {})
            secondary = list(value.get("SecondaryStrategy", {}).values())[0] if value.get("SecondaryStrategy") else {}

            # Skip if primary failed
            if not primary.get("Result", True):
                continue

            # --- Primary passed: check secondary ---
            if secondary.get("Result", False):
                secondary_passed += 1
            else:
                reason = secondary.get("Message", "Unknown reason")
                failure_reasons.append(reason)

        except Exception as e:
            print(f"Error processing {ticker}: {e}")

    counter = Counter(failure_reasons)
    total_primary_passed = secondary_passed + sum(counter.values())

    print("\n=== Secondary Strategy Analysis ===")
    print(f"Total with Primary Passed: {total_primary_passed}")
    print(f"Secondary Passed: {secondary_passed}")
    print(f"Secondary Failed: {sum(counter.values())}")

    if counter:
        print(f"\n--- Top {top_n} Secondary Failure Reasons ---")
        for idx, (reason, count) in enumerate(counter.most_common(top_n), start=1):
            print(f"{idx}. {reason} ({count} options)")

        choice = input("\nWould you like to see the full detailed breakdown? (y/n): ").strip().lower()
        if choice == "y":
            print("\n=== Full Breakdown of Secondary Failures ===")
            for reason, count in sorted(counter.items(), key=lambda x: -x[1]):
                print(f"{reason}: {count}")

    return {
        "total_primary_passed": total_primary_passed,
        "secondary_passed": secondary_passed,
        "secondary_failed": dict(counter)
    }
    
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
    print("\n--- Primary Analysis ---")
    analyze_failures(file_path)

    print("\n--- Secondary Analysis ---")
    analyze_secondary_outcomes(file_path)