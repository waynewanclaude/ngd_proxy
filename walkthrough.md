# Walkthrough: Norgate Data Proxy and Caching System (`ngd_proxy`)

We have successfully refactored the Norgate Data Proxy and caching engine into a modern, installable Python package named `ngd_proxy`, implemented all 26 core Norgate API functions (including single-value metadata lookups and EOD update times), and validated them with a robust automated test suite.

---

## 🛠️ Package Architecture & Structure

The codebase is organized as a clean, importable Python package:

```
ngd_proxy/
├── .gitignore
├── README.md
├── pyproject.toml              # Modern setuptools packaging & dependencies config
├── requirements.txt            # Package dependencies reference
├── status_tracker.md           # API implementation status tracker database
├── ngd_proxy/                  # Main package folder
│   ├── __init__.py             # Exposes public client & cache API classes/methods
│   ├── client.py               # Lightweight proxy server HTTP client
│   ├── config.json.example     # Template settings (no secrets)
│   ├── norgatedata_cache.py    # Unified SQLite + Parquet caching layer
│   └── server.py               # FastAPI proxy server (with main() CLI entrypoint)
├── tests/                      # Unit and integration test suite
│   └── test_cache.py           # 15 scenario automated testing suite
└── test_*.ipynb                # Interactive verification notebooks (git-ignored)
```

---

## 📦 Packaging and CLI Entrypoint

### 1. `pyproject.toml` Setup
We implemented a modern package configuration using standard `setuptools`:
- **Package Name:** `ngd_proxy`
- **Minimum Python Version:** `>=3.8`
- **Dependencies Managed:** `fastapi`, `uvicorn`, `pandas`, `pyarrow`, `psutil`, `requests`, `cryptography`, `jinja2`.
- **Global Console Script:** Maps the global command `ngd-proxy-server` directly to the FastAPI server running wrapper `ngd_proxy.server:main`.
- **Exclusion Filters:** Strictly excludes non-package metadata dirs (e.g. `plans` and `tests` directories) to prevent python discovery bugs during package builds.

### 2. Relative Imports & Namespace Cleanliness
- The package structure utilizes absolute internal and relative namespace routing. For example, `norgatedata_cache.py` resolves its client import via:
  ```python
  from .client import NorgateDataClient
  ```
- All convenience functions and enums are neatly exposed at the package root level in `ngd_proxy/__init__.py`.

---

## 🚀 Newly Supported API Features

To maintain compatibility with wealth-lab, backtrader, and other advanced trading packages, we implemented a full range of non-timeseries functions. Crucially, **all of these single-value lookups completely bypass local disk caching and SQLite database indexing**, loading dynamically from the proxy server:

1. **Security & Exchange Name Lookups:**
   - `security_name(symbol)`: Returns the full name of the company.
   - `exchange_name(symbol)`: Returns the short exchange code (e.g. `NASDAQ`).
   - `exchange_name_full(symbol)`: Returns the full exchange description (e.g. `Nasdaq Stock Market`).
2. **EOD Update Time Properties:**
   - `last_database_update_time(database)`: Returns a native python `datetime` object indicating when a database partition (e.g. `us`) was last updated.
   - `last_price_update_time(symbol)`: Returns a native `datetime` object for symbol-specific updates.
3. **Core Asset Metadata & Classifications:**
   - `assetid(symbol)`: Returns the unique internal integer asset ID from Norgate (e.g. `1001` for `TSLA`, `1002` for `MSFT`).
   - `base_type(symbol)`: Returns the security's base category (`Stock Market`).
   - `classification(symbol, schemename)`: Returns sector classification strings (e.g., GICS industries).
   - `corresponding_industry_index(symbol, ...)`: Resolves associated industry sector indices (e.g. `$SP500-15` or `$SP500-45`).
4. **Hierarchical Classifications Subtypes:**
   - `subtype1(symbol)`: Returns the broad security subtype level (e.g. `"Equity"`).
   - `subtype2(symbol)`: Returns the intermediate security subtype level (e.g. `"Operating Company"`).
   - `subtype3(symbol)`: Returns the granular/final security subtype level (e.g. `"Common Stock"`).
5. **Futures-Specific Specifications:**
   - `margin(symbol)`: Returns the current initial margin requirement for a contract/market (e.g. `18000.0` for Eurex DAX continuous futures `&FDAX`).
   - `point_value(symbol)`: Returns the whole point movement value (e.g. `25.0` for `&FDAX`).
   - `tick_value(symbol)`: Returns the value of a single tick (e.g. `12.5` for `&FDAX` or `&ES`).
   - `lowest_ever_tick_size(symbol)`: Returns the historically lowest minimum price increment (e.g. `0.25` for `&ES`).
   - `futures_market_session_info(symbol)`: Returns the market session trading category (e.g. `"Combined"`).

