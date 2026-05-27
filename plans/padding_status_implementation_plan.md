# Implementation Plan: Caching historical `padding_status_timeseries`

This implementation plan outlines the architectural additions, route definitions, caching protocols, and format conversions required to implement the historical data padding indicator function **`padding_status_timeseries`** as a fully cached, drop-in replacement for the native `norgatedata` library.

---

## 🛠️ Feature Overview

- **Official Function Signature**:
  ```python
  norgatedata.padding_status_timeseries(
      symbol, 
      timeseriesformat="numpy-recarray",
      start_date=None,
      end_date=None
  )
  ```
- **Return Value**: An EOD timeseries indicating whether a particular bar was padded (interpolated/copied) in the local Norgate database:
  - `1`: The price record for that date was padded (Date Padding enabled).
  - `0`: The price record represents a native trading day (no padding).
- **Return Formats**: Controlled via `timeseriesformat` parameter:
  - `"pandas-dataframe"`: `pd.DataFrame` containing a `Date` index and a single column `"PaddingStatus"`.
  - `"numpy-recarray"` (Default): `numpy.recarray` structured records containing fields (e.g. `Date` and `PaddingStatus`).
  - `"numpy-ndarray"`: A raw `numpy.ndarray` containing padding status indicators.
- **Caching Mechanism**: **Fully Cached**. Leverages the proxy's unified SQLite tracking db (`cache_metadata` table) and Snappy-compressed Parquet disk cache engine. This ensures sub-millisecond local reads, automatic LRU cache size evictions, and smart trailing range delta syncing.

---

## 📐 Detailed Component Changes

### 1. 🖥️ Proxy Server (`ngd_proxy/server.py`)

We will add mock EOD padding status generators and `/padding_status_timeseries` FastAPI routing support:

- **Mock EOD Padding Status Generator**:
  ```python
  def generate_mock_padding_status(
      symbol: str, 
      start_date: str = "2020-01-01", 
      end_date: Optional[str] = None
  ) -> pd.DataFrame:
      """Generates simulated EOD padding status timeseries (mostly 0s, with rare simulated holiday padded bars)."""
      if not end_date:
          end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
      dates = pd.bdate_range(start=start_date, end=end_date)
      n = len(dates)
      if n == 0:
          return pd.DataFrame(columns=["PaddingStatus"])
          
      status_vals = np.zeros(n, dtype=int)
      # Simulate a padded bar (e.g. holiday padding) once every 120 business days
      np.random.seed(abs(hash(symbol)) % 2**32)
      for i in range(45, n, 120):
          status_vals[i] = 1
          
      df = pd.DataFrame({"PaddingStatus": status_vals}, index=dates)
      df.index.name = "Date"
      return df
  ```
- **FastAPI Route Definition**:
  - **Endpoint**: `/padding_status_timeseries`
  - **HTTP Method**: `GET`
  - **Mock Mode Handling (`MOCK_MODE = True`)**:
    - Translate integer IDs to tickers (e.g. `1001` -> `TSLA`, `1002` -> `MSFT`).
    - Validate ticker strictly: support only `TSLA` and `MSFT`. Continuous futures and other tickers must raise a standard `404` exception.
    - Generate mock data using `generate_mock_padding_status()`.
    - Stream serialized parquet/JSON data using `serialize_dataframe()`.
  - **Real Mode Handling (`MOCK_MODE = False`)**:
    - Resolve the symbol/ID to native format using `resolve_symbol()`.
    - Fetch from the native library:
      ```python
      df = norgatedata.padding_status_timeseries(
          resolved_symbol, 
          timeseriesformat="pandas-dataframe",
          start_date=start_date,
          end_date=end_date
      )
      ```
    - Verify data presence, force single column to be `"PaddingStatus"` if not named, and serialize.

---

### 2. 📡 Proxy Client (`ngd_proxy/client.py`)

We will define a lightweight HTTP client method leveraging the existing `self._request_dataframe` utility:

```python
    def padding_status_timeseries(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Fetches historical EOD padding status timeseries from the proxy host.
        """
        params = {"symbol": symbol}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
            
        return self._request_dataframe("/padding_status_timeseries", params)
```

---

### 3. 💾 Cache Manager (`ngd_proxy/norgatedata_cache.py`)

We will implement the cache wrapper method backed by the standard Parquet cacher and casting logic:

```python
    def padding_status_timeseries(
        self,
        symbol: str,
        timeseriesformat: Any = "numpy-recarray",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ):
        """Exposes SQLite-tracked and Parquet-cached historical price padding status."""
        if not self.cache_enabled:
            df = self.client.padding_status_timeseries(symbol, start_date, end_date)
            return self._convert_format(df, timeseriesformat)
            
        # Lambda fetch delegate
        fetch_func = lambda start_date, end_date: self.client.padding_status_timeseries(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date
        )
        
        df_cached = self._get_timeseries(
            "padding_status", 
            symbol, 
            "PADDING_STATUS", 
            start_date, 
            end_date, 
            fetch_func
        )
        return self._convert_format(df_cached, timeseriesformat)
```

---

### 📦 4. Package Export (`ngd_proxy/__init__.py`)

We will expose the convenience function at the top-level package namespace:

```python
def padding_status_timeseries(
    symbol: str,
    timeseriesformat: Union[str, TimeSeriesFormat] = TimeSeriesFormat.NUMPY_RECARRAY,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Returns padding status timeseries indicating which dates have padded prices.
    Matches the official norgatedata.padding_status_timeseries signature.
    """
    if isinstance(timeseriesformat, TimeSeriesFormat):
        timeseriesformat = timeseriesformat.value
    return _get_cache().padding_status_timeseries(
        symbol=symbol,
        timeseriesformat=timeseriesformat,
        start_date=start_date,
        end_date=end_date
    )
```
- Register `padding_status_timeseries` in `__all__` to make it discoverable.

---

## 🧪 Verification & Testing Plan

### Automated Integration Tests (`tests/test_cache.py`)

We will add a dedicated integration test case, **`test_20_padding_status_timeseries_caching_and_formats`**, verifying:
1. **Cache Miss**: Querying a symbol writes tracking records to SQLite (`datatype='padding_status'`) and writes Parquet cache files.
2. **Cache Hit**: Subsequent queries read from local Parquet storage instantly.
3. **Format Conversions**: Validates outputs are correctly cast to standard NumPy record arrays, raw values arrays, or Pandas DataFrames.
4. **Mock Strictness**: Asserting invalid symbols (e.g. `AAPL` or continuous contracts `&FDAX`) raise a proper HTTP client error in Mock Mode.

### Manual Verification (`test__padding_status.ipynb`)

We will create a schema-compliant Jupyter notebook, `test__padding_status.ipynb` demonstrating the usage of `padding_status_timeseries` across all standard formats and verifying the caching metrics.
