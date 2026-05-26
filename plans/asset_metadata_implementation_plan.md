# Sub-Plan: Implementing `assetid`, `base_type`, `classification`, and `corresponding_industry_index`

This sub-plan outlines the exact steps and architectural layers to implement the **`assetid`**, **`base_type`**, **`classification`**, and **`corresponding_industry_index`** lookup functions cleanly while strictly adhering to the constraint that **only timeseries data types are cached locally**.

---

## 🛠️ Feature Overview
- **Function Signatures**:
  - `norgatedata.assetid(symbol)`
  - `norgatedata.base_type(symbol_or_assetid)`
  - `norgatedata.classification(symbol_or_assetid, schemename)`
  - `norgatedata.corresponding_industry_index(symbol_or_assetid, indexfamilycode, level, indexreturntype)`
- **Return Type**:
  - `assetid`: integer ID (or `None`).
  - `base_type`: string category (or `None`).
  - `classification`: string classification category (or `None`).
  - `corresponding_industry_index`: string index symbol (or `None`).
- **Caching Behavior**: **No Caching**. Because these functions return single metadata values rather than historical timeseries, they will bypass local SQLite indexing and Parquet file writing entirely, querying the host proxy server dynamically on every call.

---

## 📐 Detailed Component Changes

### 1. 🖥️ Proxy Server (`ngd_proxy/server.py`)
- **Route Definitions**:
  - Endpoint: `/assetid` (Parameters: `symbol`)
  - Endpoint: `/base_type` (Parameters: `symbol`)
  - Endpoint: `/classification` (Parameters: `symbol`, `schemename`)
  - Endpoint: `/corresponding_industry_index` (Parameters: `symbol`, `indexfamilycode`, `level`, `indexreturntype`)
  - Middleware: Protected by the `verify_api_key` dependency.
- **Mock Mode Handling (`MOCK_MODE = True`)**:
  - Resolve asset ID (`1001` -> `TSLA`, `1002` -> `MSFT`).
  - If input is not `TSLA`, `MSFT`, `1001`, or `1002`, raise a `404` error.
  - Return values:
    *   `/assetid`: `{"symbol": symbol, "assetid": 1001 if symbol_upper == "TSLA" else 1002}`
    *   `/base_type`: `{"symbol": symbol, "base_type": "Stock Market"}`
    *   `/classification`: `{"symbol": symbol, "classification": "Automobile" if symbol_upper == "TSLA" else "Software"}`
    *   `/corresponding_industry_index`: `{"symbol": symbol, "corresponding_industry_index": "$SP500-15" if symbol_upper == "TSLA" else "$SP500-45"}`
- **Real Mode Handling (`MOCK_MODE = False`)**:
  - Call native Windows library methods dynamically:
    ```python
    # For /assetid
    res = norgatedata.assetid(symbol)
    
    # For /base_type
    res = norgatedata.base_type(symbol)
    
    # For /classification
    res = norgatedata.classification(symbol, schemename)
    
    # For /corresponding_industry_index
    res = norgatedata.corresponding_industry_index(symbol, indexfamilycode, level, indexreturntype)
    ```

### 2. 📡 Proxy Client (`ngd_proxy/client.py`)
- Add methods inside `NorgateDataClient`:
  ```python
  def assetid(self, symbol: str) -> Optional[int]:
      url = f"{self.base_url}/assetid"
      params = {"symbol": symbol}
      response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
      response.raise_for_status()
      return response.json().get("assetid")

  def base_type(self, symbol: str) -> Optional[str]:
      url = f"{self.base_url}/base_type"
      params = {"symbol": symbol}
      response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
      response.raise_for_status()
      return response.json().get("base_type")

  def classification(self, symbol: str, schemename: str) -> Optional[str]:
      url = f"{self.base_url}/classification"
      params = {"symbol": symbol, "schemename": schemename}
      response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
      response.raise_for_status()
      return response.json().get("classification")

  def corresponding_industry_index(self, symbol: str, indexfamilycode: str, level: int, indexreturntype: str) -> Optional[str]:
      url = f"{self.base_url}/corresponding_industry_index"
      params = {
          "symbol": symbol,
          "indexfamilycode": indexfamilycode,
          "level": level,
          "indexreturntype": indexreturntype
      }
      response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
      response.raise_for_status()
      return response.json().get("corresponding_industry_index")
  ```

### 3. 💾 Cache Manager Pass-Through (`ngd_proxy/norgatedata_cache.py`)
- Enforce the non-timeseries caching bypass by defining direct pass-through wrapper methods in `NorgateDataCache`:
  ```python
  def assetid(self, symbol: str) -> Optional[int]:
      return self.client.assetid(symbol)

  def base_type(self, symbol: str) -> Optional[str]:
      return self.client.base_type(symbol)

  def classification(self, symbol: str, schemename: str) -> Optional[str]:
      return self.client.classification(symbol, schemename)

  def corresponding_industry_index(self, symbol: str, indexfamilycode: str, level: int, indexreturntype: str) -> Optional[str]:
      return self.client.corresponding_industry_index(symbol, indexfamilycode, level, indexreturntype)
  ```

### 📦 4. Main Package Root (`ngd_proxy/__init__.py`)
- Expose the top-level convenience functions:
  ```python
  def assetid(symbol: str) -> Optional[int]:
      return _get_cache().assetid(symbol)

  def base_type(symbol: str) -> Optional[str]:
      return _get_cache().base_type(symbol)

  def classification(symbol: str, schemename: str) -> Optional[str]:
      return _get_cache().classification(symbol, schemename)

  def corresponding_industry_index(symbol: str, indexfamilycode: str, level: int, indexreturntype: str) -> Optional[str]:
      return _get_cache().corresponding_industry_index(symbol, indexfamilycode, level, indexreturntype)
  ```
- Expose these functions in `__all__`.

---

## 🧪 Verification & Testing Plan

### 1. Mock Data Validation
Add dedicated test cases in `tests/test_cache.py`:
- Call `norgatedata.assetid("TSLA")` and assert it returns `1001`.
- Call `norgatedata.base_type("MSFT")` and assert it returns `"Stock Market"`.
- Call `norgatedata.classification("TSLA", "GICS")` and assert it returns `"Automobile"`.
- Call `norgatedata.corresponding_industry_index("MSFT", "$SPX", 3, "TR")` and assert it returns `"$SP500-45"`.
- Call an invalid symbol and assert it raises an error (clean 404 in mock mode).

### 2. Caching Bypass Validation
Add dedicated cache-bypass assertions in `tests/test_cache.py`:
- Call `norgatedata.assetid("MSFT")` multiple times.
- Assert that **no new `.parquet` file has been created on disk** and **no SQLite metadata row has been inserted**, proving that the lookup bypassed the caching engine completely.
