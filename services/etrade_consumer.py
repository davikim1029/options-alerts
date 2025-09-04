# etrade_consumer.py
import os
import json
import webbrowser
from datetime import datetime, timezone, timedelta
from cryptography.fernet import Fernet
from requests_oauthlib import OAuth1Session
from urllib.parse import urlencode

from models.generated.Account import Account, PortfolioAccount
from models.generated.Position import Position
from models.option import OptionContract,Product,Quick,OptionGreeks,ProductId
from services.threading.api_worker import ApiWorker,HttpMethod
from services.utils import logMessage


class EtradeConsumer:
    def __init__(self, apiWorker: ApiWorker = None, open_browser=True, sandbox=False, debug=False):
        self.debug = debug
        self.sandbox = sandbox
        self.apiWorker = apiWorker
        envType = "nonProd" if sandbox else "prod"

        self.consumer_key, self.consumer_secret = self.load_encrypted_etrade_keysecret(sandbox)
        self.token_file = os.path.join("models", f"etrade_tokens_{envType}.json")
        self.base_url = "https://apisb.etrade.com" if sandbox else "https://api.etrade.com"

        if not self.consumer_key:
            raise Exception("Missing E*TRADE consumer key")

        if not os.path.exists(self.token_file):
            logMessage("🔑 No token file found. Starting OAuth...")
            if not self.generate_token(open_browser=open_browser):
                raise Exception("Failed to generate access token.")
        else:
            self.load_tokens(open_browser=open_browser)

    def get(self, url: str, headers=None, params=None):
        # Existing headers (may be None)
        headers = headers or {}  # ensure it's a dict

        # Add/overwrite Accept header
        headers.update({"Accept": "application/json"})
        
        if self.apiWorker is not None:
            response = self.apiWorker.call_api(HttpMethod.GET, url, headers=headers, params=params)
            if response.ok:
                if response.data is not None:       # parsed JSON
                    return response.data
                else:
                    return response.response.text   # fallback to raw string
            else:
                try:
                    error = json.loads(response.response.text)
                    error_code = error["Error"]["code"]
                    if error_code == 10033:
                        symbol = params["symbol"]
                        logMessage(f"The symbol {symbol} is invalid for api: {url}")
                    
                    #10031 means no options available for month
                    #10032 means no options available
                    elif (error_code != 10031 and error_code != 10032):
                        logMessage(f"Error: {error}")
                        
                except Exception as e:
                    logMessage(f"Error parsing error: {e} from response {json.dumps(response, indent=2, default=str)}")
        else:
            try:
                return self.session.get(url, headers=headers, params=params)
            except Exception as e:
                logMessage(f"[GET Exception] {e} for URL: {url}")
                return None




    def put(self, url, headers, params):
        if self.apiWorker is not None:
            response = self.apiWorker.call_api(HttpMethod.PUT, url, headers=headers, params=params)
            if response["ok"]:
                return response.data
            else:
                logMessage(f"Error {response.status_code}: {response.error}")
        else:
            return self.session.put(url, headers, params=params)

    # ------------------- TOKENS -------------------
    def load_tokens(self, open_browser=True):
        """Load saved tokens or generate/refresh if needed."""
        token_data = {}
        if os.path.exists(self.token_file):
            with open(self.token_file, "r") as f:
                token_data = json.load(f)

        self.oauth_token = token_data.get("oauth_token")
        self.oauth_token_secret = token_data.get("oauth_token_secret")

        if self.oauth_token and self.oauth_token_secret:
            self.session = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=self.oauth_token,
                resource_owner_secret=self.oauth_token_secret,
            )

        # Validate or refresh
        if not self._validate_tokens(open_browser=open_browser):
            raise Exception("Failed to authenticate after token validation.")

    def _validate_tokens(self, open_browser=True):
        """
        Validate current tokens; attempt refresh first.
        If refresh fails, fallback to full manual token generation.
        """
        try:
            if self._check_session_valid():
                return True

            logMessage("[Token Validation] Token invalid. Attempting refresh...")
            if self._refresh_token_if_needed():
                return True

            logMessage("[Token Validation] Refresh failed, generating new token...")
            return self.generate_token(open_browser=open_browser)
        except Exception as e:
            logMessage(f"[Token Validation] Exception: {e}")
            return self.generate_token(open_browser=open_browser)

    def _check_session_valid(self):
        """Simple API test to check if the current session is valid."""
        try:
            url = f"{self.base_url}/v1/accounts/list.json"
            r = self.get(url)
            return r and getattr(r, "status_code", 200) == 200
        except Exception as e:
            logMessage(f"[Token Validation] Session check failed: {e}")
            return False

    def _refresh_token_if_needed(self):
        """
        Attempt to refresh the current token automatically.
        Returns True if refresh succeeded, False otherwise.
        """
        try:
            if not hasattr(self, "oauth_token") or not self.oauth_token:
                return False

            # Example endpoint for refresh; adjust if E*TRADE supports it
            refresh_url = f"{self.base_url}/oauth/refresh_token"
            oauth = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=self.oauth_token,
                resource_owner_secret=self.oauth_token_secret
            )
            r = oauth.post(refresh_url)
            if r.status_code != 200:
                return False

            token_response = r.json()
            self.oauth_token = token_response.get("oauth_token")
            self.oauth_token_secret = token_response.get("oauth_token_secret")

            # Rebuild session
            self.session = OAuth1Session(
                self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=self.oauth_token,
                resource_owner_secret=self.oauth_token_secret,
            )
            self.save_tokens()
            logMessage("✅ Access token refreshed successfully.")
            return True
        except Exception as e:
            logMessage(f"[Token Refresh] Failed: {e}")
            return False

    def generate_token(self, open_browser=True):
        """Full manual OAuth flow (unchanged)."""
        try:
            request_token_url = f"{self.base_url}/oauth/request_token"
            oauth = OAuth1Session(self.consumer_key, client_secret=self.consumer_secret, callback_uri="oob")
            fetch_response = oauth.fetch_request_token(request_token_url)

            resource_owner_key = fetch_response.get("oauth_token")
            resource_owner_secret = fetch_response.get("oauth_token_secret")

            authorize_base = "https://us.etrade.com/e/t/etws/authorize"
            params = {"key": self.consumer_key, "token": resource_owner_key}
            authorization_url = f"{authorize_base}?{urlencode(params)}"
            logMessage("Please go to the following URL to authorize access:")
            logMessage(authorization_url)
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
            self.save_tokens()
            logMessage("✅ Access token obtained successfully.")
            return True
        except Exception as e:
            logMessage(f"[ERROR] Failed to generate token: {e}")
            return False

    def save_tokens(self):
        """Save the current token data to disk."""
        with open(self.token_file, "w") as f:
            json.dump({
                "oauth_token": self.oauth_token,
                "oauth_token_secret": self.oauth_token_secret
            }, f)


    # ------------------- HELPERS -------------------
    def get_headers(self):
        return {"Content-Type": "application/json"}

    def load_encrypted_etrade_keysecret(self, sandbox=True):
        with open("encryption/secret.key", "rb") as key_file:
            key = key_file.read()
        sandbox_suffix = "sandbox" if sandbox else "prod"
        with open(f"encryption/etrade_consumer_key_{sandbox_suffix}.enc", "rb") as enc_file:
            encrypted_key = enc_file.read()
        with open(f"encryption/etrade_consumer_secret_{sandbox_suffix}.enc", "rb") as enc_file:
            encrypted_secret = enc_file.read()
        f = Fernet(key)
        return f.decrypt(encrypted_key).decode(), f.decrypt(encrypted_secret).decode()

    # ------------------- ACCOUNT / PORTFOLIO -------------------
    def get_accounts(self):
        url = f"{self.base_url}/v1/accounts/list.json"
        r = self.get(url)
        try:
            accts = r.json().get("AccountListResponse", {}).get("Accounts", {}).get("Account", [])
            return [Account(**acct) for acct in accts]
        except Exception as e:
            logMessage(f"[ERROR] Failed to parse account ID: {e}")
            return []

    def get_positions(self):
        accounts = self.get_accounts()
        all_positions = []
        for acct in accounts:
            url = f"{self.base_url}/v1/accounts/{acct.accountIdKey}/portfolio.json"
            r = self.get(url)
            data = r.json()
            account_portfolios = data.get("PortfolioResponse", {}).get("AccountPortfolio", [])
            for acct_raw in account_portfolios:
                portfolio = PortfolioAccount.from_dict(acct_raw)
                all_positions.extend(portfolio.Position or [])
        return all_positions
    
        #How much capital is currently outstanding (ie don't buy more than comfortable)
    def get_open_exposure(self):
        positions = self.get_positions()
        if positions is not None:
            return sum(p.totalCost for p in positions)
        return None

    # ------------------- OPTION CHAINS -------------------
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

        try:
            chain_data = r.json().get("OptionChainResponse", {})
            near_price = chain_data.get("nearPrice")
            expiry_dict = chain_data.get("SelectedED", {})
            expiry_date = datetime(
                year=expiry_dict.get("year", 1970),
                month=expiry_dict.get("month", 1),
                day=expiry_dict.get("day", 1),
                tzinfo=timezone.utc
            )
            results = []
            for optionPair in chain_data.get("OptionPair", []):
                call = optionPair.get("Call", {})
                call_greeks = call.get("OptionGreeks", {})
                option_greeks = OptionGreeks(**call_greeks)

                product = Product(
                    symbol=call.get("symbol"),
                    securityType=call.get("optionType"),  # or "CALL"/"PUT"
                    callPut="CALL" if call.get("optionType") == "CALL" else "PUT",
                    strikePrice=call.get("strikePrice"),
                    productId=ProductId(symbol=call.get("symbol"), typeCode=call.get("optionType"))
                )

                quick = Quick(
                    lastTrade=call.get("lastPrice"),
                    lastTradeTime=None,
                    change=None,
                    changePct=None,
                    volume=call.get("volume"),
                    quoteStatus=None
                )

                # Only pass keys that exist in OptionContract
                option_fields = {k: call[k] for k in [
                    "symbol", "optionType", "strikePrice", "displaySymbol", "osiKey",
                    "bid", "ask", "bidSize", "askSize", "inTheMoney", "volume",
                    "openInterest", "netChange", "lastPrice", "quoteDetail",
                    "optionCategory", "timeStamp", "adjustedFlag"
                ] if k in call}

                option = OptionContract(
                    **option_fields,
                    OptionGreeks=option_greeks,
                    quick=quick,
                    product=product
                )

                results.append(option)
            return results,True
        except Exception as e:
            logMessage(f"[ERROR] Failed to parse option chain for {symbol}: {e}")
            return [],False

    # ------------------- QUOTES -------------------
    def get_quote(self, symbol):
        url = f"{self.base_url}/v1/market/quote/{symbol}.json"
        r = self.get(url)
        try:
            qdata = r.json().get("QuoteResponse", {}).get("QuoteData", [])[0]
            product = Product(symbol=symbol)
            quick = Quick(
                lastTrade=qdata.get("lastTrade"),
                lastTradeTime=None,
                change=qdata.get("change"),
                changePct=qdata.get("changePct"),
                volume=qdata.get("volume"),
                quoteStatus=qdata.get("quoteStatus")
            )
            return Position(Product=product, Quick=quick)
        except Exception as e:
            logMessage(f"[ERROR] Failed to parse quote for {symbol}: {e}")
            return None


# ------------------- FORCE TOKEN GENERATION (OUTSIDE CLASS) -------------------
def force_generate_new_token(open_browser=False, sandbox=False):
    consumer = EtradeConsumer(open_browser=open_browser, sandbox=sandbox)
    return
