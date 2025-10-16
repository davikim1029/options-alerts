import json
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime
from analytics.analyze_evaluation import prompt_for_file

def normalize_score(score):
    """Convert score to float if possible, else None."""
    if score in (None, "N/A"):
        return None
    try:
        return float(score)
    except (ValueError, TypeError):
        return None


def load_latest_evals(file_path: str):
    """Load JSON file and return the latest evaluation for each ticker."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path, "r") as f:
        data = json.load(f)

    latest_data = {}
    for ticker, info in data.items():
        try:
            if isinstance(info, list):
                latest_eval = max(
                    info,
                    key=lambda e: datetime.fromisoformat(e.get("Timestamp", "1970-01-01T00:00:00"))
                )
            else:
                latest_eval = info
            latest_data[ticker] = latest_eval.get("Value", {})
        except Exception as e:
            print(f"Error processing {ticker}: {e}")
    return latest_data


def analyze_successes(file_path: str, top_n: int = 3):
    """Analyze primary strategy successes and key attributes."""
    data = load_latest_evals(file_path)

    success_reasons = []
    score_counts = defaultdict(int)

    # Optional: track other metrics if you want, e.g., "Score buckets", "Days to expiry", etc.
    # For now, we just focus on Score and Message attributes.
    for ticker, value in data.items():
        try:
            primary = value.get("PrimaryStrategy", {}).get("OptionBuyStrategy", {})
            primary_score = normalize_score(primary.get("Score"))

            if primary.get("Result", False):
                score_counts[primary_score] += 1
                reason = primary.get("Message", "No message")
                success_reasons.append(f"Primary - {reason}")
        except Exception as e:
            print(f"Error processing {ticker}: {e}")

    counter = Counter(success_reasons)

    if not counter:
        print("No successes found!")
        return counter

    # --- Top 3 success reasons ---
    print("\n=== Top 3 Success Reasons ===")
    for idx, (reason, count) in enumerate(counter.most_common(top_n), start=1):
        print(f"{idx}. {reason} ({count} options)")

    # --- Score distribution ---
    print("\n=== Primary Score Distribution for Successes ===")
    for score, count in sorted(score_counts.items(), key=lambda x: (x[0] is None, x[0])):
        label = "N/A" if score is None else score
        print(f"Score {label}: {count} options")

    print(f"\nTotal Successful Options: {len(success_reasons)} / {len(data)}")

    # --- Optional full breakdown ---
    choice = input("\nWould you like to see the full detailed breakdown of successes? (y/n): ").strip().lower()
    if choice == "y":
        print("\n=== Full Breakdown of Successes by Reason ===")
        for reason, count in sorted(counter.items(), key=lambda x: -x[1]):
            print(f"{reason}: {count}")

    return counter


def success_analysis_entry():
    """Entry point for primary success analysis."""
    while True:
        file_path = prompt_for_file()
        if file_path.lower() == "exit":
            print("Exiting...")
            return

        path = Path(file_path)
        if not path.exists() or not path.is_file():
            print(f"File not found: {file_path}")
            continue
        break

    print("\n--- Primary Success Analysis ---")
    analyze_successes(file_path)
