# Sub-Plan: Implementing Futures-Specific Metadata Functions

This implementation plan outlines the architectural additions, routing changes, client-side pass-throughs, and mock datasets required to support the futures-specific metadata functions **`margin`**, **`point_value`**, **`tick_value`**, **`lowest_ever_tick_size`**, and **`futures_market_session_info`** under `ngd_proxy`.

---

## 🛠️ Feature Overview

- **Function Signatures**:
  - `norgatedata.margin(symbol_or_assetid)`
  - `norgatedata.point_value(symbol_or_assetid)`
  - `norgatedata.tick_value(symbol_or_assetid)`
  - `norgatedata.lowest_ever_tick_size(symbol_or_assetid)`
  - `norgatedata.futures_market_session_info(symbol_or_assetid)`
- **Return Type**:
  - `margin`, `point_value`, `tick_value`, `lowest_ever_tick_size`: `Optional[float]` (returns the value or `None` if not a futures contract/market).
  - `futures_market_session_info`: `Optional[str]` (returns trading session category e.g. `"Combined"` or `None` if not a futures contract/market).
- **Caching Behavior**: **No Caching** (strictly bypasses Parquet/SQLite caching, aligning with our direct metadata lookup design).

---

## 📐 Detailed Component Changes

### 1. 🖥️ Proxy Server (`ngd_proxy/server.py`)
- **Route Definitions**:
  - Endpoint: `/margin` (Parameters: `symbol: str`)
  - Endpoint: `/point_value` (Parameters: `symbol: str`)
  - Endpoint: `/tick_value` (Parameters: `symbol: str`)
  - Endpoint: `/lowest_ever_tick_size` (Parameters: `symbol: str`)
  - Endpoint: `/futures_market_session_info` (Parameters: `symbol: str`)
  - Middleware: Protected by the `verify_api_key` dependency.
- **Mock Mode Handling (`MOCK_MODE = True`)**:
  - Convert numeric asset IDs to uppercase symbols (`2001` -> `&FDAX`, `2002` -> `&ES`, `1001` -> `TSLA`, `1002` -> `MSFT`).
  - Validation:
    - If symbol/ID is one of our equity mock assets (`TSLA`, `MSFT`, `1001`, `1002`), return `None` for all values (since stocks have no futures specs).
    - If symbol/ID is one of our futures mock assets (`&FDAX`, `FDAX`, `2001`) or (`&ES`, `ES`, `2002`), return appropriate values:
      - **`&FDAX` / `FDAX` / `2001`**:
        - `/margin` -> `{"symbol": symbol_upper, "margin": 18000.0}`
        - `/point_value` -> `{"symbol": symbol_upper, "point_value": 25.0}`
        - `/tick_value` -> `{"symbol": symbol_upper, "tick_value": 12.5}`
        - `/lowest_ever_tick_size` -> `{"symbol": symbol_upper, "lowest_ever_tick_size": 0.5}`
        - `/futures_market_session_info` -> `{"symbol": symbol_upper, "futures_market_session_info": "Combined"}`
      - **`&ES` / `ES` / `2002`**:
        - `/margin` -> `{"symbol": symbol_upper, "margin": 12000.0}`
        - `/point_value` -> `{"symbol": symbol_upper, "point_value": 50.0}`
        - `/tick_value` -> `{"symbol": symbol_upper, "tick_value": 12.5}`
        - `/lowest_ever_tick_size` -> `{"symbol": symbol_upper, "lowest_ever_tick_size": 0.25}`
        - `/futures_market_session_info` -> `{"symbol": symbol_upper, "futures_market_session_info": "Combined"}`
    - If symbol/ID is any other symbol, raise a `404` error in Mock Mode.
- **Real Mode Handling (`MOCK_MODE = False`)**:
  - Apply `resolve_symbol(symbol)` helper to handle digit-string asset IDs.
  - Dynamically call native library functions:
    ```python
    res = norgatedata.margin(resolved_symbol)
    res = norgatedata.point_value(resolved_symbol)
    res = norgatedata.tick_value(resolved_symbol)
    res = norgatedata.lowest_ever_tick_size(resolved_symbol)
    res = norgatedata.futures_market_session_info(resolved_symbol)
    ```

