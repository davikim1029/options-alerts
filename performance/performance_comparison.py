import json
import os
from datetime import datetime
from pathlib import Path


def load_json(file_path):
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    with open(file_path) as f:
        return json.load(f)

def analyze_timestamps(data):
    # Extract timestamps and sort them
    timestamps = [datetime.fromisoformat(v["Timestamp"]) for v in data.values()]
    timestamps.sort()

    if not timestamps:
        return 0, 0

    # Total elapsed time (start to finish)
    total_time = (timestamps[-1] - timestamps[0]).total_seconds()

    # Average processing time per ticker
    avg_time = total_time / len(timestamps)

    return total_time, avg_time

def get_valid_path(prompt_text):
    while True:
        path = input(prompt_text).strip()
        if os.path.isfile(path):
            return path
        else:
            print(f"❌ File not found: {path}. Please try again.\n")

def compare_evals():
    print("=== JSON Ticker Processing Speed Comparison ===")
    
    #file1 = get_valid_path("Enter path to first JSON file: ")
    file1 = prompt_for_file()
    #file2 = get_valid_path("Enter path to second JSON file: ")
    file2 = prompt_for_file(file_to_exclude=file1.split("/")[-1])
    
    if file1 == file2:
        print("The same file was selected for comparison, nothing to compare.")
        return

    data1 = load_json(file1)
    data2 = load_json(file2)

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
        
        
def prompt_for_file(default_folder: str = "data/ticker_eval/cleaned", file_to_exclude: str = ""):
    folder = Path(default_folder)
    files = sorted([f for f in folder.glob("*.json") if f.is_file()])

    if not files:
        print(f"No JSON files found in {default_folder}. Please enter a file path.")
        return input("Enter file path: ").strip()

    print(f"\nFiles found in {default_folder}:")
    
    
    display_files = [f for f in files if f.name != file_to_exclude]
    for idx, f in enumerate(display_files, start=1):
        print(f"{idx}. {f.name}")

    print(f"{len(display_files)+1}. Enter custom file path")

    while True:
        choice = input("Select an option: ").strip()
        if choice.isdigit():
            choice = int(choice)
            if 1 <= choice <= len(display_files):
                return str(display_files[choice - 1])
            elif choice == len(display_files) + 1:
                return input("Enter file path: ").strip()
        print("Invalid selection, try again.")


def perf_comp_entry():
    compare_evals()
