# Sub-Plan: Implementing the `fundamental` lookup function

This sub-plan outlines the exact steps and architectural layers to implement the **`fundamental`** metadata lookup function cleanly while strictly adhering to the constraint that **only timeseries data types are cached locally**.

---

## 🛠️ Feature Overview
- **Function Signature**: `norgatedata.fundamental(symbol_or_assetid, fieldname, datetimeformat='iso')`
- **Return Type**: A Python tuple `(value, date)` containing the latest reported value and the date to which it applies.
- **Caching Behavior**: **No Caching**. Because this function returns a single latest reported value rather than a historical timeseries, it will bypass local SQLite indexing and Parquet file writing entirely, querying the host proxy server dynamically on every call.

---

## 📐 Detailed Component Changes

### 1. 🖥️ Proxy Server (`ngd_proxy/server.py`)
- **Route Definition**:
  - Endpoint: `/fundamental`
  - Parameters: `symbol` (string), `fieldname` (string), and `datetimeformat` (optional, string).
  - Middleware: Protected by the `verify_api_key` dependency.
- **Mock Mode Handling (`MOCK_MODE = True`)**:
  - Implement a synthetic Refinitiv/LSEG generator:
    - Pre-defined accurate mock records for core symbols (e.g., for `ON` PE ratios, book values, etc.).
    - Dynamic random generation based on `fieldname` suffix/prefix for other symbols (e.g., returning numeric values for `pe_ratio`, `eps`, or strings for descriptive fields) with a static mock date (e.g., `"2025-12-31"`).
- **Real Mode Handling (`MOCK_MODE = False`)**:
  - Call the native Windows library:
    ```python
    value, date = norgatedata.fundamental(symbol, fieldname, datetimeformat=datetimeformat)
    return {"value": value, "date": date}
    ```

### 2. 📡 Proxy Client (`ngd_proxy/client.py`)
- Add the `fundamental` method inside the `NorgateDataClient` class:
  ```python
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
  ```

### 3. 💾 Cache Manager Pass-Through (`ngd_proxy/norgatedata_cache.py`)
- Enforce the non-timeseries caching bypass by defining a direct pass-through wrapper method:
  ```python
  def fundamental(self, symbol: str, fieldname: str, datetimeformat: str = 'iso') -> tuple:
      """
      Exposes current single-value fundamental lookup.
      Bypasses local Parquet file-caching and database indexing entirely.
      """
      return self.client.fundamental(symbol, fieldname, datetimeformat)
  ```

### 4. 📦 Main Package Root (`ngd_proxy/__init__.py`)
- Expose the top-level convenience function:
  ```python
  def fundamental(symbol: str, fieldname: str, datetimeformat: str = 'iso') -> tuple:
      return _get_cache().fundamental(symbol, fieldname, datetimeformat)
  ```

---

## 🧪 Verification & Testing Plan

### 1. Mock Data Validation
Add a dedicated test case `test_fundamental_mock_data` in `tests/test_cache.py`:
- Call `norgatedata.fundamental("ON", "pe")`.
- Assert that it returns a valid tuple containing a float (e.g. `24.5`) and a date string (e.g. `"2025-12-31"`).
- Call a non-existent symbol/field and assert it handles `None, None` gracefully.

### 2. Caching Bypass Validation
Add a dedicated test case `test_fundamental_cache_bypass` in `tests/test_cache.py`:
- Record the count of `.parquet` files and SQLite entries under `test_norgate_cache/`.
- Call `norgatedata.fundamental("AAPL", "eps")` multiple times.
- Assert that **no new `.parquet` file has been created on disk** and **no SQLite metadata row has been inserted**, proving that the lookup successfully bypassed the caching engine.
