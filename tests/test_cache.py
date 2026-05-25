import os
import json
import shutil
import sqlite3
import time
import threading
import logging
import unittest
from datetime import datetime

import pandas as pd
import uvicorn

# Suppress logs for cleaner test output
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("NorgateDataClient").setLevel(logging.WARNING)
logging.getLogger("NorgateDataCache").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.ERROR)

# Import our proxy components
from ngd_proxy.server import app
from ngd_proxy import server
from ngd_proxy import NorgateDataClient, NorgateDataCache

logger = logging.getLogger("Test")
logging.basicConfig(level=logging.INFO)

TEST_PORT = 8099
TEST_BASE_URL = f"http://127.0.0.1:{TEST_PORT}"
TEST_CACHE_DIR = os.path.abspath("./test_norgate_cache")

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=TEST_PORT, log_level="error")

class TestNorgateDataProxyAndCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Force mock mode on server
        server.MOCK_MODE = True
        server.API_KEY = "test-secret-key"
        
        # Start server in background thread
        cls.server_thread = threading.Thread(target=run_server, daemon=True)
        cls.server_thread.start()
        
        # Wait a moment for server to bind
        time.sleep(1.5)

    def setUp(self):
        # Clean up any residual test cache folder
        if os.path.exists(TEST_CACHE_DIR):
            shutil.rmtree(TEST_CACHE_DIR)
            
        # Create a clean config.json for tests
        self.config_data = {
            "server_base_url": TEST_BASE_URL,
            "api_key": "test-secret-key",
            "cache_enabled": True,
            "cache_dir": TEST_CACHE_DIR,
            "max_cache_size_mb": 10,
            "eviction_policy": "LRU",
            "refresh_expired_days": 1
        }
        with open("config_test.json", "w") as f:
            json.dump(self.config_data, f)
            
        # Initialize Cache Manager pointing to test config
        self.cache = NorgateDataCache(config_path="config_test.json")

    def tearDown(self):
        # Clean up files
        if os.path.exists(TEST_CACHE_DIR):
            shutil.rmtree(TEST_CACHE_DIR)
        if os.path.exists("config_test.json"):
            os.remove("config_test.json")

    # --- Test Cases ---

    def test_01_server_status(self):
        """Verifies connection status and that the server is running in Mock Mode."""
        status = self.cache.client.status()
        self.assertEqual(status.get("status"), "ok")
        self.assertEqual(status.get("mode"), "mock")
        self.assertTrue(status.get("ndu_connected"))
        self.assertIn("system", status)

    def test_02_price_cache_miss_and_hit(self):
        """Asserts that first query is a cache miss and second query is an instant hit."""
        symbol = "MSFT"
        
        # --- 1. Cache Miss (Fetch and store) ---
        t0 = time.time()
        df1 = self.cache.price_timeseries(
            symbol=symbol,
            stock_price_adjustment_setting="TOTALRETURN",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        t_miss = time.time() - t0
        
        self.assertFalse(df1.empty)
        self.assertEqual(df1.index.name, "Date")
        self.assertIn("Close", df1.columns)
        
        # Verify SQLite index entries
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT start_date, end_date, file_path, access_count FROM cache_metadata WHERE symbol='MSFT'")
        row = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "2025-01-01")
        self.assertEqual(row[1], "2025-01-10")
        self.assertTrue(os.path.exists(row[2]))
        self.assertEqual(row[3], 1) # First access

        # --- 2. Cache Hit (Instant slicing) ---
        t0 = time.time()
        df2 = self.cache.price_timeseries(
            symbol=symbol,
            stock_price_adjustment_setting="TOTALRETURN",
            start_date="2025-01-03",
            end_date="2025-01-08"
        )
        t_hit = time.time() - t0
        
        self.assertFalse(df2.empty)
        # Sliced subset should have fewer rows than the main cache
        self.assertLess(len(df2), len(df1))
        
        # Confirm cache hit is significantly faster (sub-millisecond load vs HTTP roundtrip)
        logger.info(f"Performance: Cache Miss = {t_miss:.4f}s | Cache Hit = {t_hit:.4f}s")
        self.assertLess(t_hit, t_miss)

    def test_03_price_incremental_sync_tail(self):
        """Asserts smart range-merging when querying recent missing dates (gap at the end)."""
        symbol = "NVDA"
        
        # Initial seeding: Jan 1 to Jan 10
        self.cache.price_timeseries(symbol, "TOTALRETURN", "2025-01-01", "2025-01-10")
        
        # Expand query: Jan 1 to Jan 15 (Missing Jan 11-15)
        df = self.cache.price_timeseries(symbol, "TOTALRETURN", "2025-01-01", "2025-01-15")
        
        self.assertFalse(df.empty)
        
        # Check that metadata in SQLite was updated to end on Jan 15
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT start_date, end_date, access_count FROM cache_metadata WHERE symbol='NVDA'")
        row = cursor.fetchone()
        conn.close()
        
        self.assertEqual(row[0], "2025-01-01")
        self.assertEqual(row[1], "2025-01-15")
        self.assertEqual(row[2], 2) # Incremental hit incremented access count

    def test_04_price_incremental_sync_head(self):
        """Asserts smart range-merging when querying older missing dates (gap at the beginning)."""
        symbol = "AMZN"
        
        # Initial seeding: Jan 5 to Jan 15
        self.cache.price_timeseries(symbol, "TOTALRETURN", "2025-01-05", "2025-01-15")
        
        # Expand backwards: Jan 1 to Jan 15 (Missing Jan 1-4)
        df = self.cache.price_timeseries(symbol, "TOTALRETURN", "2025-01-01", "2025-01-15")
        
        self.assertFalse(df.empty)
        
        # Verify metadata start_date updated to Jan 01
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT start_date, end_date FROM cache_metadata WHERE symbol='AMZN'")
        row = cursor.fetchone()
        conn.close()
        
        self.assertEqual(row[0], "2025-01-01")
        self.assertEqual(row[1], "2025-01-15")

    def test_05_index_constituent_caching(self):
        """Tests unified caching specifically for historical index constituent membership."""
        symbol = "AAPL"
        index = "S&P 500"
        
        # 1. Miss
        df1 = self.cache.index_constituent_timeseries(symbol, index, "2025-01-01", "2025-01-10")
        self.assertIn("is_constituent", df1.columns)
        
        # 2. Verify in SQLite
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT datatype, start_date, end_date FROM cache_metadata WHERE datatype='index_constituent'")
        row = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "index_constituent")
        self.assertEqual(row[1], "2025-01-01")
        self.assertEqual(row[2], "2025-01-10")

    def test_06_lru_cache_eviction(self):
        """Verifies LRU eviction works correctly under storage limits."""
        # Update config dynamically to force tiny cache size limit (8 KB)
        self.config_data["max_cache_size_mb"] = 0.008  # extremely small limit (~8192 bytes)
        with open("config_test.json", "w") as f:
            json.dump(self.config_data, f)
            
        # Re-initialize cache with new tiny limit
        tiny_cache = NorgateDataCache(config_path="config_test.json")
        
        # Cache 4 different symbols. Each file will be ~2-5KB, easily blowing the 1KB limit
        # This will trigger eviction on subsequent writes!
        symbols = ["T1", "T2", "T3", "T4"]
        for s in symbols:
            tiny_cache.price_timeseries(s, "TOTALRETURN", "2025-01-01", "2025-01-20")
            time.sleep(0.1) # ensure distinct access timestamps
            
        # Query current records in SQLite
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT symbol FROM cache_metadata")
        cached_symbols = [r[0] for r in cursor.fetchall()]
        conn.close()
        
        # Assert that some of the oldest cached tickers (e.g. T1 or T2) have been evicted
        # and only the most recent ones (e.g. T4) remain on disk
        self.assertNotIn("T1", cached_symbols)
        self.assertIn("T4", cached_symbols)
        
        # Confirm that the physical file for T1 was actually removed from disk
        t1_path = os.path.join(TEST_CACHE_DIR, "price_T1_TOTALRETURN.parquet")
        self.assertFalse(os.path.exists(t1_path))

if __name__ == "__main__":
    unittest.main()
