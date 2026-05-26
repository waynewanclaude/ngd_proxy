# Sub-Plan: Implementing the `security_name` lookup function

This sub-plan outlines the exact steps and architectural layers to implement the **`security_name`** metadata lookup function cleanly while strictly adhering to the constraint that **only timeseries data types are cached locally**.

---

## 🛠️ Feature Overview
- **Function Signature**: `norgatedata.security_name(symbol_or_assetid)`
- **Return Type**: A Python string containing the full descriptive name of the security (or `None` if not found).
- **Caching Behavior**: **No Caching**. Because this function returns a single metadata string rather than a historical timeseries, it will bypass local SQLite indexing and Parquet file writing entirely, querying the host proxy server dynamically on every call.

---

## 📐 Detailed Component Changes

### 1. 🖥️ Proxy Server (`ngd_proxy/server.py`)
- **Route Definition**:
  - Endpoint: `/security_name`
  - Parameters: `symbol` (string or integer asset ID).
  - Middleware: Protected by the `verify_api_key` dependency.
- **Mock Mode Handling (`MOCK_MODE = True`)**:
  - Match against a mock database dictionary:
    ```python
    mock_names = {
        "ON": "ON Semiconductor Corporation",
        "AAPL": "Apple Inc. Common Stock",
        "MSFT": "Microsoft Corporation Common Stock",
        "GOOGL": "Alphabet Inc. Class A Common Stock",
        "NVDA": "NVIDIA Corporation Common Stock",
        "AMZN": "Amazon.com, Inc. Common Stock"
    }
    ```
  - Returns `{"symbol": symbol, "security_name": name}`.
- **Real Mode Handling (`MOCK_MODE = False`)**:
  - Call the native Windows library:
    ```python
    name = norgatedata.security_name(symbol)
    return {"symbol": symbol, "security_name": name}
    ```

### 2. 📡 Proxy Client (`ngd_proxy/client.py`)
- Add the `security_name` method inside the `NorgateDataClient` class:
  ```python
  def security_name(self, symbol: str) -> Optional[str]:
      """
      Retrieve full security name.
      """
      url = f"{self.base_url}/security_name"
      params = {"symbol": symbol}
      response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
      response.raise_for_status()
      return response.json().get("security_name")
  ```

### 3. 💾 Cache Manager Pass-Through (`ngd_proxy/norgatedata_cache.py`)
- Enforce the non-timeseries caching bypass by defining a direct pass-through wrapper method:
  ```python
  def security_name(self, symbol: str) -> Optional[str]:
      """
      Exposes current single-value security name lookup.
      Bypasses local Parquet file-caching and database indexing entirely.
      """
      return self.client.security_name(symbol)
  ```

### 📦 4. Main Package Root (`ngd_proxy/__init__.py`)
- Expose the top-level convenience function:
  ```python
  def security_name(symbol: str) -> Optional[str]:
      return _get_cache().security_name(symbol)
  ```

---

## 🧪 Verification & Testing Plan

### 1. Mock Data Validation
Add a dedicated test case `test_security_name_mock_data` in `tests/test_cache.py`:
- Call `norgatedata.security_name("ON")`.
- Assert that it returns `"ON Semiconductor Corporation"`.

### 2. Caching Bypass Validation
Add a dedicated test case `test_security_name_cache_bypass` in `tests/test_cache.py`:
- Record the count of `.parquet` files and SQLite entries under `test_norgate_cache/`.
- Call `norgatedata.security_name("AAPL")` multiple times.
- Assert that **no new `.parquet` file has been created on disk** and **no SQLite metadata row has been inserted**, proving that the lookup successfully bypassed the caching engine.
