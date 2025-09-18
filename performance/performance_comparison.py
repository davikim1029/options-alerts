import json
import os
from datetime import datetime
from pathlib import Path

def load_json(file_path):
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    with open(file_path) as f:
        return json.load(f)

def extract_latest_timestamps(data):
    """
    Returns a sorted list of datetime objects representing the latest evaluation
    for each ticker.
    """
    timestamps = []
    for ticker, info in data.items():
        try:
            if isinstance(info, list):
                # Pick the latest eval by timestamp
                latest_eval = max(
                    info,
                    key=lambda e: datetime.fromisoformat(e.get("Timestamp", "1970-01-01T00:00:00"))
                )
                ts = latest_eval.get("Timestamp")
            elif isinstance(info, dict):
                ts = info.get("Timestamp")
            else:
                continue

            if ts:
                timestamps.append(datetime.fromisoformat(ts))
        except Exception as e:
            print(f"Error processing {ticker}: {e}")
            continue

    timestamps.sort()
    return timestamps

def analyze_timestamps(data):
    timestamps = extract_latest_timestamps(data)

    if not timestamps:
        return 0, 0

    total_time = (timestamps[-1] - timestamps[0]).total_seconds()
    avg_time = total_time / len(timestamps) if len(timestamps) > 0 else 0

    return total_time, avg_time

def prompt_for_file(default_folder: str = "data/ticker_eval/cleaned", file_to_exclude: str = ""):
    folder = Path(default_folder)
    files = sorted([f for f in folder.glob("*.json") if f.is_file()])

    if not files:
        print(f"No JSON files found in {default_folder}. Please enter a file path.")
        return input("Enter file path: ").strip()

    display_files = [f for f in files if f.name != file_to_exclude]
    print(f"\nFiles found in {default_folder}:")
    for idx, f in enumerate(display_files, start=1):
        print(f"{idx}. {f.name}")
    print(f"{len(display_files)+1}. Enter custom file path")
    print(f"{len(display_files)+2}. Exit")

    while True:
        choice = input("Select an option: ").strip()
        if choice.isdigit():
            choice = int(choice)
            if 1 <= choice <= len(display_files):
                return str(display_files[choice - 1])
            elif choice == len(display_files) + 1:
                return input("Enter file path: ").strip()
            elif choice == len(display_files) + 2:
                return "exit"
        print("Invalid selection, try again.")

def compare_evals():
    print("=== JSON Ticker Processing Speed Comparison ===")
    
    found = False
    while not found:
        try:
            file1 = prompt_for_file()
            if (file1.lower() == "exit"):
                print("Exiting...")
                return
            data1 = load_json(file1)
        except Exception as e:
            print(e)
            continue
        found = True

    found = False
    while not found:
        try:
            file2 = prompt_for_file(file_to_exclude=Path(file1).name)
            if (file2.lower() == "exit"):
                print("Exiting...")
                return
            data2 = load_json(file2)
        except Exception as e:
            print(e)
            continue
        found = True

    
    if file1 == file2:
        print("The same file was selected for comparison, nothing to compare.")
        return
    
    
    total1, avg1 = analyze_timestamps(data1)
    total2, avg2 = analyze_timestamps(data2)

    print("\n=== Results ===")
    print(f"Method 1 ({file1}): Total {total1:.2f}s, Avg {avg1:.2f}s/ticker")
    print(f"Method 2 ({file2}): Total {total2:.2f}s, Avg {avg2:.2f}s/ticker")

    if avg1 < avg2:
        print("\n✅ Method 1 processed tickers faster on average.")
    elif avg2 < avg1:
        print("\n✅ Method 2 processed tickers faster on average.")
    else:
        print("\n⚖️ Both methods processed tickers at the same average speed.")

def perf_comp_entry():
    compare_evals()
