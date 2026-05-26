# Sub-Plan: Implementing the `last_database_update_time` and `last_price_update_time` lookup functions

This sub-plan outlines the exact steps and architectural layers to implement the **`last_database_update_time`** and **`last_price_update_time`** lookup functions cleanly while strictly adhering to the constraint that **only timeseries data types are cached locally**.

---

## 🛠️ Feature Overview
- **Function Signatures**: 
  - `norgatedata.last_database_update_time(database)`
  - `norgatedata.last_price_update_time(symbol)`
- **Return Type**: A Python `datetime` object indicating when data was last updated on the local PC (or `None` if not found).
- **Caching Behavior**: **No Caching**. Because these functions return a single latest update datetime rather than a historical timeseries, they will bypass local SQLite indexing and Parquet file writing entirely, querying the host proxy server dynamically on every call.

---

## 📐 Detailed Component Changes

### 1. 🖥️ Proxy Server (`ngd_proxy/server.py`)
- **Route Definitions**:
  - Endpoint: `/last_database_update_time`
    - Parameter: `database` (string)
  - Endpoint: `/last_price_update_time`
    - Parameter: `symbol` (string or integer asset ID)
  - Middleware: Protected by the `verify_api_key` dependency.
- **Mock Mode Handling (`MOCK_MODE = True`)**:
  - For `last_database_update_time`:
    - Accept only `'us'` and `'forex'`. For any other database, raise a `404` error.
    - Return `{"last_database_update_time": "2026-05-26T00:00:00"}`.
  - For `last_price_update_time`:
    - Accept only `TSLA`, `MSFT`, `1001`, and `1002`. Resolve `1001` -> `TSLA` and `1002` -> `MSFT`. For any other symbol, raise a `404` error.
    - Return `{"last_price_update_time": "2026-05-26T01:00:00"}`.
- **Real Mode Handling (`MOCK_MODE = False`)**:
  - Call the native Windows library dynamically:
    ```python
    # For /last_database_update_time
    dt = norgatedata.last_database_update_time(database)
    return {"database": database, "last_database_update_time": dt.isoformat() if dt else None}
    
    # For /last_price_update_time
    dt = norgatedata.last_price_update_time(symbol)
    return {"symbol": symbol, "last_price_update_time": dt.isoformat() if dt else None}
    ```

### 2. 📡 Proxy Client (`ngd_proxy/client.py`)
- Add methods inside the `NorgateDataClient` class, parsing the returned ISO datetime string back into a Python `datetime` object:
  ```python
  from datetime import datetime

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
  ```

### 3. 💾 Cache Manager Pass-Through (`ngd_proxy/norgatedata_cache.py`)
- Enforce the non-timeseries caching bypass by defining direct pass-through wrapper methods in `NorgateDataCache`:
  ```python
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
  ```

### 📦 4. Main Package Root (`ngd_proxy/__init__.py`)
- Expose the top-level convenience functions:
  ```python
  def last_database_update_time(database: str) -> Optional[datetime]:
      return _get_cache().last_database_update_time(database)

  def last_price_update_time(symbol: str) -> Optional[datetime]:
      return _get_cache().last_price_update_time(symbol)
  ```
- Expose these functions in `__all__`.

---

## 🧪 Verification & Testing Plan

### 1. Mock Data Validation
Add dedicated test cases in `tests/test_cache.py`:
- Call `norgatedata.last_database_update_time("us")` and assert it returns `datetime(2026, 5, 26, 0, 0, 0)`.
- Call `norgatedata.last_price_update_time("TSLA")` and assert it returns `datetime(2026, 5, 26, 1, 0, 0)`.
- Call invalid inputs (like invalid symbol or invalid database) and assert they raise exceptions (clean 404 in mock mode).

### 2. Caching Bypass Validation
Add dedicated cache-bypass assertions in `tests/test_cache.py`:
- Call `norgatedata.last_price_update_time("MSFT")` multiple times.
- Assert that **no new `.parquet` file has been created on disk** and **no SQLite metadata row has been inserted**, proving that the lookup bypassed the caching engine completely.
