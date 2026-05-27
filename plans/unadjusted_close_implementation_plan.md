# Implementation Plan: Caching historical `unadjusted_close_timeseries`

This implementation plan outlines the architectural changes, FastAPI route definitions, client-side HTTP integration, cache manager interceptor logic, and output format conversion layers required to implement the historical timeseries function **`unadjusted_close_timeseries`** as a fully cached, drop-in replacement for the native `norgatedata` library.

---

## 🛠️ Feature Overview

- **Official Function Signature**:
  ```python
  norgatedata.unadjusted_close_timeseries(
      symbol, 
      timeseriesformat="numpy-recarray",
      start_date=None,
      end_date=None,
      key_by_assetid=False
  )
  ```
- **Return Formats**: Controlled via `timeseriesformat` (either `str` or `TimeSeriesFormat` enum):
  - `"pandas-dataframe"`: `pd.DataFrame` containing either a `Date` or `AssetID` index, and a single column `"Close"`.
  - `"numpy-recarray"` (Default): `numpy.recarray` structured records containing fields (e.g. `Date` and `Close`).
  - `"numpy-ndarray"`: A raw `numpy.ndarray` containing close prices.
- **Caching Mechanism**: **Fully Cached**. Leverages the proxy's unified SQLite tracking db (`cache_metadata` table) and Snappy-compressed Parquet disk cache engine. This ensures sub-millisecond local reads, automatic LRU cache size evictions, and smart trailing range delta syncing.

---

## 📐 Detailed Component Changes

### 1. 🖥️ Proxy Server (`ngd_proxy/server.py`)

We will add EOD price simulation generators and `/unadjusted_close_timeseries` FastAPI routing support:

- **Mock EOD Close Generator**:
  ```python
  def generate_mock_unadjusted_close(
      symbol: str, 
      start_date: str = "2020-01-01", 
      end_date: Optional[str] = None
  ) -> pd.DataFrame:
      """Generates simulated EOD close timeseries using the standard mock random walk."""
      df = generate_mock_price_timeseries(symbol, start_date, end_date)
      return df[["Close"]]
  ```
- **FastAPI Route Definition**:
  - **Endpoint**: `/unadjusted_close_timeseries`
  - **HTTP Method**: `GET`
  - **Mock Mode Handling (`MOCK_MODE = True`)**:
    - Translate integer IDs to tickers (e.g., `1001` -> `TSLA`, `1002` -> `MSFT`, `2001` -> `&FDAX`, `2002` -> `&ES`).
    - Validate ticker strictly: support only `TSLA`, `MSFT`, `&FDAX` / `FDAX`, `&ES` / `ES`. Unsupported tickers must raise a standard `404` exception.
    - Extract and return only the `"Close"` column of the generated random walk.
    - Use `serialize_dataframe()` to respect `Accept: application/x-parquet` or fallback to JSON.
  - **Real Mode Handling (`MOCK_MODE = False`)**:
    - Resolve the symbol/ID to native format using `resolve_symbol()`.
    - Fetch from the native library:
      ```python
      df = norgatedata.unadjusted_close_timeseries(
          resolved_symbol, 
          timeseriesformat="pandas-dataframe",
          start_date=start_date,
          end_date=end_date
      )
      ```
    - Check if the returned DataFrame is empty, format its index, and stream the serialized parquet/JSON data.

---

### 2. 📡 Proxy Client (`ngd_proxy/client.py`)

We will define an elegant HTTP client consumer method leveraging the robust `self._request_dataframe` utility:

```python
    def unadjusted_close_timeseries(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        key_by_assetid: bool = False
    ) -> pd.DataFrame:
        """
        Fetches historical EOD unadjusted close timeseries from the proxy host.
        """
        params = {
            "symbol": symbol,
            "key_by_assetid": key_by_assetid
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
            
        return self._request_dataframe("/unadjusted_close_timeseries", params)
```

---

### 3. 💾 Cache Manager (`ngd_proxy/norgatedata_cache.py`)

We will introduce a dynamic output format casting utility and the caching interceptor logic:

