import json

# Path to your JSON file

def clean_ignore_cache():
    file_path = "cache/ignore_tickers.json"

    # Load the JSON file
    with open(file_path, "r") as f:
        data = json.load(f)

    # Filter to keep only entries with the exact error message
    error_message = "No options found"
    filtered_data = {
        k: v for k, v in data.items() if v.get("Value") == error_message
    }

    # Save the cleaned JSON back to file
    with open(file_path, "w") as f:
        json.dump(filtered_data, f, indent=2)

    print(f"Cleaned JSON written to {file_path}")
