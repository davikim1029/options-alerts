import json
import os
from datetime import datetime

def load_json(file_path):
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

def main():
    print("=== JSON Ticker Processing Speed Comparison ===")
    
    file1 = get_valid_path("Enter path to first JSON file: ")
    file2 = get_valid_path("Enter path to second JSON file: ")

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

if __name__ == "__main__":
    main()
