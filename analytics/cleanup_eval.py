import json
from pathlib import Path
from collections import defaultdict

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

    # { "YYYY-MM-DD": { "TICKER": [ { eval1 }, { eval2 } ] } }
    daily_data = defaultdict(lambda: defaultdict(list))

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
            daily_data[day][ticker].append(eval_data)

        # Delete the incremental file after merging
        try:
            f.unlink()
            print(f"Deleted {f.name}")
        except Exception as e:
            print(f"Could not delete {f.name}: {e}")

    return daily_data

def save_cleaned_daily_data(daily_data: dict, output_folder: Path):
    output_folder.mkdir(parents=True, exist_ok=True)

    for day, tickers in daily_data.items():
        out_file = output_folder / f"eval_cleaned_{day}.json"

        # Load existing file if present
        if out_file.exists():
            try:
                with open(out_file, "r") as f:
                    existing_data = json.load(f)
            except Exception as e:
                print(f"Warning: could not read existing {out_file}, overwriting. Error: {e}")
                existing_data = {}
        else:
            existing_data = {}

        # Ensure all existing entries are lists to allow appending
        for t, val in existing_data.items():
            if isinstance(val, dict):
                existing_data[t] = [val]

        # Append new evals
        for ticker, evals in tickers.items():
            if ticker not in existing_data:
                existing_data[ticker] = []
            existing_data[ticker].extend(evals)

        with open(out_file, "w") as f:
            json.dump(existing_data, f, indent=2)

        print(f"Saved {sum(len(v) for v in existing_data.values())} total evals to {out_file}")

def cleanup_entry():
    folder = prompt_for_folder()
    daily_data = merge_eval_files(folder)

    if not daily_data:
        print("No data to save.")
        return

    output_folder = folder / "cleaned"
    save_cleaned_daily_data(daily_data, output_folder)
    print("\nCleanup complete!")
