# Sub-Plan: Implementing `subtype1`, `subtype2`, and `subtype3` Metadata Classifications

This implementation plan outlines the architectural additions, routing changes, client-side pass-throughs, and mock datasets required to support the hierarchical security classification functions **`subtype1`**, **`subtype2`**, and **`subtype3`** under `ngd_proxy`.

---

## 🛠️ Feature Overview

- **Function Signatures**:
  - `norgatedata.subtype1(symbol_or_assetid)`
  - `norgatedata.subtype2(symbol_or_assetid)`
  - `norgatedata.subtype3(symbol_or_assetid)`
- **Return Type**: `Optional[str]` (returns a string classification level or `None` if not available / not classified).
- **Hierarchy Details**:
  - **`subtype1`**: Broad classification level below the base type (e.g., `Equity`, `Exchange Traded Product`, `Debt`, `Hybrid`).
  - **`subtype2`**: Intermediate classification level (e.g., `Operating Company`, `ETF`, `ETN`).
  - **`subtype3`**: Granular classification level (e.g., `Common Stock`, `Closed-End Fund`, `SPAC`, `MLP`).
- **Caching Behavior**: **No Caching** (strictly bypasses Parquet/SQLite storage, matching our clean-design direct metadata pass-through convention).

---

## 📐 Detailed Component Changes

### 1. 🖥️ Proxy Server (`ngd_proxy/server.py`)
- **Route Definitions**:
  - Endpoint: `/subtype1` (Parameters: `symbol: str`)
  - Endpoint: `/subtype2` (Parameters: `symbol: str`)
  - Endpoint: `/subtype3` (Parameters: `symbol: str`)
  - Middleware: Protected by the `verify_api_key` dependency.
- **Mock Mode Handling (`MOCK_MODE = True`)**:
  - Convert numeric asset IDs to uppercase symbols (`1001` -> `TSLA`, `1002` -> `MSFT`).
  - Strict validation: If symbol/ID is not `TSLA`, `MSFT`, `1001`, or `1002`, raise a `404` error.
  - Return responses:
    - **`TSLA` / `1001`**:
      - `/subtype1` -> `{"symbol": symbol_upper, "subtype1": "Equity"}`
      - `/subtype2` -> `{"symbol": symbol_upper, "subtype2": "Operating Company"}`
      - `/subtype3` -> `{"symbol": symbol_upper, "subtype3": "Common Stock"}`
    - **`MSFT` / `1002`**:
      - `/subtype1` -> `{"symbol": symbol_upper, "subtype1": "Equity"}`
      - `/subtype2` -> `{"symbol": symbol_upper, "subtype2": "Operating Company"}`
      - `/subtype3` -> `{"symbol": symbol_upper, "subtype3": "Common Stock"}`
- **Real Mode Handling (`MOCK_MODE = False`)**:
  - Dynamically call native library functions:
    ```python
    res1 = norgatedata.subtype1(symbol)
    res2 = norgatedata.subtype2(symbol)
    res3 = norgatedata.subtype3(symbol)
    ```

---

### 2. 📡 Proxy Client (`ngd_proxy/client.py`)
- Define HTTP consumer methods within `NorgateDataClient`:
  ```python
  def subtype1(self, symbol: str) -> Optional[str]:
      url = f"{self.base_url}/subtype1"
      params = {"symbol": symbol}
      response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
      response.raise_for_status()
      return response.json().get("subtype1")

  def subtype2(self, symbol: str) -> Optional[str]:
      url = f"{self.base_url}/subtype2"
      params = {"symbol": symbol}
      response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
      response.raise_for_status()
      return response.json().get("subtype2")

  def subtype3(self, symbol: str) -> Optional[str]:
      url = f"{self.base_url}/subtype3"
      params = {"symbol": symbol}
      response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
      response.raise_for_status()
      return response.json().get("subtype3")
  ```

---

### 3. 💾 Cache Manager Pass-Through (`ngd_proxy/norgatedata_cache.py`)
- Expose direct cache-bypass methods within `NorgateDataCache`:
  ```python
  def subtype1(self, symbol: str) -> Optional[str]:
      return self.client.subtype1(symbol)

  def subtype2(self, symbol: str) -> Optional[str]:
      return self.client.subtype2(symbol)

  def subtype3(self, symbol: str) -> Optional[str]:
      return self.client.subtype3(symbol)
  ```

---

### 📦 4. Main Package Export (`ngd_proxy/__init__.py`)
- Expose the user convenience functions at the package namespace level:
  ```python
  def subtype1(symbol: str) -> Optional[str]:
      return _get_cache().subtype1(symbol)

  def subtype2(symbol: str) -> Optional[str]:
      return _get_cache().subtype2(symbol)

  def subtype3(symbol: str) -> Optional[str]:
      return _get_cache().subtype3(symbol)
  ```
- Register `subtype1`, `subtype2`, and `subtype3` in `__all__`.

---

## 🧪 Verification & Testing Plan

### 1. Automated Integration Tests (`tests/test_cache.py`)
- Add integration tests validating return values in Uvicorn testing framework:
  - Assert that calling `norgatedata.subtype1("TSLA")` returns `"Equity"`.
  - Assert that calling `norgatedata.subtype2("MSFT")` returns `"Operating Company"`.
  - Assert that calling `norgatedata.subtype3("TSLA")` returns `"Common Stock"`.
  - Assert that calling an invalid/unsupported symbol (e.g., `"AAPL"`) in Mock Mode raises a proper HTTP `404` client exception.
- Add caching bypass assertions:
  - Call the subtype functions repeatedly and assert that no local SQLite rows or Parquet cache files are written, verifying that these lookups bypass local cache directories completely.

### 2. Interactive Notebook Validation (`test__subtype.ipynb`)
- Recreate a beautiful Jupyter notebook `test__subtype.ipynb` using the standard mockup format demonstrating usage, output types, and error handling for invalid/unsupported symbols.
