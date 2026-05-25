# Norgate Data Proxy (`ngd_proxy`)

A lightweight, high-performance, cross-platform bridge and caching system designed to access **Windows-only Norgate Data** from **macOS, Linux, and Windows** environments.

## Architecture Overview

```
 ┌───────────────────────────────────────┐
 │   macOS / Linux / Windows Client      │
 │  ┌─────────────────────────────────┐  │
 │  │        Trading Script           │  │
 │  └────────────────┬────────────────┘  │
 │                   │                   │
 │  ┌────────────────▼────────────────┐  │
 │  │   NorgateDataCache (Parquet)    │  │
 │  └────────────────┬────────────────┘  │
 │                   │ (Cache Miss)      │
 │  ┌────────────────▼────────────────┐  │
 │  │       NorgateDataClient         │  │
 │  └────────────────┬────────────────┘  │
 └───────────────────┼───────────────────┘
                     │ HTTP + Parquet (X-API-Key)
 ┌───────────────────┼───────────────────┐
 │       Windows Host (or VM)            │
 │  ┌────────────────▼────────────────┐  │
 │  │         FastAPI Server          │  │
 │  └────────────────┬────────────────┘  │
 │                   │ (Local Call)      │
 │  ┌────────────────▼────────────────┐  │
 │  │   norgatedata Python Library   │  │
 │  └────────────────┬────────────────┘  │
 │  ┌────────────────▼────────────────┐  │
 │  │    Norgate Data Updater (NDU)   │  │
 │  └─────────────────────────────────┘  │
 └───────────────────────────────────────┘
```

---

## Key Features

1. **High-Performance Serialization:** Standard JSON is slow and discards complex Pandas data types (like timezones, precise integers/floats, and categorical data). This proxy defaults to **Apache Parquet** (`application/x-parquet`) to stream dataframes over HTTP instantly, maintaining 100% type-fidelity.
2. **Unified Client-Side Caching Layer:** Caches all primary Norgate timeseries types:
   - Price & Volume timeseries (`price_timeseries`)
   - Historical Index Membership timeseries (`index_constituent_timeseries`)
   - Fundamentals (Dividend yield, exchange listing status, capital events)
3. **Smart Range Merging (Incremental Sync):** When querying a time series, the client-side cache automatically:
   - Returns a sliced subset instantly (in microseconds) if already fully cached.
   - Queries *only the missing dates* from the Windows host if the cache is slightly out-of-date, appending the new bars and writing them back to disk.
4. **LRU/LFU Eviction:** Automatically monitors cache directories and prunes old, inactive, or "dead" symbols when a configurable storage threshold is reached.
5. **Secure Local Access:** Includes simple API key validation via `X-API-Key` headers for safe deployment on local networks or VMs.

---

## Quick Start

### 1. Windows Host Setup (Server)

Install dependencies on your Windows host:
```bash
pip install -r requirements.txt
```

Launch the server (NDU must be running):
```bash
python server.py
```
*To run with simulated mock data (no active NNDU subscription required for testing), use:*
```bash
python server.py --mock
```

Open `http://localhost:8000/dashboard` in a browser to see system load, active query counters, and NDU status.

### 2. Client Setup (macOS / Linux / Windows)

Copy `client.py`, `norgatedata_cache.py`, and `config.json` to your client machine.

Configure your connection in `config.json`:
```json
{
  "server_base_url": "http://<windows-ip>:8000",
  "api_key": "norgate-secure-default-key-replace-me",
  "cache_enabled": true,
  "cache_dir": "~/.cache/norgatedata",
  "max_cache_size_mb": 10000,
  "eviction_policy": "LRU",
  "refresh_expired_days": 1
}
```

### 3. Usage Example

Replaces your standard `norgatedata` imports. It exposes the exact same method names:

```python
from norgatedata_cache import NorgateDataCache

# Initialise the cache manager (it automatically handles local cache & HTTP proxy calls)
cache = NorgateDataCache()

# 1. Fetching Price Timeseries
df = cache.price_timeseries(
    "AAPL",
    stock_price_adjustment_setting="TOTALRETURN",
    start_date="2020-01-01"
)
print("AAPL Prices:\n", df.tail())

# 2. Fetching Historical Index Membership
index_df = cache.index_constituent_timeseries(
    "AAPL",
    "S&P 500",
    start_date="2020-01-01"
)
print("\nAAPL Index Membership:\n", index_df.tail())
```

---

## Developer Guide & Testing

To verify cache performance and eviction mechanics:
```bash
python test_cache.py
```
