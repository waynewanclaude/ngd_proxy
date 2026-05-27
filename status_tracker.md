# Norgate Data API Function Implementation & Test Tracker

This database tracks the implementation status of all 26 official Norgate Data API functions and properties. 

### Status Legend
*   **`YES`**: Fully implemented and passes the automated test suite.
*   **`FAILED`**: Implemented but failing one or more integration/unit tests.
*   **`PLAN`**: Implementation plan is accepted/created, but the code is pending implementation.
*   **`NO`**: Pending implementation, and **no** implementation plan has been drafted yet.
*   **`DROP`**: Will not implement (decided by design).

---

## 📊 API Status Database

| # | Function / Property Name | Category | Current Status | Notes |
|---|---------------------------|----------|----------------|-------|
| 1 | `price_timeseries` | Price / Volume | **`YES`** | Fully implemented, cached locally via Parquet, passes performance test. |
| 2 | `unadjusted_close_timeseries` | Price / Volume | **`YES`** | Fully implemented, cached locally via Parquet, supporting recarray, dataframe and ndarray formats. |
| 3 | `index_constituent_timeseries` | Time Series | **`YES`** | Fully implemented, cached locally via Parquet, passes index sync test. |
| 4 | `major_exchange_listed_timeseries` | Time Series | **`NO`** | Pending timeseries caching implementation. |
| 5 | `capital_event_timeseries` | Time Series | **`NO`** | Pending timeseries caching implementation. |
| 6 | `dividend_yield_timeseries` | Time Series | **`YES`** | Fully implemented, cached locally via Parquet, passes yield test. |
| 7 | `padding_status_timeseries` | Time Series | **`NO`** | Pending timeseries caching implementation. |
| 8 | `security_name` | Metadata | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 9 | `exchange_name` | Metadata | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 10 | `exchange_name_full` | Metadata | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 11 | `base_type` | Metadata | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 12 | `subtype1` (incl. `2` and `3`) | Metadata | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 13 | `assetid` | Metadata | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 14 | `classification` | Classifications | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 15 | `corresponding_industry_index` | Classifications | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 16 | `fundamental` | Fundamentals | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 17 | `watchlists` | Watchlists | **`YES`** | Implemented, routes through proxy client to host server. |
| 18 | `watchlist` | Watchlists | **`YES`** | Fully implemented, direct native mapping, bypasses cache, passes mock & bypass tests. |
| 19 | `watchlist_symbols` | Watchlists | **`YES`** | Implemented, routes through proxy client to host server. |
| 20 | `margin` | Futures | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 21 | `point_value` | Futures | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 22 | `tick_value` | Futures | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 23 | `lowest_ever_tick_size` | Futures | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 24 | `futures_market_session_info` | Futures | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 25 | `last_database_update_time` | Database Property | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
| 26 | `last_price_update_time` | Database Property | **`YES`** | Fully implemented, direct pass-through, bypasses cache, passes mock & bypass tests. |
