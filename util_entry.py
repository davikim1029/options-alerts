# main.py
import os
import sys
from dotenv import load_dotenv
from services.etrade_consumer import force_generate_new_token
from encryption.encryptItems import encryptEtradeKeySecret
from analytics.analyze_evaluation import analysis_entry
from analytics.cleanup_eval import cleanup_entry
from analytics.review_ignore_cache import review_ignore
from performance.performance_comparison import perf_comp_entry
from testing.get_ticker_opts import get_ticker_opts_entry

# Disable GPU / MPS fallback
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"



def get_mode_from_prompt():
    """
    Interactive mode selection for CLI.
    """
    modes = [
      ("refresh-token", "Refresh the Etrade token"),
        ("analyze-tickers","Analyze evaluated tickers"),
        ("performance-compare","Compare performance on evaluated tickers"),
        ("cleanup-eval","Consolidate disparate eval files"),
        ("get-ticker-opts", "Get option results for a given ticker"),
        ("reset-tickers", "Reset the ticker caches for full review"),
        ("encrypt-etrade", "Encrypt Etrade Key And Secret"),
        ("review-ignore","Review Ignored Ticker Cache"),
        ("quit", "Exit program")
    ]

    while True:
        print("Available modes:")
        for i, (key, desc) in enumerate(modes, start=1):
            print(f"  {i}. {desc} [{key}]")
        
        choice = input("\nEnter mode number: ").strip()
        
        if choice in ("q", "quit", "6"):
            print("Exiting program.")
            return "quit"
        
        if not choice:
          continue
        try:
            index = int(choice) - 1
            if 0 <= index < len(modes):
                return modes[index][0]
        except ValueError:
            pass
        print("Invalid choice, try again.")
          
    #If we somehow are here, exit
    return "quit"



def main():
  
    load_dotenv()
    
    while True:
        mode = get_mode_from_prompt()
        if mode == "quit":
            sys.exit(0)
            break


        # --- Mode Handling ---
              
        elif mode == "refresh-token":
            force_generate_new_token()

          
        elif mode == "encrypt-etrade":
            encryptEtradeKeySecret(False)

        elif mode == "analyze-tickers":
            analysis_entry()
            
        elif mode == "performance-compare":
            perf_comp_entry()
            
        elif mode == "cleanup-eval":
            cleanup_entry()
            
        elif mode == "review-ignore":
            review_ignore()

        elif mode == "get-ticker-opts":
            get_ticker_opts_entry()
            
        elif mode == "reset-tickers":
            files_to_reset = ["evaluated","last_ticker"]
            for name in files_to_reset:
                file_path=f"cache/{name}.json"
                if os.path.exists(file_path):
                    # File exists, proceed with deletion
                    os.remove(file_path)
                    print(f"File '{file_path}' deleted successfully.")
                else:
                    print(f"File '{file_path}' does not exist.")
                        
        else:
            print("Invalid mode selected.")
        

if __name__ == "__main__":
    main()