- **Format Conversion Layer**:
  ```python
      def _convert_format(self, df: pd.DataFrame, format_setting: Union[str, TimeSeriesFormat]):
          """Converts the internal Pandas DataFrame to the requested native user return format."""
          # Standardize format name to string
          fmt = format_setting.value if isinstance(format_setting, TimeSeriesFormat) else str(format_setting).lower()
          
          if fmt == "pandas-dataframe":
              return df
          elif fmt == "numpy-recarray":
              return df.to_records(index=True)
          elif fmt == "numpy-ndarray":
              return df.to_numpy()
          else:
              raise ValueError(f"Unsupported timeseries format: {format_setting}")
  ```
- **Caching Wrapper Method**:
  ```python
      def unadjusted_close_timeseries(
          self,
          symbol: str,
          timeseriesformat: Union[str, TimeSeriesFormat] = TimeSeriesFormat.NUMPY_RECARRAY,
          start_date: Optional[str] = None,
          end_date: Optional[str] = None,
          key_by_assetid: bool = False
      ):
          """Exposes SQLite-tracked and Parquet-cached historical unadjusted close prices."""
          if not self.cache_enabled:
              df = self.client.unadjusted_close_timeseries(symbol, start_date, end_date, key_by_assetid)
              return self._convert_format(df, timeseriesformat)
              
          # Form cache-matching param string
          param = "UNADJUSTED"
          if key_by_assetid:
              param += "_ASSETID"
              
          # Lambda fetch delegate
          fetch_func = lambda s_date, e_date: self.client.unadjusted_close_timeseries(
              symbol=symbol,
              start_date=s_date,
              end_date=e_date,
              key_by_assetid=key_by_assetid
          )
          
          df_cached = self._get_timeseries("unadjusted_close", symbol, param, start_date, end_date, fetch_func)
          return self._convert_format(df_cached, timeseriesformat)
  ```

---

### 📦 4. Package Export (`ngd_proxy/__init__.py`)

We will expose the dynamic EOD query utility at the top-level package namespace:

```python
def unadjusted_close_timeseries(
    symbol: str,
    timeseriesformat: Union[str, TimeSeriesFormat] = TimeSeriesFormat.NUMPY_RECARRAY,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    key_by_assetid: bool = False
):
    """
    Returns unadjusted close EOD timeseries.
    Matches the official norgatedata.unadjusted_close_timeseries signature.
    """
    if isinstance(timeseriesformat, TimeSeriesFormat):
        timeseriesformat = timeseriesformat.value
    return _get_cache().unadjusted_close_timeseries(
        symbol=symbol,
        timeseriesformat=timeseriesformat,
        start_date=start_date,
        end_date=end_date,
        key_by_assetid=key_by_assetid
    )
```
- Register `unadjusted_close_timeseries` in `__all__` to make it fully discoverable.

---

## 🧪 Verification & Testing Plan

### Automated Integration Tests (`tests/test_cache.py`)

We will add a thorough integration test case, **`test_17_unadjusted_close_timeseries_caching_and_formats`**, verifying:
1. **Cache Miss**: Fetching a symbol from the server writes metadata to SQLite (`datatype='unadjusted_close'`) and generates a snappy Parquet file on disk (e.g. `unadjusted_close_TSLA_UNADJUSTED.parquet`).
2. **Cache Hit**: Subsequent queries for the same range retrieve the cached EOD series instantaneously without calling the server.
3. **Format Conversions**: Verify `numpy-recarray` returns a `numpy.recarray` with index records, `numpy-ndarray` returns price arrays, and `pandas-dataframe` returns a standard `pd.DataFrame`.
4. **Range Stitching**: Requesting extra days verifies smart trailing delta sync.
5. **Continuous Futures Spec**: Verifies query success for continous contracts (e.g. `&FDAX`).
6. **Mock Validation**: Attempting to query invalid symbols (e.g., `AAPL`) raises a proper HTTP client error in Mock Mode.

### Manual Verification (`test__unadjusted_close.ipynb`)

 We will create a clean Jupyter notebook, `test__unadjusted_close.ipynb` containing `"metadata": {}` blocks on every cell, to allow interactive verification and visualization of the return types across different symbols and contracts.
