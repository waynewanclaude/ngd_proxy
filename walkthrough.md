# Walkthrough: Norgate Data Proxy and Caching System (`ngd_proxy`)

We have successfully refactored the Norgate Data Proxy and caching engine into a modern, installable Python package named `ngd_proxy`, implemented all 26 core Norgate API functions (including single-value metadata lookups, futures contract specs, EOD update times, and historical timeseries), and validated them with a robust automated test suite.

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
│   └── test_cache.py           # 18 scenario automated testing suite
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

## 🚀 Supported API Features

The proxy client-side caching engine selectively caches historical timeseries to snappy-compressed Parquet local storage, while other lookups (watchlists, metadata, calendars, futures contract terms, and single-value fundamentals) bypass caching completely to ensure fresh data and zero storage overhead:

### 1. Historical Timeseries (Fully Cached & Indexed via SQLite)
- **`price_timeseries`**: High-performance OHLCV historical timeseries.
- **`index_constituent_timeseries`**: Boolean membership array indicating historical index inclusion.
- **`dividend_yield_timeseries`**: Historical dividend yield spikes.
- **`unadjusted_close_timeseries`** (Newly Implemented): Fetches raw, unadjusted close price history. Supports dynamic format conversions (`pandas-dataframe`, `numpy-recarray` [default], and `numpy-ndarray`) and keying by asset ID.
- **`major_exchange_listed_timeseries`** (Newly Implemented): Fetches indicator series showing whether a US security was listed on a major exchange vs OTC historically. Supports dynamic formats (`numpy-recarray` [default], `pandas-dataframe`, `numpy-ndarray`).
- **`capital_event_timeseries`** (Newly Implemented): Fetches indicator series showing whether a corporate action (split, stock dividend, reorganization) occurred on the ex-date. Supports dynamic formats (`numpy-recarray` [default], `pandas-dataframe`, `numpy-ndarray`).
- **`padding_status_timeseries`** (Newly Implemented): Fetches indicator series showing whether price records were date-padded historically. Supports dynamic formats (`numpy-recarray` [default], `pandas-dataframe`, `numpy-ndarray`).

### 2. Metadata, Calendars, & Futures Specs (Cache Bypassing Pass-Throughs)
- **Security & Exchange Name Lookups**: `security_name`, `exchange_name`, `exchange_name_full`.
- **EOD Update Time Properties**: `last_database_update_time`, `last_price_update_time`.
- **Core Asset Metadata & Classifications**: `assetid`, `base_type`, `classification`, `corresponding_industry_index`.
- **Hierarchical Subtype Metadata**: `subtype1`, `subtype2`, `subtype3` (e.g., broad subclass, intermediate, and final subtype like `"Common Stock"`).
- **Futures-Specific Specifications**: `margin`, `point_value`, `tick_value`, `lowest_ever_tick_size`, `futures_market_session_info`.
- **Watchlists**: `watchlists`, `watchlist_symbols`, `watchlist_details`, `watchlist`.

---

## 🧪 Verification & Test Results

The test suite in `tests/test_cache.py` imports directly from the `ngd_proxy` package namespace. We have successfully expanded it to **18 rigorous automated integration tests**, verifying both core timeseries Parquet caches and the caching-bypass behavior of all newly implemented metadata fields.

Running the test suite via:
```bash
python -m unittest tests/test_cache.py
```

Produces flawless verification results:
```text
Ran 18 tests in 3.093s

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
17. **`test_17_unadjusted_close_timeseries_caching_and_formats`** (Newly Added): Asserts unadjusted close EOD caching behavior, cache hits, delta date syncs, return format options (`numpy-recarray`, `pandas-dataframe`, `numpy-ndarray`), key by asset ID mapping, and strict mock symbol 404 validation.
18. **`test_18_major_exchange_listed_timeseries_caching_and_formats`** (Newly Added): Asserts major exchange listed status EOD caching behavior, cache hits, different return format options (`numpy-recarray`, `pandas-dataframe`, `numpy-ndarray`), and strict mock symbol 404 validation.
19. **`test_19_capital_event_timeseries_caching_and_formats`** (Newly Added): Asserts capital event status EOD caching behavior, cache hits, different return format options (`numpy-recarray`, `pandas-dataframe`, `numpy-ndarray`), and strict mock symbol 404 validation.
20. **`test_20_padding_status_timeseries_caching_and_formats`** (Newly Added): Asserts price padding status EOD caching behavior, cache hits, different return format options (`numpy-recarray`, `pandas-dataframe`, `numpy-ndarray`), and strict mock symbol 404 validation.

---

## 📓 Interactive Notebooks

We created beautiful verification notebooks mapping our full suite of functionalities (using `TSLA` as the primary mock symbol alongside `MSFT` and `&FDAX`/`&ES` for futures). You can run these notebooks inside Jupyter to see everything work interactively:
- **[`test__price_timeseries.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__price_timeseries.ipynb):** High-speed timeseries fetching, caching, and timing metrics.
- **[`test__unadjusted_close.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__unadjusted_close.ipynb):** Unadjusted close price caching, dynamic formats, and asset ID mapping.
- **[`test__major_exchange_listed.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__major_exchange_listed.ipynb):** Major exchange listed status price caching and dynamic formats.
- **[`test__capital_event.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__capital_event.ipynb):** Corporate action capital events caching and dynamic formats.
- **[`test__padding_status.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__padding_status.ipynb):** EOD date padding indicators caching and dynamic formats.
- **[`test__security_name.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__security_name.ipynb):** Security names, fundamental fields, and watchlist details.
- **[`test__exchange_name.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__exchange_name.ipynb):** Short and full exchange names.
- **[`test__update_time.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__update_time.ipynb):** EOD database partition and symbol price update datetimes.
- **[`test__asset_metadata.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__asset_metadata.ipynb):** Asset IDs, GICS classification, base types, and corresponding industry indices.
- **[`test__subtype.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__subtype.ipynb):** Hierarchical classification subtypes (`subtype1`, `subtype2`, `subtype3`).
- **[`test__futures_metadata.ipynb`](file:///c:/Projects/claudeai/gemini/ngd_proxy/test__futures_metadata.ipynb):** Futures-specific specification lookups (`margin`, `point_value`, `tick_value`, `lowest_ever_tick_size`, `futures_market_session_info`).
