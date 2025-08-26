# etrade_consumer.py
import os
import json
from models.dataClassCreator import generate_dataclass
from services.utils import from_dict
from models.generated.Account import Account
from models.generated.Position import Position
from models.cache_manager import PositionCache
from datetime import datetime, timezone,timedelta
from cryptography.fernet import Fernet
from requests_oauthlib import OAuth1Session
from urllib.parse import urlencode
import webbrowser
from services.api_worker import ApiWorker,HttpMethod
from dacite import from_dict, Config
import time

class EtradeConsumer:
    def __init__(self,apiWorker:ApiWorker = None, sandbox=True, debug=False):
        self.debug = debug
        self.position_cache = PositionCache()
        self.sandbox = sandbox
        self.apiWorker = apiWorker
        if sandbox:
            envType="nonProd"
        else: 
            envType="prod"
        self.consumer_key,self.consumer_secret = self.load_encrypted_etrade_keysecret(sandbox)
        self.token_file = os.path.join("models", f"etrade_tokens_{envType}.json")
        self.base_url = "https://apisb.etrade.com" if sandbox else "https://api.etrade.com"

        if not self.consumer_key:
            raise Exception("Missing E*TRADE consumer key")

        if not os.path.exists(self.token_file):
            print("🔑 No token file found. Starting OAuth...")
            #self.consumer_secret = self.load_or_create_encrypted_secret()
            if not self.generate_token():
                raise Exception("Failed to generate access token.")
        else:
            self.load_tokens()
       
            
    def get(self,url:str,headers = None,params = None):
        if self.apiWorker is not None:
            response = self.apiWorker.call_api(HttpMethod.GET,url,headers=headers,params=params)
            if response.ok:
                return response.data
            else:
                try:
                    error = json.loads(response.response.text)
                    error_code = error["Error"]["code"]
                    if error_code == 10033:
                        symbol = params["symbol"]
                        print(f"The symbol {symbol} is invalid for api: {url}")
                    
                    #10031 means no options available for month
                    #10032 means no options available
                    elif (error_code != 10031 and error_code != 10032):
                        print(f"Error: {error}")
                        
                except Exception as e:
                    print(f"Error parsing error: {e}")
                    
                return None
            
        else:
            return self.session.get(url,headers= headers,params=params)
             
    
    def put(self,url,headers,params):
        if self.apiWorker is not None:
            response = self.apiWorker.call_api(HttpMethod.PUT, url,headers=headers,params=params )
            if response["ok"]:
                return response.data
            else:
                print(f"Error {response.status_code}: {response.error} ")
        else:
            return self.session.put(url,headers,params=params)

            
    def load_tokens(self):
        with open(self.token_file, "r") as f:
            token_data = json.load(f)

        self.oauth_token = token_data.get("oauth_token")
        self.oauth_token_secret = token_data.get("oauth_token_secret")

        self.session = OAuth1Session(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.oauth_token,
            resource_owner_secret=self.oauth_token_secret
        )

        # Validate and re-auth if needed
        if not self._validate_tokens():
            raise Exception("Failed to authenticate after token validation.")


    def _validate_tokens(self):
        try:
            url = f"{self.base_url}/v1/accounts/list.json"
            r = self.get(url)

            status_code = r.status_code
            if status_code == 200:
                return True
            elif status_code == 401:
            
                # Invalidate and regenerate
                print("[Token Validation] Deleting invalid token file and re-authenticating...")
                if os.path.exists(self.token_file):
                    os.remove(self.token_file)

                #self.consumer_secret = self.load_or_create_encrypted_secret()  # Just to be sure it's loaded
                return self.generate_token()
            else:
                 print(f"[Token Validation] Failed with status: {r.text}")

                


        except Exception as e:
            print(f"[Token Validation] Exception: {e}")
            if os.path.exists(self.token_file):
                os.remove(self.token_file)
            return self.generate_token()



    def generate_token(self, open_browser: bool = True, redirect_url: str = None):
        """
        Initiates the OAuth 1.0a flow and fetches the access token for authenticated API usage.

        Args:
            open_browser (bool): Whether to automatically open the auth URL in the web browser.
            redirect_url (str): Optional redirect URI if you're running a local callback server.

        Returns:
            bool: True if token was successfully generated, False otherwise.
        """
        try:
            request_token_url = f"{self.base_url}/oauth/request_token"
            oauth = OAuth1Session(self.consumer_key, client_secret=self.consumer_secret, callback_uri="oob")
            fetch_response = oauth.fetch_request_token(request_token_url)

            resource_owner_key = fetch_response.get("oauth_token")
            resource_owner_secret = fetch_response.get("oauth_token_secret")
            
            # Step 2: build the E*TRADE-specific authorize URL
            authorize_base    = "https://us.etrade.com/e/t/etws/authorize"
            params = {"key": self.consumer_key, "token": resource_owner_key}
            authorization_url = f"{authorize_base}?{urlencode(params)}"
            print("Please go to the following URL to authorize access:")
            print(authorization_url)
            if open_browser:
                webbrowser.open(authorization_url)

            verifier = input("Paste the verifier code here: ")

            access_token_url = f"{self.base_url}/oauth/access_token"
            oauth = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=resource_owner_key,
                resource_owner_secret=resource_owner_secret,
                verifier=verifier
            )
            token_response = oauth.fetch_access_token(access_token_url)

            self.oauth_token = token_response.get("oauth_token")
            self.oauth_token_secret = token_response.get("oauth_token_secret")

            self.session = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=self.oauth_token,
                resource_owner_secret=self.oauth_token_secret,
            )
            print("Access token obtained successfully.")
            self.save_tokens()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to generate token: {e}")
            return False
        
    def save_tokens(self):
        with open(self.token_file, "w") as f:
            json.dump({
                "oauth_token": self.oauth_token,
                "oauth_token_secret": self.oauth_token_secret
            }, f)
            
    def get_headers(self):
        return {
            "Content-Type": "application/json"
        }

    # In etrade_consumer.py (update get_option_chain)

    def get_option_chain(self, symbol):
        url = f"{self.base_url}/v1/market/optionchains.json"
        params = {
            "symbol": symbol,
            "includeWeekly": "true",
            "strategy": "SINGLE",
            "skipAdjusted": "false",
            "chainType": "CALL",
            "noOfStrikes": 5,
        }

        r = self.get(url, params=params)
        if r is None:
            return None,False
        chain_data = r.json()
        optionPairs = chain_data.get("OptionChainResponse")

        results = []
        for optionPair in optionPairs.get("OptionPair"):
            call = optionPair.get("Call")
            if not call:
                continue
            
            expiry_dict = optionPairs.get("SelectedED")
            expiry_date = datetime(
                year=expiry_dict["year"],
                month=expiry_dict["month"],
                day=expiry_dict["day"],
                tzinfo=timezone.utc
            )
            greeks = call.get("OptionGreeks", {})
            
            option = {
                "symbol": call.get("symbol"),
                "display": call.get("displaySymbol"),
                "underlyingPrice": optionPairs.get("nearPrice"),
                "lastPrice": call.get("lastPrice"),
                "ask": call.get("ask", 0),
                "askSize": call.get("askSize",0),
                "bid": call.get("bid",0),
                "bidSize": call.get("bidSize",0),
                "openInterest": call.get("openInterest",0),
                "inTheMoney": call.get("inTheMoney"),
                "volume": call.get("volume", 0),
                "openInterest": call.get("openInterest", 0),
                "expiryDate": expiry_date,  # YYYY-MM-DD
                "strikePrice": call.get("strikePrice", 0),
                "underlyingSymbol": symbol,

                # GREEKS:
                "delta": greeks.get("delta"),
                "gamma": greeks.get("gamma"),
                "theta": greeks.get("theta"),
                "vega": greeks.get("vega"),
                "impliedVolatility": greeks.get("iv"),
            }
            results.append(option)

        return results,True



    def flatten_option_response(self, json_data):
        results = []
        for date_entry in json_data.get("optionPairs", []):
            for option in date_entry:
                results.append({
                    "symbol": option["call"]["symbol"],
                    "ask": option["call"].get("ask", 0),
                    "volume": option["call"].get("volume", 0),
                    "expiry": option["call"]["expiryYearMonth"],
                })
        return results

    def get_accounts(self):
        url = f"{self.base_url}/v1/accounts/list.json"
        r = self.get(url)  # ✅ Use authenticated session
        try:
            accts = r.json().get("AccountListResponse").get("Accounts",[]).get("Account")
            return accts
        except Exception as e:
            print(f"[ERROR] Failed to parse account ID: {e}")
            return None



    def get_positions(self):
        if self.position_cache.is_cached("positions"):
            return self.position_cache.get("positions")
        accts = self.get_accounts()
        positions = []
        for idx,acct in enumerate(accts):
            acct_id = acct['accountId']
            acct_id_key = acct["accountIdKey"]
            url = f"{self.base_url}/v1/accounts/{acct_id_key}/portfolio.json"
            r = self.get(url)
            data = r.json()

            accounts = data.get("PortfolioResponse", {}).get("AccountPortfolio", [])
            for acct in accounts:
                #generate_dataclass(data=acct, name="Account", prepend_parent=False, nested_in_file=False)
                for pos in acct["Position"]:                
                    positions.append(pos)

        self.position_cache.add("positions",positions)
        return positions

    def get_greeks(self, option_symbol):
        url = f"{self.base_url}/v1/market/quote/{option_symbol}.json"
        r = self.get(url, headers=self.get_headers())
        data = r.json()
        quote = data.get("QuoteResponse", {}).get("QuoteData", [{}])[0]
        greeks = quote.get("OptionGreeks", {})

        return {
            "delta": greeks.get("delta"),
            "theta": greeks.get("theta"),
            "gamma": greeks.get("gamma"),
            "vega": greeks.get("vega")
        }

    def get_quote(self, symbol):
        url = f"{self.base_url}/v1/market/quote/{symbol}.json"
        r = self.get(url, headers=self.get_headers())
        data = r.json()
        return data.get("QuoteResponse", {}).get("QuoteData", [{}])[0]

    def get_balance(self,acct_id_key,instType):
        url = f"{self.base_url}/v1/accounts/{acct_id_key}/balance.json?instType={instType}&realTimeNAV=true.json"
        r = self.get(url)
        return r.json()["BalanceResponse"]["Computed"]
  
    #How much capital is currently outstanding (ie don't buy more than comfortable)
    def get_open_exposure(self):
        positions = self.get_positions()
        if positions is not None:
            return sum(p["totalCost"] for p in positions)
        return None
    
    #Load password for notifications         
    def load_encrypted_etrade_keysecret(self,sandbox):
        with open("encryption/secret.key", "rb") as key_file:
            key = key_file.read()

        sandbox_suffix = "sandbox" if sandbox else "prod"

        with open(f"encryption/etrade_consumer_key_{sandbox_suffix}.enc", "rb") as enc_file:
            encrypted_key = enc_file.read()
        
        fernet = Fernet(key)
        etrade_key=fernet.decrypt(encrypted_key).decode()
        
        with open(f"encryption/etrade_consumer_secret_{sandbox_suffix}.enc", "rb") as enc_file:
            encrypted_secret = enc_file.read()

        etrade_secret=fernet.decrypt(encrypted_secret).decode()
        return etrade_key,etrade_secret

    def load_config_value(self, key: str, fallback_env: str = None) -> str:
        return os.getenv(key) or fallback_env or None

    def parse_acquired(self,acquired_str):
        # If it's an integer or looks like one (epoch in ms)
        if isinstance(acquired_str, (int, float)):
            return datetime.fromtimestamp(acquired_str / 1000, tz=timezone.utc)
        
        # If it's a string of digits (epoch in ms)
        if isinstance(acquired_str, str) and acquired_str.isdigit():
            return datetime.fromtimestamp(int(acquired_str) / 1000, tz=timezone.utc)
        
        # Otherwise, assume it's already a formatted date string (YYYY-MM-DD)
        try:
            return datetime.strptime(acquired_str, "%Y-%m-%d")
        except Exception:
            raise ValueError(f"Unrecognized acquired date format: {acquired_str}")

    def is_stale(self,ts, max_age_seconds=3600):
        """
        Return True if timestamp `ts` is older than `max_age_seconds`.
        
        ts can be:
        - datetime object
        - int/float epoch in seconds
        - int/float epoch in milliseconds
        """
        # normalize timestamp into a datetime
        if isinstance(ts, (int, float)):
            # detect ms vs seconds (simple heuristic)
            if ts > 1e12:  # definitely ms
                ts = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            else:  # assume seconds
                ts = datetime.fromtimestamp(ts, tz=timezone.utc)
        elif not isinstance(ts, datetime):
            raise TypeError(f"Unsupported timestamp type: {type(ts)}")
        
        # always compare in UTC
        now = datetime.now(timezone.utc)
        return (now - ts) > timedelta(seconds=max_age_seconds)

