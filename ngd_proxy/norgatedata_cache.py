import os
import json
import sqlite3
import time
import logging
from typing import Optional, List, Dict, Union, Any
from datetime import datetime

import pandas as pd
from .client import NorgateDataClient

logger = logging.getLogger("NorgateDataCache")

def sanitize_filename(name: str) -> str:
    """Replaces invalid characters for cross-platform filenames (Windows/Linux/macOS)."""
    invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|', ' ', '\t', '\n']
    for char in invalid_chars:
        name = name.replace(char, '_')
    return name

class NorgateDataCache:
    """
    A unified, isolated client-side caching layer for Norgate Data.
    Acts as a transparent drop-in wrapper around NorgateDataClient.
    """
    def __init__(self, config_path: str = "config.json"):
        self.config_path = os.path.abspath(config_path)
        self._load_config()
        
        # Initialize HTTP client
        self.client = NorgateDataClient(
            base_url=self.server_base_url,
            api_key=self.api_key,
            config_path=config_path
        )
        
        if self.cache_enabled:
            self._init_cache_environment()
            logger.info(f"Local Caching is ENABLED. Cache directory: {self.cache_dir} | Limit: {self.max_cache_size_mb} MB | Eviction: {self.eviction_policy}")
        else:
            logger.info("Local Caching is DISABLED. Sourcing all data directly from proxy server.")

    def _load_config(self):
        """Loads configuration from config.json with robust fallbacks."""
        # Default configuration values
        self.server_base_url = "http://127.0.0.1:8000"
        self.api_key = "norgate-secure-default-key-replace-me"
        self.cache_enabled = True
        self.cache_dir = "~/.cache/norgatedata"
        self.max_cache_size_mb = 10000
        self.eviction_policy = "LRU"
        self.refresh_expired_days = 1

        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    config = json.load(f)
                    self.server_base_url = config.get("server_base_url", self.server_base_url)
                    self.api_key = config.get("api_key", self.api_key)
                    self.cache_enabled = config.get("cache_enabled", self.cache_enabled)
                    self.cache_dir = config.get("cache_dir", self.cache_dir)
                    self.max_cache_size_mb = config.get("max_cache_size_mb", self.max_cache_size_mb)
                    self.eviction_policy = config.get("eviction_policy", self.eviction_policy).upper()
                    self.refresh_expired_days = config.get("refresh_expired_days", self.refresh_expired_days)
            except Exception as e:
                logger.warning(f"Error parsing {self.config_path}: {e}. Running with standard defaults.")

    def _init_cache_environment(self):
        """Resolves cache paths and initializes the SQLite tracking index."""
        try:
            # Expand ~ to user home directory
            self.cache_dir = os.path.abspath(os.path.expanduser(self.cache_dir))
            os.makedirs(self.cache_dir, exist_ok=True)
            
            # Setup SQLite Database path
            self.db_path = os.path.join(self.cache_dir, "cache_index.db")
            
            # Create tracking table if it doesn't exist
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cache_metadata (
                    datatype TEXT,
                    symbol TEXT,
                    parameter TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    file_path TEXT,
                    file_size INTEGER,
                    last_accessed_at REAL,
                    access_count INTEGER,
                    PRIMARY KEY (datatype, symbol, parameter)
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to initialize cache environment: {e}. Disabling caching for safety.")
            self.cache_enabled = False

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    # --- Core Cache Interceptor Engine ---
    def _get_timeseries(
        self,
        datatype: str,
        symbol: str,
        parameter: str,
        start_date: Optional[str],
        end_date: Optional[str],
        fetch_func  # Callable to call NorgateDataClient if miss or delta occurs
    ) -> pd.DataFrame:
        """
        Generic, high-performance timeseries cacher. Resolves cache hits,
        cache misses, and partial interval gaps automatically.
        """
        # If cache is disabled, run directly against client
        if not self.cache_enabled:
            return fetch_func(start_date=start_date, end_date=end_date)

        # Standardise date strings or fill empty ones
        today_str = datetime.today().strftime("%Y-%m-%d")
        q_start = start_date or "1900-01-01"
        q_end = end_date or today_str
        
        # Read from SQLite Cache Index
        cache_record = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT start_date, end_date, file_path, file_size, access_count FROM cache_metadata WHERE datatype=? AND symbol=? AND parameter=?",
                (datatype, symbol, parameter)
            )
            cache_record = cursor.fetchone()
            conn.close()
        except Exception as e:
            logger.warning(f"Cache database read failed: {e}. Falling back to server fetch.")
            return fetch_func(start_date=start_date, end_date=end_date)

        # --- Case 1: Cache Miss ---
        if not cache_record:
            logger.info(f"Cache MISS for [{datatype}] {symbol} ({parameter}). Fetching full history from server.")
            df = fetch_func(start_date=start_date, end_date=end_date)
            if df.empty:
                return df
                
            self._save_to_cache(datatype, symbol, parameter, q_start, q_end, df)
            return df

        cached_start, cached_end, file_path, file_size, access_count = cache_record

        # Check if local file exists
        if not os.path.exists(file_path):
            logger.warning(f"Cached file not found on disk: {file_path}. Removing cache entry and re-fetching.")
            self._delete_metadata(datatype, symbol, parameter)
            df = fetch_func(start_date=start_date, end_date=end_date)
            if df.empty:
                return df
            self._save_to_cache(datatype, symbol, parameter, q_start, q_end, df)
            return df

        # Convert strings to pandas timestamps for math comparison
        ts_q_start = pd.to_datetime(q_start)
        ts_q_end = pd.to_datetime(q_end)
        ts_c_start = pd.to_datetime(cached_start)
        ts_c_end = pd.to_datetime(cached_end)

        # --- Case 2: Direct Cache Hit (Fully Covered) ---
        if ts_q_start >= ts_c_start and ts_q_end <= ts_c_end:
            logger.debug(f"Cache HIT for [{datatype}] {symbol} ({parameter}). Slicing in memory.")
            try:
                df = pd.read_parquet(file_path)
                self._update_access_stats(datatype, symbol, parameter, access_count)
                # Slice and return
                return df.loc[ts_q_start:ts_q_end]
            except Exception as e:
                logger.warning(f"Failed to read cached Parquet file {file_path}: {e}. Re-fetching.")
                self._delete_metadata(datatype, symbol, parameter)
                return fetch_func(start_date=start_date, end_date=end_date)

        # --- Case 3: Incremental Sync (Partial gaps) ---
        logger.info(f"Cache PARTIAL HIT for [{datatype}] {symbol} ({parameter}). Local range: {cached_start} to {cached_end}.")
        try:
            # Load current local cache
            df_cached = pd.read_parquet(file_path)
            
            # Sub-case A: Missing recent bars (Gap at the End)
            if ts_q_end > ts_c_end and ts_q_start >= ts_c_start:
                # Sync only the delta!
                delta_start = (ts_c_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                logger.info(f"Incremental sync: Requesting delta from server for {symbol} ({delta_start} to {q_end})")
                df_delta = fetch_func(start_date=delta_start, end_date=q_end)
                
                if df_delta.empty:
                    # Server had no new data (holiday/weekend/EOD not updated yet)
                    # Extend metadata end_date to query end to avoid repeated redundant calls
                    self._update_metadata_range(datatype, symbol, parameter, cached_start, q_end, df_cached)
                    return df_cached.loc[ts_q_start:ts_q_end]
                
                # Merge new rows
                df_merged = pd.concat([df_cached, df_delta])
                df_merged = df_merged[~df_merged.index.duplicated(keep="last")].sort_index()
                
                # Save and update SQLite
                self._save_to_cache(datatype, symbol, parameter, cached_start, q_end, df_merged)
                return df_merged.loc[ts_q_start:ts_q_end]

            # Sub-case B: Missing older bars (Gap at the Beginning)
            elif ts_q_start < ts_c_start and ts_q_end <= ts_c_end:
                delta_end = (ts_c_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                logger.info(f"Incremental sync: Requesting historical head from server for {symbol} ({q_start} to {delta_end})")
                df_delta = fetch_func(start_date=q_start, end_date=delta_end)
                
                if df_delta.empty:
                    self._update_metadata_range(datatype, symbol, parameter, q_start, cached_end, df_cached)
                    return df_cached.loc[ts_q_start:ts_q_end]
                
                # Merge new rows
                df_merged = pd.concat([df_delta, df_cached])
                df_merged = df_merged[~df_merged.index.duplicated(keep="last")].sort_index()
                
                # Save and update SQLite
                self._save_to_cache(datatype, symbol, parameter, q_start, cached_end, df_merged)
                return df_merged.loc[ts_q_start:ts_q_end]

            # Sub-case C: Gap on both sides (Or complex overlap)
            else:
                logger.info(f"Double overlap. Fetching full requested range {q_start} to {q_end} from server.")
                df = fetch_func(start_date=start_date, end_date=end_date)
                if df.empty:
                    return df
                self._save_to_cache(datatype, symbol, parameter, q_start, q_end, df)
                return df
                
        except Exception as e:
            logger.warning(f"Error during incremental merge for {symbol}: {e}. Overwriting cache with fresh download.")
            df = fetch_func(start_date=start_date, end_date=end_date)
            if not df.empty:
                self._save_to_cache(datatype, symbol, parameter, q_start, q_end, df)
            return df

    # --- Cache Management and Eviction Write Operations ---
    def _save_to_cache(self, datatype: str, symbol: str, parameter: str, start: str, end: str, df: pd.DataFrame):
        """Saves a dataframe to a local Parquet file and updates SQLite metadata."""
        try:
            safe_symbol = sanitize_filename(symbol)
            safe_parameter = sanitize_filename(parameter)
            file_name = f"{datatype}_{safe_symbol}_{safe_parameter}.parquet"
            file_path = os.path.join(self.cache_dir, file_name)
            
            # Write to disk
            df.to_parquet(file_path, engine="pyarrow", compression="snappy", index=True)
            file_size = os.path.getsize(file_path)
            
            # Fetch existing access count if any, and increment it
            existing_count = 1
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT access_count FROM cache_metadata WHERE datatype=? AND symbol=? AND parameter=?",
                    (datatype, symbol, parameter)
                )
                row = cursor.fetchone()
                if row:
                    existing_count = row[0] + 1
                conn.close()
            except Exception:
                pass

            # Write to SQLite
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO cache_metadata 
                (datatype, symbol, parameter, start_date, end_date, file_path, file_size, last_accessed_at, access_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (datatype, symbol, parameter, start, end, file_path, file_size, time.time(), existing_count))
            conn.commit()
            conn.close()
            
            # Trigger eviction check
            self._check_eviction()
        except Exception as e:
            logger.error(f"Failed to save timeseries cache file for {symbol}: {e}")

    def _update_metadata_range(self, datatype: str, symbol: str, parameter: str, start: str, end: str, df: pd.DataFrame):
        """Updates date range and stats for an existing cache record."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE cache_metadata SET start_date=?, end_date=?, last_accessed_at=?, access_count=access_count+1 WHERE datatype=? AND symbol=? AND parameter=?",
                (start, end, time.time(), datatype, symbol, parameter)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to update metadata range in SQLite: {e}")

    def _update_access_stats(self, datatype: str, symbol: str, parameter: str, current_count: int):
        """Increments access count and updates access time for cache hits."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE cache_metadata SET last_accessed_at=?, access_count=? WHERE datatype=? AND symbol=? AND parameter=?",
                (time.time(), current_count + 1, datatype, symbol, parameter)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to update SQLite statistics: {e}")

    def _delete_metadata(self, datatype: str, symbol: str, parameter: str):
        """Deletes metadata record from SQLite."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM cache_metadata WHERE datatype=? AND symbol=? AND parameter=?",
                (datatype, symbol, parameter)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to delete SQLite metadata: {e}")

    def _check_eviction(self):
        """
        Monitors total cache directory size. Evicts files based on LRU or LFU
        when total size exceeds `max_cache_size_mb`.
        """
        max_bytes = self.max_cache_size_mb * 1024 * 1024
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(file_size) FROM cache_metadata")
            total_bytes = cursor.fetchone()[0] or 0
            
            if total_bytes <= max_bytes:
                conn.close()
                return
                
            logger.warning(f"Cache directory size ({total_bytes / 1024 / 1024:.2f} MB) exceeds maximum ({self.max_cache_size_mb} MB). Running eviction!")
            
            # Select correct sorting based on eviction policy
            if self.eviction_policy == "LFU":
                # Least Frequently Used first, breaking ties with oldest access
                cursor.execute("SELECT datatype, symbol, parameter, file_path, file_size FROM cache_metadata ORDER BY access_count ASC, last_accessed_at ASC")
            else:
                # Least Recently Used (Default)
                cursor.execute("SELECT datatype, symbol, parameter, file_path, file_size FROM cache_metadata ORDER BY last_accessed_at ASC")
                
            candidates = cursor.fetchall()
            
            # Prune until size is below 90% of the threshold (avoid thrashing on every single write)
            target_limit = max_bytes * 0.90
            bytes_deleted = 0
            
            for datatype, symbol, parameter, file_path, file_size in candidates:
                if total_bytes - bytes_deleted <= target_limit:
                    break
                    
                # Delete disk file
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        logger.info(f"Evicted cached file: {file_path}")
                    except Exception as ex:
                        logger.error(f"Failed to delete file {file_path}: {ex}")
                
                # Delete SQLite record
                cursor.execute(
                    "DELETE FROM cache_metadata WHERE datatype=? AND symbol=? AND parameter=?",
                    (datatype, symbol, parameter)
                )
                bytes_deleted += file_size
                logger.info(f"Evicted SQLite metadata for [{datatype}] {symbol} ({parameter})")
                
            conn.commit()
            conn.close()
            logger.info(f"Eviction complete. Pruned {bytes_deleted / 1024 / 1024:.2f} MB.")
            
        except Exception as e:
            logger.error(f"Error checking cache eviction limits: {e}")

    # --- Public API Wrapper Methods ---

    def price_timeseries(
        self,
        symbol: str,
        stock_price_adjustment_setting: Union[str, int] = "TOTALRETURN",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        key_by_assetid: bool = False
    ) -> pd.DataFrame:
        """
        Exposes cached price timeseries.
        """
        # Form parameter string
        param = str(stock_price_adjustment_setting).upper()
        if key_by_assetid:
            param += "_ASSETID"
            
        fetch_func = lambda start_date, end_date: self.client.price_timeseries(
            symbol=symbol,
            stock_price_adjustment_setting=stock_price_adjustment_setting,
            start_date=start_date,
            end_date=end_date,
            key_by_assetid=key_by_assetid
        )
        
        return self._get_timeseries("price", symbol, param, start_date, end_date, fetch_func)

    def index_constituent_timeseries(
        self,
        symbol: str,
        indexname: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Exposes cached index constituent timeseries.
        """
        fetch_func = lambda start_date, end_date: self.client.index_constituent_timeseries(
            symbol=symbol,
            indexname=indexname,
            start_date=start_date,
            end_date=end_date
        )
        
        return self._get_timeseries("index_constituent", symbol, indexname, start_date, end_date, fetch_func)

    def dividend_yield_timeseries(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Exposes cached dividend yield timeseries.
        """
        fetch_func = lambda start_date, end_date: self.client.dividend_yield_timeseries(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date
        )
        
        return self._get_timeseries("dividend_yield", symbol, "DIVIDEND", start_date, end_date, fetch_func)

    def watchlists(self) -> List[str]:
        """
        Transparent wrapper around proxy watchlists.
        """
        return self.client.watchlists()

    def watchlist_symbols(self, watchlistname: str) -> List[str]:
        """
        Transparent wrapper around proxy watchlist symbols.
        """
        return self.client.watchlist_symbols(watchlistname)

    def watchlist_details(self, watchlistname: str) -> List[Dict[str, Any]]:
        """
        Transparent wrapper around proxy watchlist details.
        """
        return self.client.watchlist_details(watchlistname)

    def watchlist(self, watchlistname: str) -> List[Dict[str, Any]]:
        """
        Exposes single-value watchlist lookup.
        Bypasses local Parquet file-caching and database indexing entirely.
        """
        return self.client.watchlist(watchlistname)

    def security_name(self, symbol: str) -> Optional[str]:
        """
        Exposes current single-value security name lookup.
        Bypasses local Parquet file-caching and database indexing entirely.
        """
        return self.client.security_name(symbol)

    def fundamental(self, symbol: str, fieldname: str, datetimeformat: str = 'iso') -> tuple:
        """
        Exposes current single-value fundamental lookup.
        Bypasses local Parquet file-caching and database indexing entirely.
        """
        return self.client.fundamental(symbol, fieldname, datetimeformat)

    def exchange_name(self, symbol: str) -> Optional[str]:
        """
        Exposes short exchange name lookup.
        Bypasses local Parquet file-caching and database indexing entirely.
        """
        return self.client.exchange_name(symbol)

    def exchange_name_full(self, symbol: str) -> Optional[str]:
        """
        Exposes full exchange name lookup.
        Bypasses local Parquet file-caching and database indexing entirely.
        """
        return self.client.exchange_name_full(symbol)

    def last_database_update_time(self, database: str) -> Optional[datetime]:
        """
        Exposes database update time lookup.
        Bypasses local Parquet file-caching and database indexing entirely.
        """
        return self.client.last_database_update_time(database)

    def last_price_update_time(self, symbol: str) -> Optional[datetime]:
        """
        Exposes symbol price update time lookup.
        Bypasses local Parquet file-caching and database indexing entirely.
        """
        return self.client.last_price_update_time(symbol)

    def assetid(self, symbol: str) -> Optional[int]:
        """
        Exposes asset ID lookup.
        Bypasses local Parquet file-caching and database indexing entirely.
        """
        return self.client.assetid(symbol)

    def base_type(self, symbol: str) -> Optional[str]:
        """
        Exposes base type lookup.
        Bypasses local Parquet file-caching and database indexing entirely.
        """
        return self.client.base_type(symbol)

    def classification(self, symbol: str, schemename: str) -> Optional[str]:
        """
        Exposes classification lookup.
        Bypasses local Parquet file-caching and database indexing entirely.
        """
        return self.client.classification(symbol, schemename)

    def corresponding_industry_index(self, symbol: str, indexfamilycode: str, level: int, indexreturntype: str) -> Optional[str]:
        """
        Exposes corresponding industry index lookup.
        Bypasses local Parquet file-caching and database indexing entirely.
        """
        return self.client.corresponding_industry_index(symbol, indexfamilycode, level, indexreturntype)



