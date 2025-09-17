import json
from pathlib import Path

def prompt_for_folder(default_folder: str = "data/ticker_eval") -> Path:
    folder = Path(default_folder)
    if folder.exists() and folder.is_dir():
        return folder

    print(f"Default folder '{default_folder}' not found.")
    while True:
        user_input = input("Enter folder path: ").strip()
        folder = Path(user_input)
        if folder.exists() and folder.is_dir():
            return folder
        print("Invalid folder, try again.")

def merge_eval_files(folder: Path):
    files = sorted([f for f in folder.glob("*.json") if f.is_file()])
    if not files:
        print(f"No JSON files found in {folder}")
        return {}

    print(f"\nFound {len(files)} JSON files in {folder}")

    daily_data = {}  # { "YYYY-MM-DD": { "TICKER": { latest eval } } }

    for f in files:
        try:
            with open(f, "r") as infile:
                data = json.load(infile)
        except Exception as e:
            print(f"Skipping {f.name} (error: {e})")
            continue

        for ticker, eval_data in data.items():
            timestamp = eval_data.get("Timestamp")
            if not timestamp:
                continue

            day = timestamp.split("T")[0]
            eval_data["original_file"] = f.name

            # Initialize day dict
            if day not in daily_data:
                daily_data[day] = {}

            # Keep the most recent evaluation per ticker
            existing = daily_data[day].get(ticker)
            if not existing or existing["Timestamp"] < eval_data["Timestamp"]:
                daily_data[day][ticker] = eval_data

    return daily_data

def save_cleaned_daily_data(daily_data: dict, output_folder: Path):
    output_folder.mkdir(parents=True, exist_ok=True)

    for day, tickers in daily_data.items():
        out_file = output_folder / f"eval_cleaned_{day}.json"
        with open(out_file, "w") as f:
            json.dump(tickers, f, indent=2)
        print(f"Saved {len(tickers)} tickers to {out_file}")

def cleanup_entry():
    folder = prompt_for_folder()
    daily_data = merge_eval_files(folder)

    if not daily_data:
        print("No data to save.")
        return

    output_folder = folder / "cleaned"
    save_cleaned_daily_data(daily_data, output_folder)
    print("\nCleanup complete!")

if __name__ == "__main__":
    cleanup_entry()
