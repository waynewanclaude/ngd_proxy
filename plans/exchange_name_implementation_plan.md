# Sub-Plan: Implementing the `exchange_name` and `exchange_name_full` lookup functions

This sub-plan outlines the exact steps and architectural layers to implement the **`exchange_name`** and **`exchange_name_full`** metadata lookup functions cleanly while strictly adhering to the constraint that **only timeseries data types are cached locally**.

---

## 🛠️ Feature Overview
- **Function Signatures**: 
  - `norgatedata.exchange_name(symbol_or_assetid)`
  - `norgatedata.exchange_name_full(symbol_or_assetid)`
- **Return Type**: A Python string containing the short or full exchange name (or `None` / empty if not found).
- **Caching Behavior**: **No Caching**. Because these functions return a single metadata string rather than a historical timeseries, they will bypass local SQLite indexing and Parquet file writing entirely, querying the host proxy server dynamically on every call.

---

## 📐 Detailed Component Changes

### 1. 🖥️ Proxy Server (`ngd_proxy/server.py`)
- **Route Definitions**:
  - Endpoint: `/exchange_name`
  - Endpoint: `/exchange_name_full`
  - Parameters: `symbol` (string or integer asset ID).
  - Middleware: Protected by the `verify_api_key` dependency.
- **Mock Mode Handling (`MOCK_MODE = True`)**:
  - Map against standard mock database dictionary:
    ```python
    mock_exchanges = {
        "TSLA": {"short": "NASDAQ", "full": "Nasdaq Stock Market"},
        "MSFT": {"short": "NASDAQ", "full": "Nasdaq Stock Market"}
    }
    ```
  - Handle resolving Asset IDs `1001` to `TSLA` and `1002` to `MSFT`.
  - If the symbol is not `TSLA` or `MSFT` (or asset IDs `1001` or `1002`), it raises an HTTP 404 error.
- **Real Mode Handling (`MOCK_MODE = False`)**:
  - Call the native Windows library dynamically:
    ```python
    # For /exchange_name
    name = norgatedata.exchange_name(symbol)
    return {"symbol": symbol, "exchange_name": name}
    
    # For /exchange_name_full
    name_full = norgatedata.exchange_name_full(symbol)
    return {"symbol": symbol, "exchange_name_full": name_full}
    ```

### 2. 📡 Proxy Client (`ngd_proxy/client.py`)
- Add methods inside the `NorgateDataClient` class:
  ```python
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
  ```

### 3. 💾 Cache Manager Pass-Through (`ngd_proxy/norgatedata_cache.py`)
- Enforce the non-timeseries caching bypass by defining direct pass-through wrapper methods in `NorgateDataCache`:
  ```python
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
  ```

### 📦 4. Main Package Root (`ngd_proxy/__init__.py`)
- Expose the top-level convenience functions:
  ```python
  def exchange_name(symbol: str) -> Optional[str]:
      return _get_cache().exchange_name(symbol)

  def exchange_name_full(symbol: str) -> Optional[str]:
      return _get_cache().exchange_name_full(symbol)
  ```
- Expose these functions in `__all__`.

---

## 🧪 Verification & Testing Plan

### 1. Mock Data Validation
Add dedicated test cases in `tests/test_cache.py`:
- Call `norgatedata.exchange_name("TSLA")` and assert it returns `"NASDAQ"`.
- Call `norgatedata.exchange_name_full("MSFT")` and assert it returns `"Nasdaq Stock Market"`.
- Call an invalid symbol and assert it raises an error (clean 404 in mock mode).

### 2. Caching Bypass Validation
Add dedicated cache-bypass assertions in `tests/test_cache.py`:
- Call `norgatedata.exchange_name("TSLA")` multiple times.
- Assert that **no new `.parquet` file has been created on disk** and **no SQLite metadata row has been inserted**, proving that the lookup bypassed the caching engine completely.