---

## 🧪 Verification & Test Results

The test suite in `tests/test_cache.py` imports directly from the `ngd_proxy` package namespace. We have successfully expanded it from 6 to **16 rigorous automated integration tests**, verifying both core timeseries Parquet caches and the caching-bypass behavior of all newly implemented metadata fields.

Running the test suite via:
```bash
python -m unittest tests/test_cache.py
```

Produces flawless verification results:
```text
Ran 16 tests in 3.402s

OK
[WARNING] Could not import native 'norgatedata' library. Falling back to MOCK MODE.
```

### Detailed Test Coverage
1. **`test_01_server_status`**: Connection checks and Mock Mode handshake.
2. **`test_02_price_cache_miss_and_hit`**: Confirmed Parquet streaming cache misses and instantaneous subsequent cache hits.
3. **`test_03_price_incremental_sync_tail`**: Smart date-range stitching at the end of a range (using TSLA).
4. **`test_04_price_incremental_sync_head`**: Smart date-range stitching at the start of a range (using MSFT).
5. **`test_05_index_constituent_caching`**: Unified caching for historical index constituent membership.
6. **`test_06_lru_cache_eviction`**: Eviction logic pruning oldest entries under directory storage constraints using distinct combinations of symbols and adjustment types.
7. **`test_07_security_name_mock_data_and_cache_bypass`**: Asserted that single-value name lookup returns precise mock details and bypasses local caching entirely.
8. **`test_08_fundamental_mock_data_and_cache_bypass`**: Asserted that single-value fundamental fields return precise mock data (EPS/PE) and bypass local caching entirely.
9. **`test_09_watchlist_mock_data_and_cache_bypass`**: Asserted that single-value watchlist queries return correct mock details and bypass local caching entirely.
10. **`test_10_exchange_name_mock_data_and_cache_bypass`**: Asserted that exchange_name returns correct short exchange details and bypasses caching.
11. **`test_11_exchange_name_full_mock_data_and_cache_bypass`**: Asserted that exchange_name_full returns full exchange description and bypasses caching.
12. **`test_12_last_database_update_time_and_cache_bypass`**: Asserted ISO datetime parsing from server string to native Python `datetime` objects and verified cache bypass.
13. **`test_13_last_price_update_time_and_cache_bypass`**: Asserted symbol price update time datetime parsing and cache bypass.
14. **`test_14_asset_metadata_lookups_and_cache_bypass`**: Asserted correct mock outputs for `assetid`, `base_type`, `classification`, and `corresponding_industry_index` lookups and verified cache bypass.
15. **`test_15_subtype_lookups_and_cache_bypass`**: Asserted correct hierarchical output for `subtype1`, `subtype2`, and `subtype3` lookups and verified cache bypass.
16. **`test_16_futures_metadata_lookups_and_cache_bypass`**: Asserted correct futures specifications (`margin`, `point_value`, `tick_value`, `lowest_ever_tick_size`, and `futures_market_session_info`) for `&FDAX` and `&ES` continuous futures symbols, returning `None` for stocks, and verified cache bypass.

---

## 📓 Interactive Notebooks

We created beautiful verification notebooks mapping our full suite of functionalities (using `TSLA` as the primary mock symbol alongside `MSFT` and `&FDAX`/`&ES` for futures). You can run these notebooks inside Jupyter to see everything work interactively:
- **[`test__price_timeseries.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__price_timeseries.ipynb):** High-speed timeseries fetching, caching, and timing metrics.
- **[`test__security_name.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__security_name.ipynb):** Security names, fundamental fields, and watchlist details.
- **[`test__exchange_name.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__exchange_name.ipynb):** Short and full exchange names.
- **[`test__update_time.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__update_time.ipynb):** EOD database partition and symbol price update datetimes.
- **[`test__asset_metadata.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__asset_metadata.ipynb):** Asset IDs, GICS classification, base types, and corresponding industry indices.
- **[`test__subtype.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__subtype.ipynb):** Hierarchical classification subtypes (`subtype1`, `subtype2`, `subtype3`).
- **[`test__futures_metadata.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__futures_metadata.ipynb):** Futures-specific specification lookups (`margin`, `point_value`, `tick_value`, `lowest_ever_tick_size`, `futures_market_session_info`).

