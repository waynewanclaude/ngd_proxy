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
        symbol = "TSLA"
        
        # Initial seeding: Jan 1 to Jan 10
        self.cache.price_timeseries(symbol, "TOTALRETURN", "2025-01-01", "2025-01-10")
        
        # Expand query: Jan 1 to Jan 15 (Missing Jan 11-15)
        df = self.cache.price_timeseries(symbol, "TOTALRETURN", "2025-01-01", "2025-01-15")
        
        self.assertFalse(df.empty)
        
        # Check that metadata in SQLite was updated to end on Jan 15
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT start_date, end_date, access_count FROM cache_metadata WHERE symbol='TSLA'")
        row = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "2025-01-01")
        self.assertEqual(row[1], "2025-01-15")
        self.assertEqual(row[2], 2) # Incremental hit incremented access count

    def test_04_price_incremental_sync_head(self):
        """Asserts smart range-merging when querying older missing dates (gap at the beginning)."""
        symbol = "MSFT"
        
        # Initial seeding: Jan 5 to Jan 15
        self.cache.price_timeseries(symbol, "TOTALRETURN", "2025-01-05", "2025-01-15")
        
        # Expand backwards: Jan 1 to Jan 15 (Missing Jan 1-4)
        df = self.cache.price_timeseries(symbol, "TOTALRETURN", "2025-01-01", "2025-01-15")
        
        self.assertFalse(df.empty)
        
        # Verify metadata start_date updated to Jan 01
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT start_date, end_date FROM cache_metadata WHERE symbol='MSFT'")
        row = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "2025-01-01")
        self.assertEqual(row[1], "2025-01-15")

    def test_05_index_constituent_caching(self):
        """Tests unified caching specifically for historical index constituent membership."""
        symbol = "TSLA"
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
        
        # Cache 4 different combinations. Each file will be ~2-5KB, easily blowing the 8KB limit
        # This will trigger eviction on subsequent writes!
        keys = [
            ("TSLA", "TOTALRETURN"),
            ("TSLA", "CAPITAL"),
            ("MSFT", "TOTALRETURN"),
            ("MSFT", "CAPITAL")
        ]
        for s, adj in keys:
            tiny_cache.price_timeseries(s, adj, "2025-01-01", "2025-01-20")
            time.sleep(0.1) # ensure distinct access timestamps
            
        # Query current records in SQLite
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, parameter FROM cache_metadata")
        cached_keys = cursor.fetchall()
        conn.close()
        
        # Assert that some of the oldest cached keys have been evicted
        self.assertNotIn(("TSLA", "TOTALRETURN"), cached_keys)
        self.assertIn(("MSFT", "CAPITAL"), cached_keys)
        
        # Confirm that the physical file for oldest was actually removed from disk
        tsla_tr_path = os.path.join(TEST_CACHE_DIR, "price_TSLA_TOTALRETURN.parquet")
        self.assertFalse(os.path.exists(tsla_tr_path))


    def test_07_security_name_mock_data_and_cache_bypass(self):
        """Verifies security_name returns correct mock data and bypasses the cache entirely."""
        # 1. Clear cache database to start clean
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache_metadata")
        conn.commit()
        conn.close()

        # 2. Get security name
        name = self.cache.security_name("MSFT")
        self.assertEqual(name, "Microsoft Corporation Common Stock")

        # 3. Check cache is bypassed (no files, no DB entries)
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache_metadata")
        db_count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(db_count, 0)
        
        # Verify no parquet files were created
        files = [f for f in os.listdir(TEST_CACHE_DIR) if f.endswith(".parquet")]
        self.assertEqual(len(files), 0)

        # 4. Check that invalid symbol raises error
        with self.assertRaises(Exception):
            self.cache.security_name("ON")

    def test_08_fundamental_mock_data_and_cache_bypass(self):
        """Verifies fundamental returns correct mock data and bypasses the cache entirely."""
        # 1. Clear cache database to start clean
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache_metadata")
        conn.commit()
        conn.close()

        # 2. Get fundamental data
        val, dt = self.cache.fundamental("MSFT", "pe")
        self.assertEqual(val, 24.5)
        self.assertEqual(dt, "2025-12-31")

        val2, dt2 = self.cache.fundamental("TSLA", "eps")
        self.assertEqual(val2, 3.2)
        self.assertEqual(dt2, "2025-12-31")

        # 3. Check cache is bypassed (no files, no DB entries)
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache_metadata")
        db_count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(db_count, 0)
        
        # Verify no parquet files were created
        files = [f for f in os.listdir(TEST_CACHE_DIR) if f.endswith(".parquet")]
        self.assertEqual(len(files), 0)

        # 4. Check that invalid symbol raises error
        with self.assertRaises(Exception):
            self.cache.fundamental("ON", "pe")

    def test_09_watchlist_mock_data_and_cache_bypass(self):
        """Verifies watchlist returns correct mock details and bypasses the cache entirely."""
        # 1. Get watchlist details
        details = self.cache.watchlist("Nasdaq 100")
        self.assertTrue(len(details) > 0)
        self.assertEqual(details[0]["symbol"], "TSLA")
        self.assertEqual(details[1]["symbol"], "MSFT")

        # 2. Check no DB entry was made
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache_metadata WHERE datatype='watchlist'")
        db_count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(db_count, 0)

    def test_10_exchange_name_mock_data_and_cache_bypass(self):
        """Verifies exchange_name returns correct mock data and bypasses the cache entirely."""
        # 1. Clear cache database to start clean
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache_metadata")
        conn.commit()
        conn.close()

        # 2. Get exchange name
        name = self.cache.exchange_name("TSLA")
        self.assertEqual(name, "NASDAQ")

        # 3. Check cache is bypassed (no files, no DB entries)
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache_metadata")
        db_count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(db_count, 0)
        
        # Verify no parquet files were created
        files = [f for f in os.listdir(TEST_CACHE_DIR) if f.endswith(".parquet")]
        self.assertEqual(len(files), 0)

        # 4. Check that invalid symbol raises error
        with self.assertRaises(Exception):
            self.cache.exchange_name("ON")

    def test_11_exchange_name_full_mock_data_and_cache_bypass(self):
        """Verifies exchange_name_full returns correct mock data and bypasses the cache entirely."""
        # 1. Clear cache database to start clean
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache_metadata")
        conn.commit()
        conn.close()

        # 2. Get full exchange name
        name_full = self.cache.exchange_name_full("MSFT")
        self.assertEqual(name_full, "Nasdaq Stock Market")

        # 3. Check cache is bypassed (no files, no DB entries)
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache_metadata")
        db_count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(db_count, 0)
        
        # Verify no parquet files were created
        files = [f for f in os.listdir(TEST_CACHE_DIR) if f.endswith(".parquet")]
        self.assertEqual(len(files), 0)

        # 4. Check that invalid symbol raises error
        with self.assertRaises(Exception):
            self.cache.exchange_name_full("ON")

    def test_12_last_database_update_time_and_cache_bypass(self):
        """Verifies last_database_update_time parses datetime and bypasses the cache entirely."""
        from datetime import datetime
        # 1. Get database update time
        dt = self.cache.last_database_update_time("us")
        self.assertEqual(dt, datetime(2026, 5, 26, 0, 0, 0))

        # 2. Check cache is bypassed (no files, no DB entries)
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache_metadata")
        db_count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(db_count, 0)

        # 3. Check invalid database raises error
        with self.assertRaises(Exception):
            self.cache.last_database_update_time("invalid_db")

    def test_13_last_price_update_time_and_cache_bypass(self):
        """Verifies last_price_update_time parses datetime and bypasses the cache entirely."""
        from datetime import datetime
        # 1. Get price update time
        dt = self.cache.last_price_update_time("TSLA")
        self.assertEqual(dt, datetime(2026, 5, 26, 1, 0, 0))

        # 2. Check cache is bypassed (no files, no DB entries)
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache_metadata")
        db_count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(db_count, 0)

        # 3. Check invalid symbol raises error
        with self.assertRaises(Exception):
            self.cache.last_price_update_time("ON")

    def test_14_asset_metadata_lookups_and_cache_bypass(self):
        """Verifies assetid, base_type, classification, and industry index lookups with cache bypass."""
        # 1. Get asset ID
        aid = self.cache.assetid("TSLA")
        self.assertEqual(aid, 1001)

        # 2. Get base type
        btype = self.cache.base_type("MSFT")
        self.assertEqual(btype, "Stock Market")

        # 3. Get classification (testing defaults and result types)
        classif = self.cache.classification("TSLA", "GICS")
        self.assertEqual(classif, "Automobile")

        classif_id = self.cache.classification("TSLA", "GICS", classificationresulttype="ClassificationId")
        self.assertEqual(classif_id, "15")

        classif_msft_id = self.cache.classification("MSFT", "GICS", "ClassificationId")
        self.assertEqual(classif_msft_id, "45")


        # 4. Get corresponding industry index
        idx = self.cache.corresponding_industry_index("MSFT", "$SPX", 3, "TR")
        self.assertEqual(idx, "$SP500-45")

        # 5. Check cache is bypassed (no files, no DB entries)
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache_metadata")
        db_count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(db_count, 0)

        # 6. Check invalid symbol raises error
        with self.assertRaises(Exception):
            self.cache.assetid("ON")

    def test_15_subtype_lookups_and_cache_bypass(self):
        """Verifies subtype1, subtype2, and subtype3 lookups return correct mock data and bypass cache."""
        # 1. Clear cache database to start clean
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache_metadata")
        conn.commit()
        conn.close()

        # 2. Get subtypes
        sub1_tsla = self.cache.subtype1("TSLA")
        sub2_tsla = self.cache.subtype2("TSLA")
        sub3_tsla = self.cache.subtype3("TSLA")

        sub1_msft = self.cache.subtype1("MSFT")
        sub2_msft = self.cache.subtype2("MSFT")
        sub3_msft = self.cache.subtype3("MSFT")

        # 3. Assert return values
        self.assertEqual(sub1_tsla, "Equity")
        self.assertEqual(sub2_tsla, "Operating Company")
        self.assertEqual(sub3_tsla, "Common Stock")

        self.assertEqual(sub1_msft, "Equity")
        self.assertEqual(sub2_msft, "Operating Company")
        self.assertEqual(sub3_msft, "Common Stock")

        # 4. Check cache is bypassed (no files, no DB entries)
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache_metadata")
        db_count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(db_count, 0)

        # Verify no parquet files were created
        files = [f for f in os.listdir(TEST_CACHE_DIR) if f.endswith(".parquet")]
        self.assertEqual(len(files), 0)

        # 5. Check invalid symbol raises error
        with self.assertRaises(Exception):
            self.cache.subtype1("ON")

    def test_16_futures_metadata_lookups_and_cache_bypass(self):
        """Verifies futures metadata functions return accurate mock data and bypass cache completely."""
        # 1. Clear cache database to start clean
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache_metadata")
        conn.commit()
        conn.close()

        # 2. Get futures specifications for &FDAX
        margin_fdax = self.cache.margin("&FDAX")
        pv_fdax = self.cache.point_value("&FDAX")
        tv_fdax = self.cache.tick_value("&FDAX")
        lt_fdax = self.cache.lowest_ever_tick_size("&FDAX")
        sess_fdax = self.cache.futures_market_session_info("&FDAX")

        # 3. Assert return values for &FDAX
        self.assertEqual(margin_fdax, 18000.0)
        self.assertEqual(pv_fdax, 25.0)
        self.assertEqual(tv_fdax, 12.5)
        self.assertEqual(lt_fdax, 0.5)
        self.assertEqual(sess_fdax, "Combined")

        # 4. Get futures specifications for &ES
        margin_es = self.cache.margin("&ES")
        pv_es = self.cache.point_value("&ES")
        tv_es = self.cache.tick_value("&ES")
        lt_es = self.cache.lowest_ever_tick_size("&ES")
        sess_es = self.cache.futures_market_session_info("&ES")

        # 5. Assert return values for &ES
        self.assertEqual(margin_es, 12000.0)
        self.assertEqual(pv_es, 50.0)
        self.assertEqual(tv_es, 12.5)
        self.assertEqual(lt_es, 0.25)
        self.assertEqual(sess_es, "Combined")

        # 6. Verify non-futures behavior for stocks (return None)
        self.assertIsNone(self.cache.margin("TSLA"))
        self.assertIsNone(self.cache.point_value("MSFT"))
        self.assertIsNone(self.cache.tick_value("TSLA"))
        self.assertIsNone(self.cache.lowest_ever_tick_size("MSFT"))
        self.assertIsNone(self.cache.futures_market_session_info("TSLA"))

        # 7. Check cache is bypassed (no files, no DB entries)
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache_metadata")
        db_count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(db_count, 0)

        # Verify no parquet files were created
        files = [f for f in os.listdir(TEST_CACHE_DIR) if f.endswith(".parquet")]
        self.assertEqual(len(files), 0)

        # 8. Check invalid symbol raises error in mock mode
        with self.assertRaises(Exception):
            self.cache.margin("ON")

    def test_17_unadjusted_close_timeseries_caching_and_formats(self):
        """Verifies that unadjusted close timeseries caching, delta-stitching, and format conversion layers work perfectly."""
        # 1. Clear cache database to start clean
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache_metadata")
        conn.commit()
        conn.close()

        # Remove any lingering parquet files
        for f in os.listdir(TEST_CACHE_DIR):
            if f.endswith(".parquet"):
                os.remove(os.path.join(TEST_CACHE_DIR, f))

        # 2. Assert cache miss (Server Fetch & Cache Write)
        df_tsla = self.cache.unadjusted_close_timeseries(
            symbol="TSLA",
            timeseriesformat="pandas-dataframe",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        self.assertIsInstance(df_tsla, pd.DataFrame)
        self.assertFalse(df_tsla.empty)
        self.assertEqual(list(df_tsla.columns), ["Close"])
        self.assertEqual(df_tsla.index.name, "Date")

        # Verify DB metadata entry was made
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT start_date, end_date, file_path, access_count FROM cache_metadata WHERE datatype='unadjusted_close' AND symbol='TSLA' AND parameter='UNADJUSTED'")
        record = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(record)
        self.assertEqual(record[0], "2025-01-01")
        self.assertEqual(record[1], "2025-01-10")

        # Verify Parquet file was created
        parquet_file = record[2]
        self.assertTrue(os.path.exists(parquet_file))
        self.assertTrue("unadjusted_close_TSLA_UNADJUSTED" in parquet_file)

        # 3. Assert cache hit (Instant slice without server)
        df_tsla_hit = self.cache.unadjusted_close_timeseries(
            symbol="TSLA",
            timeseriesformat="pandas-dataframe",
            start_date="2025-01-02",
            end_date="2025-01-08"
        )
        self.assertEqual(len(df_tsla_hit), 5) # 5 business days between Jan 2 and Jan 8

        # 4. Verify different timeseriesformat settings
        # numpy-recarray
        rec = self.cache.unadjusted_close_timeseries(
            symbol="TSLA",
            timeseriesformat="numpy-recarray",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        import numpy as np
        self.assertIsInstance(rec, np.recarray)
        self.assertTrue(len(rec) > 0)
        self.assertTrue("Close" in rec.dtype.names)
        self.assertTrue("Date" in rec.dtype.names)

        # numpy-ndarray
        arr = self.cache.unadjusted_close_timeseries(
            symbol="TSLA",
            timeseriesformat="numpy-ndarray",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        self.assertIsInstance(arr, np.ndarray)
        self.assertEqual(arr.ndim, 2) # Date and Close

        # 5. Verify continuous futures contract caching
        df_fdax = self.cache.unadjusted_close_timeseries(
            symbol="&FDAX",
            timeseriesformat="pandas-dataframe",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        self.assertIsInstance(df_fdax, pd.DataFrame)
        self.assertFalse(df_fdax.empty)

        # 6. Verify key_by_assetid caching behavior
        df_asset = self.cache.unadjusted_close_timeseries(
            symbol="MSFT",
            timeseriesformat="pandas-dataframe",
            start_date="2025-01-01",
            end_date="2025-01-10",
            key_by_assetid=True
        )
        self.assertEqual(df_asset.index.name, "AssetID")
        self.assertEqual(df_asset.index[0], 1002)

        # Verify DB metadata entry for asset ID param
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT parameter FROM cache_metadata WHERE datatype='unadjusted_close' AND symbol='MSFT'")
        record_asset = cursor.fetchone()
        conn.close()
        self.assertEqual(record_asset[0], "UNADJUSTED_ASSETID")

        # 7. Assert that invalid symbol raises 404 client error in mock mode
        with self.assertRaises(Exception):
            self.cache.unadjusted_close_timeseries("AAPL")

    def test_18_major_exchange_listed_timeseries_caching_and_formats(self):
        """Verifies that major exchange listed status timeseries caching and formats work perfectly."""
        # 1. Clear cache database to start clean
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache_metadata")
        conn.commit()
        conn.close()

        # Remove any lingering parquet files
        for f in os.listdir(TEST_CACHE_DIR):
            if f.endswith(".parquet"):
                os.remove(os.path.join(TEST_CACHE_DIR, f))

        # 2. Assert cache miss (Server Fetch & Cache Write)
        df_tsla = self.cache.major_exchange_listed_timeseries(
            symbol="TSLA",
            timeseriesformat="pandas-dataframe",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        self.assertIsInstance(df_tsla, pd.DataFrame)
        self.assertFalse(df_tsla.empty)
        self.assertEqual(list(df_tsla.columns), ["MajorExchangeListed"])
        self.assertEqual(df_tsla.index.name, "Date")

        # Verify DB metadata entry was made
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT start_date, end_date, file_path FROM cache_metadata WHERE datatype='major_exchange_listed' AND symbol='TSLA' AND parameter='MAJOR_EXCHANGE_LISTED'")
        record = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(record)
        self.assertEqual(record[0], "2025-01-01")
        self.assertEqual(record[1], "2025-01-10")

        # Verify Parquet file was created
        parquet_file = record[2]
        self.assertTrue(os.path.exists(parquet_file))

        # 3. Assert cache hit (Instant slice without server)
        df_tsla_hit = self.cache.major_exchange_listed_timeseries(
            symbol="TSLA",
            timeseriesformat="pandas-dataframe",
            start_date="2025-01-02",
            end_date="2025-01-08"
        )
        self.assertEqual(len(df_tsla_hit), 5) 

        # 4. Verify different timeseriesformat settings
        # numpy-recarray
        rec = self.cache.major_exchange_listed_timeseries(
            symbol="TSLA",
            timeseriesformat="numpy-recarray",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        import numpy as np
        self.assertIsInstance(rec, np.recarray)
        self.assertTrue(len(rec) > 0)
        self.assertTrue("MajorExchangeListed" in rec.dtype.names)

        # numpy-ndarray
        arr = self.cache.major_exchange_listed_timeseries(
            symbol="TSLA",
            timeseriesformat="numpy-ndarray",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        self.assertIsInstance(arr, np.ndarray)
        self.assertEqual(arr.ndim, 2)

        # 5. Assert that invalid symbol raises 404 client error in mock mode
        with self.assertRaises(Exception):
            self.cache.major_exchange_listed_timeseries("AAPL")

    def test_19_capital_event_timeseries_caching_and_formats(self):
        """Verifies that capital event timeseries caching and formats work perfectly."""
        # 1. Clear cache database to start clean
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache_metadata")
        conn.commit()
        conn.close()

        # Remove any lingering parquet files
        for f in os.listdir(TEST_CACHE_DIR):
            if f.endswith(".parquet"):
                os.remove(os.path.join(TEST_CACHE_DIR, f))

        # 2. Assert cache miss (Server Fetch & Cache Write)
        df_tsla = self.cache.capital_event_timeseries(
            symbol="TSLA",
            timeseriesformat="pandas-dataframe",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        self.assertIsInstance(df_tsla, pd.DataFrame)
        self.assertFalse(df_tsla.empty)
        self.assertEqual(list(df_tsla.columns), ["Capital Event"])
        self.assertEqual(df_tsla.index.name, "Date")

        # Verify DB metadata entry was made
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT start_date, end_date, file_path FROM cache_metadata WHERE datatype='capital_event' AND symbol='TSLA' AND parameter='CAPITAL_EVENT'")
        record = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(record)
        self.assertEqual(record[0], "2025-01-01")
        self.assertEqual(record[1], "2025-01-10")

        # Verify Parquet file was created
        parquet_file = record[2]
        self.assertTrue(os.path.exists(parquet_file))

        # 3. Assert cache hit (Instant slice without server)
        df_tsla_hit = self.cache.capital_event_timeseries(
            symbol="TSLA",
            timeseriesformat="pandas-dataframe",
            start_date="2025-01-02",
            end_date="2025-01-08"
        )
        self.assertEqual(len(df_tsla_hit), 5) 

        # 4. Verify different timeseriesformat settings
        # numpy-recarray
        rec = self.cache.capital_event_timeseries(
            symbol="TSLA",
            timeseriesformat="numpy-recarray",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        import numpy as np
        self.assertIsInstance(rec, np.recarray)
        self.assertTrue(len(rec) > 0)
        self.assertTrue("Capital Event" in rec.dtype.names)

        # numpy-ndarray
        arr = self.cache.capital_event_timeseries(
            symbol="TSLA",
            timeseriesformat="numpy-ndarray",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        self.assertIsInstance(arr, np.ndarray)
        self.assertEqual(arr.ndim, 2)

        # 5. Assert that invalid symbol raises 404 client error in mock mode
        with self.assertRaises(Exception):
            self.cache.capital_event_timeseries("AAPL")

    def test_20_padding_status_timeseries_caching_and_formats(self):
        """Verifies that padding status timeseries caching and formats work perfectly."""
        # 1. Clear cache database to start clean
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cache_metadata")
        conn.commit()
        conn.close()

        # Remove any lingering parquet files
        for f in os.listdir(TEST_CACHE_DIR):
            if f.endswith(".parquet"):
                os.remove(os.path.join(TEST_CACHE_DIR, f))

        # 2. Assert cache miss (Server Fetch & Cache Write)
        df_tsla = self.cache.padding_status_timeseries(
            symbol="TSLA",
            timeseriesformat="pandas-dataframe",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        self.assertIsInstance(df_tsla, pd.DataFrame)
        self.assertFalse(df_tsla.empty)
        self.assertEqual(list(df_tsla.columns), ["PaddingStatus"])
        self.assertEqual(df_tsla.index.name, "Date")

        # Verify DB metadata entry was made
        conn = sqlite3.connect(os.path.join(TEST_CACHE_DIR, "cache_index.db"))
        cursor = conn.cursor()
        cursor.execute("SELECT start_date, end_date, file_path FROM cache_metadata WHERE datatype='padding_status' AND symbol='TSLA' AND parameter='PADDING_STATUS'")
        record = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(record)
        self.assertEqual(record[0], "2025-01-01")
        self.assertEqual(record[1], "2025-01-10")

        # Verify Parquet file was created
        parquet_file = record[2]
        self.assertTrue(os.path.exists(parquet_file))

        # 3. Assert cache hit (Instant slice without server)
        df_tsla_hit = self.cache.padding_status_timeseries(
            symbol="TSLA",
            timeseriesformat="pandas-dataframe",
            start_date="2025-01-02",
            end_date="2025-01-08"
        )
        self.assertEqual(len(df_tsla_hit), 5) 

        # 4. Verify different timeseriesformat settings
        # numpy-recarray
        rec = self.cache.padding_status_timeseries(
            symbol="TSLA",
            timeseriesformat="numpy-recarray",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        import numpy as np
        self.assertIsInstance(rec, np.recarray)
        self.assertTrue(len(rec) > 0)
        self.assertTrue("PaddingStatus" in rec.dtype.names)

        # numpy-ndarray
        arr = self.cache.padding_status_timeseries(
            symbol="TSLA",
            timeseriesformat="numpy-ndarray",
            start_date="2025-01-01",
            end_date="2025-01-10"
        )
        self.assertIsInstance(arr, np.ndarray)
        self.assertEqual(arr.ndim, 2)

        # 5. Assert that invalid symbol raises 404 client error in mock mode
        with self.assertRaises(Exception):
            self.cache.padding_status_timeseries("AAPL")

    def test_21_server_discovery_and_probing(self):
        """Verifies that the client concurrently probes multiple URLs and locks onto the first active one."""
        # 1. Probing with a dead port first, then our active test port
        dead_url = "http://127.0.0.1:9999"
        active_url = f"http://127.0.0.1:{TEST_PORT}"
        
        # Initialize client with both URLs
        client = NorgateDataClient(
            base_url=[dead_url, active_url],
            api_key="test-secret-key"
        )
        
        # Verify that the active server URL was successfully discovered and locked onto
        self.assertEqual(client.base_url, active_url)
        
        # Verify that we can query the server status successfully via this client
        status = client.status()
        self.assertEqual(status.get("status"), "ok")
        
        # 2. Verify fallback behavior when no servers are responding
        client_dead = NorgateDataClient(
            base_url=["http://127.0.0.1:9998", "http://127.0.0.1:9997"],
            api_key="test-secret-key"
        )
        # Should gracefully fall back to the first URL in the list
        self.assertEqual(client_dead.base_url, "http://127.0.0.1:9998")

if __name__ == "__main__":
    unittest.main()





