import json

def delete_scores_from_eval():
    import json

    # --- Configuration ---
    input_file = "/Users/daviskim/Documents/GitHub/options/options-alerts/cache/evaluated.json"

    # --- Load JSON data from file ---
    with open(input_file, "r") as f:
        data = json.load(f)

    # --- Prompt for score to remove ---
    score_to_remove = prompt_score_to_remove()

    # --- Identify tickers to remove ---
    tickers_to_remove = set()
    for option_name, option_info in data.items():
        primary_strategy = option_info.get("Value", {}).get("PrimaryStrategy", {}).get("OptionBuyStrategy")
        if primary_strategy and primary_strategy.get("Score") == score_to_remove:
            ticker = option_name.split(" - ")[0]
            tickers_to_remove.add(ticker)

    # --- Remove all options for tickers with that score ---
    cleaned_data = {k: v for k, v in data.items() if k.split(" - ")[0] not in tickers_to_remove}

    # --- Save cleaned JSON back to the file ---
    with open(input_file, "w") as f:
        json.dump(cleaned_data, f, indent=4)

    print(f"Removed {len(data) - len(cleaned_data)} options from {len(tickers_to_remove)} tickers.")


# Prompt the user for an integer score to remove
def prompt_score_to_remove():
    while True:
        try:
            score_to_remove = int(input("Enter the score to remove: "))
            break
        except ValueError:
            print("Invalid input. Please enter an integer value.")
    return score_to_remove



if __name__ == "__main__":
    delete_scores_from_eval()
