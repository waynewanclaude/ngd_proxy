import os
import json
import logging
from io import BytesIO
from typing import Optional, List, Dict, Union, Any
from datetime import datetime


import pandas as pd
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("NorgateDataClient")

class NorgateDataClient:
    """
    A lightweight, high-performance client that communicates with the ngd_proxy Windows host.
    """
    def __init__(
        self, 
        base_url: Optional[str] = None, 
        api_key: Optional[str] = None,
        config_path: str = "config.json"
    ):
        # Resolve config path
        resolved_config_path = os.path.abspath(config_path)
        
        # Load from config.json if not explicitly provided
        self.base_url = base_url
        self.api_key = api_key
        
        if os.path.exists(resolved_config_path):
            try:
                with open(resolved_config_path, "r") as f:
                    config = json.load(f)
                    if not self.base_url:
                        self.base_url = config.get("server_base_url", "http://127.0.0.1:8000")
                    if not self.api_key:
                        self.api_key = config.get("api_key", "norgate-secure-default-key-replace-me")
            except Exception as e:
                logger.warning(f"Failed to parse config file: {e}. Using explicit inputs or defaults.")
        
        # Fallbacks if still not defined
        self.base_url = self.base_url or "http://127.0.0.1:8000"
        self.api_key = self.api_key or "norgate-secure-default-key-replace-me"
        
        # Clean trailing slash from base url
        self.base_url = self.base_url.rstrip("/")
        
        logger.info(f"Initialized client. Server URL: {self.base_url}")

    def _get_headers(self) -> Dict[str, str]:
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _request_dataframe(self, endpoint: str, params: Dict[str, Any]) -> pd.DataFrame:
        """
        Helper method to fetch and decode a DataFrame using high-performance Parquet format.
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        # Request binary Parquet format
        headers["Accept"] = "application/x-parquet"
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code != 200:
                # Handle error nicely
                error_msg = f"HTTP Error {response.status_code}: "
                try:
                    error_msg += response.json().get("detail", response.text)
                except Exception:
                    error_msg += response.text
                raise RuntimeError(error_msg)
            
            # Check content type to see if it is Parquet
            content_type = response.headers.get("Content-Type", "")
            if "application/x-parquet" in content_type or response.content.startswith(b"PAR1"):
                # Read Parquet from binary response body
                df = pd.read_parquet(BytesIO(response.content))
                # Ensure the index is a DatetimeIndex
                if not isinstance(df.index, pd.DatetimeIndex) and df.index.name == "Date":
                    df.index = pd.to_datetime(df.index)
                return df
            else:
                # Fallback to JSON
                data = response.json()
                if not data:
                    return pd.DataFrame()
                df = pd.DataFrame(data)
                if "Date" in df.columns:
                    df["Date"] = pd.to_datetime(df["Date"])
                    df.set_index("Date", inplace=True)
                return df
                
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to connect to proxy server: {e}")

    def status(self) -> Dict[str, Any]:
        """
        Check connectivity and health of the proxy server and NDU.
        """
        url = f"{self.base_url}/status"
        try:
            response = requests.get(url, headers=self._get_headers(), timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"status": "error", "detail": str(e), "ndu_connected": False}

    def price_timeseries(
        self,
        symbol: str,
        stock_price_adjustment_setting: Union[str, int] = "TOTALRETURN",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        key_by_assetid: bool = False
    ) -> pd.DataFrame:
        """
        Fetches price timeseries for a symbol.
        """
        params = {
            "symbol": symbol,
            "adjustment": stock_price_adjustment_setting,
            "key_by_assetid": key_by_assetid
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
            
        return self._request_dataframe("/price_timeseries", params)

    def index_constituent_timeseries(
        self,
        symbol: str,
        indexname: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Checks historical index constituent membership timeseries.
        Returns a single-column DataFrame (is_constituent: 1 or 0) indexed by Date.
        """
        params = {
            "symbol": symbol,
            "indexname": indexname
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
            
        return self._request_dataframe("/index_constituent_timeseries", params)

    def dividend_yield_timeseries(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Fetches historical dividend yield timeseries.
        """
        params = {"symbol": symbol}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
            
        return self._request_dataframe("/dividend_yield_timeseries", params)

    def unadjusted_close_timeseries(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        key_by_assetid: bool = False
    ) -> pd.DataFrame:
        """
        Fetches historical EOD unadjusted close timeseries from the proxy host.
        """
        params = {
            "symbol": symbol,
            "key_by_assetid": key_by_assetid
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
            
        return self._request_dataframe("/unadjusted_close_timeseries", params)

    def major_exchange_listed_timeseries(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Fetches historical EOD major exchange listed timeseries from the proxy host.
        """
        params = {"symbol": symbol}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
            
        return self._request_dataframe("/major_exchange_listed_timeseries", params)

    def capital_event_timeseries(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Fetches historical EOD capital event timeseries from the proxy host.
        """
        params = {"symbol": symbol}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
            
        return self._request_dataframe("/capital_event_timeseries", params)

    def padding_status_timeseries(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Fetches historical EOD padding status timeseries from the proxy host.
        """
        params = {"symbol": symbol}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
            
        return self._request_dataframe("/padding_status_timeseries", params)

    def watchlists(self) -> List[str]:
        """
        Retrieve available watchlists.
        """
        url = f"{self.base_url}/watchlists"
        response = requests.get(url, headers=self._get_headers(), timeout=10)
        response.raise_for_status()
        return response.json()

    def watchlist_symbols(self, watchlistname: str) -> List[str]:
        """
        Retrieve symbols belonging to a watchlist.
        """
        url = f"{self.base_url}/watchlist/symbols"
        params = {"watchlistname": watchlistname}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=15)
        response.raise_for_status()
        return response.json()

    def watchlist_details(self, watchlistname: str) -> List[Dict[str, Any]]:
        """
        Retrieve full security details of a watchlist.
        """
        url = f"{self.base_url}/watchlist/details"
        params = {"watchlistname": watchlistname}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=15)
        response.raise_for_status()
        return response.json()

    def watchlist(self, watchlistname: str) -> List[Dict[str, Any]]:
        """
        Retrieve security details of a watchlist (assetid, symbol, name).
        """
        url = f"{self.base_url}/watchlist"
        params = {"watchlistname": watchlistname}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=15)
        response.raise_for_status()
        return response.json()


    def security_name(self, symbol: str) -> Optional[str]:
        """
        Retrieve full security name.
        """
        url = f"{self.base_url}/security_name"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("security_name")

    def fundamental(self, symbol: str, fieldname: str, datetimeformat: str = 'iso') -> tuple:
        """
        Retrieve current fundamental single-value reported data.
        """
        url = f"{self.base_url}/fundamental"
        params = {
            "symbol": symbol,
            "fieldname": fieldname,
            "datetimeformat": datetimeformat
        }
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return (data.get("value"), data.get("date"))

    def exchange_name(self, symbol: str) -> Optional[str]:
        """
        Retrieve short exchange name.
        """
        url = f"{self.base_url}/exchange_name"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("exchange_name")

    def exchange_name_full(self, symbol: str) -> Optional[str]:
        """
        Retrieve full exchange name.
        """
        url = f"{self.base_url}/exchange_name_full"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("exchange_name_full")

    def last_database_update_time(self, database: str) -> Optional[datetime]:
        """
        Retrieve the last database update time as a datetime object.
        """
        url = f"{self.base_url}/last_database_update_time"
        params = {"database": database}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        val = response.json().get("last_database_update_time")
        return datetime.fromisoformat(val) if val else None

    def last_price_update_time(self, symbol: str) -> Optional[datetime]:
        """
        Retrieve the last price update time for a symbol as a datetime object.
        """
        url = f"{self.base_url}/last_price_update_time"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        val = response.json().get("last_price_update_time")
        return datetime.fromisoformat(val) if val else None

    def assetid(self, symbol: str) -> Optional[int]:
        """
        Retrieve the unique Norgate asset ID for a symbol.
        """
        url = f"{self.base_url}/assetid"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("assetid")

    def base_type(self, symbol: str) -> Optional[str]:
        """
        Retrieve the base type of the security.
        """
        url = f"{self.base_url}/base_type"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("base_type")

    def classification(self, symbol: str, schemename: str, classificationresulttype: str = "Name", level: Optional[int] = None) -> Optional[str]:
        """
        Retrieve classification category for a schemename.
        """
        url = f"{self.base_url}/classification"
        params = {
            "symbol": symbol,
            "schemename": schemename,
            "classificationresulttype": classificationresulttype
        }
        if level is not None:
            params["level"] = level
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("classification")


    def corresponding_industry_index(self, symbol: str, indexfamilycode: str, level: int, indexreturntype: str) -> Optional[str]:
        """
        Retrieve symbol of the corresponding industry index.
        """
        url = f"{self.base_url}/corresponding_industry_index"
        params = {
            "symbol": symbol,
            "indexfamilycode": indexfamilycode,
            "level": level,
            "indexreturntype": indexreturntype
        }
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("corresponding_industry_index")

    def subtype1(self, symbol: str) -> Optional[str]:
        """
        Retrieve primary classification subtype of the security.
        """
        url = f"{self.base_url}/subtype1"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("subtype1")

    def subtype2(self, symbol: str) -> Optional[str]:
        """
        Retrieve secondary classification subtype of the security.
        """
        url = f"{self.base_url}/subtype2"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("subtype2")

    def subtype3(self, symbol: str) -> Optional[str]:
        """
        Retrieve tertiary classification subtype of the security.
        """
        url = f"{self.base_url}/subtype3"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("subtype3")

    def margin(self, symbol: str) -> Optional[float]:
        """
        Retrieve current margin requirement of the futures contract/market.
        """
        url = f"{self.base_url}/margin"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("margin")

    def point_value(self, symbol: str) -> Optional[float]:
        """
        Retrieve point value of the futures contract/market.
        """
        url = f"{self.base_url}/point_value"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("point_value")

    def tick_value(self, symbol: str) -> Optional[float]:
        """
        Retrieve tick value of the futures contract/market.
        """
        url = f"{self.base_url}/tick_value"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("tick_value")

    def lowest_ever_tick_size(self, symbol: str) -> Optional[float]:
        """
        Retrieve historically lowest ever tick size of the futures contract/market.
        """
        url = f"{self.base_url}/lowest_ever_tick_size"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("lowest_ever_tick_size")

    def futures_market_session_info(self, symbol: str) -> Optional[str]:
        """
        Retrieve market trading session info of the futures contract/market.
        """
        url = f"{self.base_url}/futures_market_session_info"
        params = {"symbol": symbol}
        response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("futures_market_session_info")