---

### 2. 📡 Proxy Client (`ngd_proxy/client.py`)
- Define HTTP consumer methods within `NorgateDataClient`:
  ```python
  def margin(self, symbol: str) -> Optional[float]:
      url = f"{self.base_url}/margin"
      params = {"symbol": symbol}
      response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
      response.raise_for_status()
      return response.json().get("margin")

  def point_value(self, symbol: str) -> Optional[float]:
      url = f"{self.base_url}/point_value"
      params = {"symbol": symbol}
      response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
      response.raise_for_status()
      return response.json().get("point_value")

  def tick_value(self, symbol: str) -> Optional[float]:
      url = f"{self.base_url}/tick_value"
      params = {"symbol": symbol}
      response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
      response.raise_for_status()
      return response.json().get("tick_value")

  def lowest_ever_tick_size(self, symbol: str) -> Optional[float]:
      url = f"{self.base_url}/lowest_ever_tick_size"
      params = {"symbol": symbol}
      response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
      response.raise_for_status()
      return response.json().get("lowest_ever_tick_size")

  def futures_market_session_info(self, symbol: str) -> Optional[str]:
      url = f"{self.base_url}/futures_market_session_info"
      params = {"symbol": symbol}
      response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
      response.raise_for_status()
      return response.json().get("futures_market_session_info")
  ```

---

### 3. 💾 Cache Manager Pass-Through (`ngd_proxy/norgatedata_cache.py`)
- Expose direct cache-bypass methods within `NorgateDataCache`:
  ```python
  def margin(self, symbol: str) -> Optional[float]:
      return self.client.margin(symbol)

  def point_value(self, symbol: str) -> Optional[float]:
      return self.client.point_value(symbol)

  def tick_value(self, symbol: str) -> Optional[float]:
      return self.client.tick_value(symbol)

  def lowest_ever_tick_size(self, symbol: str) -> Optional[float]:
      return self.client.lowest_ever_tick_size(symbol)

  def futures_market_session_info(self, symbol: str) -> Optional[str]:
      return self.client.futures_market_session_info(symbol)
  ```

---

### 📦 4. Main Package Export (`ngd_proxy/__init__.py`)
- Expose the user convenience functions at the package namespace level:
  ```python
  def margin(symbol: str) -> Optional[float]:
      return _get_cache().margin(symbol)

  def point_value(symbol: str) -> Optional[float]:
      return _get_cache().point_value(symbol)

  def tick_value(symbol: str) -> Optional[float]:
      return _get_cache().tick_value(symbol)

  def lowest_ever_tick_size(symbol: str) -> Optional[float]:
      return _get_cache().lowest_ever_tick_size(symbol)

  def futures_market_session_info(symbol: str) -> Optional[str]:
      return _get_cache().futures_market_session_info(symbol)
  ```
- Register the functions in `__all__`.

---

## 🧪 Verification & Testing Plan

### 1. Automated Integration Tests (`tests/test_cache.py`)
- Add integration tests validating return values in Uvicorn testing framework:
  - Assert that calling `norgatedata.margin("&FDAX")` returns `18000.0`.
  - Assert that calling `norgatedata.point_value("&ES")` returns `50.0`.
  - Assert that calling `norgatedata.tick_value("&FDAX")` returns `12.5`.
  - Assert that calling `norgatedata.lowest_ever_tick_size("&ES")` returns `0.25`.
  - Assert that calling `norgatedata.futures_market_session_info("&FDAX")` returns `"Combined"`.
  - Assert that calling these functions on equity mock assets (`TSLA`, `MSFT`) cleanly returns `None` (representing non-futures behavior).
  - Assert that calling an invalid/unsupported symbol (e.g., `"AAPL"`) in Mock Mode raises a proper HTTP `404` client exception.
- Add caching bypass assertions:
  - Call the futures functions repeatedly and assert that no local SQLite rows or Parquet cache files are written, verifying that these lookups bypass local cache directories completely.

### 2. Interactive Notebook Validation (`test__futures_metadata.ipynb`)
- Recreate a beautiful Jupyter notebook `test__futures_metadata.ipynb` demonstrating usage, output types, and non-futures behavior for equity assets.
