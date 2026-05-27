# Implementation Plan: Caching historical `capital_event_timeseries`

This implementation plan outlines the architectural additions, route definitions, caching protocols, and format conversions required to implement the historical capital events timeseries function **`capital_event_timeseries`** as a fully cached, drop-in replacement for the native `norgatedata` library.

---

## 🛠️ Feature Overview

- **Official Function Signature**:
  ```python
  norgatedata.capital_event_timeseries(
      symbol, 
      timeseriesformat="numpy-recarray",
      start_date=None,
      end_date=None
  )
  ```
- **Return Value**: An EOD timeseries indicating the occurrence of corporate actions (splits, reverse splits, stock dividends, complex reorganizations):
  - `1`: A capital event occurred on the ex-date.
  - `0`: No capital event occurred.
- **Return Formats**: Configurable via `timeseriesformat`:
  - `"pandas-dataframe"`: `pd.DataFrame` containing a `Date` index and a single column `"Capital Event"`.
  - `"numpy-recarray"` (Default): `numpy.recarray` structured records containing fields (e.g. `Date` and `Capital Event`).
  - `"numpy-ndarray"`: A raw `numpy.ndarray` containing capital event indicators.
- **Caching Mechanism**: **Fully Cached**. Leverages the proxy's unified SQLite tracking db (`cache_metadata` table) and Snappy-compressed Parquet disk cache engine. This ensures sub-millisecond local reads, automatic LRU cache size evictions, and smart trailing range delta syncing.

---

## 📐 Detailed Component Changes

### 1. 🖥️ Proxy Server (`ngd_proxy/server.py`)

We will add mock EOD capital event generators and `/capital_event_timeseries` FastAPI routing support:

- **Mock EOD Capital Event Generator**:
  ```python
  def generate_mock_capital_event(
      symbol: str, 
      start_date: str = "2020-01-01", 
      end_date: Optional[str] = None
  ) -> pd.DataFrame:
      """Generates simulated EOD capital event timeseries (mostly 0s, with approx yearly ex-dates)."""
      if not end_date:
          end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
      dates = pd.bdate_range(start=start_date, end=end_date)
      n = len(dates)
      if n == 0:
          return pd.DataFrame(columns=["Capital Event"])
          
      events = np.zeros(n, dtype=int)
      # Simulate a stock split/event once every 250 business days (approx yearly)
      np.random.seed(abs(hash(symbol)) % 2**32)
      for i in range(120, n, 250):
          events[i] = 1
          
      df = pd.DataFrame({"Capital Event": events}, index=dates)
      df.index.name = "Date"
      return df
  ```
- **FastAPI Route Definition**:
  - **Endpoint**: `/capital_event_timeseries`
  - **HTTP Method**: `GET`
  - **Mock Mode Handling (`MOCK_MODE = True`)**:
    - Translate integer IDs to tickers (e.g. `1001` -> `TSLA`, `1002` -> `MSFT`).
    - Validate ticker strictly: support only `TSLA` and `MSFT`. Continuous futures and other tickers must raise a standard `404` exception.
    - Generate mock data using `generate_mock_capital_event()`.
    - Stream serialized parquet/JSON data using `serialize_dataframe()`.
  - **Real Mode Handling (`MOCK_MODE = False`)**:
    - Resolve the symbol/ID to native format using `resolve_symbol()`.
    - Fetch from the native library:
      ```python
      df = norgatedata.capital_event_timeseries(
          resolved_symbol, 
          timeseriesformat="pandas-dataframe",
          start_date=start_date,
          end_date=end_date
      )
      ```
    - Verify data presence, force single column to be `"Capital Event"` if not named, and serialize.

---

### 2. 📡 Proxy Client (`ngd_proxy/client.py`)

We will define a lightweight HTTP client method leveraging the existing `self._request_dataframe` utility:

```python
    def capital_event_timeseries(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Fetches historical EOD capital event timeseries from the proxy host.
        """
        params = {"symbol": symbol}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
            
        return self._request_dataframe("/capital_event_timeseries", params)
```

---

### 3. 💾 Cache Manager (`ngd_proxy/norgatedata_cache.py`)

We will implement the cache wrapper method backed by the standard Parquet cacher and casting logic:

```python
    def capital_event_timeseries(
        self,
        symbol: str,
        timeseriesformat: Any = "numpy-recarray",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ):
        """Exposes SQLite-tracked and Parquet-cached historical capital event status."""
        if not self.cache_enabled:
            df = self.client.capital_event_timeseries(symbol, start_date, end_date)
            return self._convert_format(df, timeseriesformat)
            
        # Lambda fetch delegate
        fetch_func = lambda start_date, end_date: self.client.capital_event_timeseries(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date
        )
        
        df_cached = self._get_timeseries(
            "capital_event", 
            symbol, 
            "CAPITAL_EVENT", 
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
def capital_event_timeseries(
    symbol: str,
    timeseriesformat: Union[str, TimeSeriesFormat] = TimeSeriesFormat.NUMPY_RECARRAY,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Returns capital event timeseries indicating split/corporate ex-dates.
    Matches the official norgatedata.capital_event_timeseries signature.
    """
    if isinstance(timeseriesformat, TimeSeriesFormat):
        timeseriesformat = timeseriesformat.value
    return _get_cache().capital_event_timeseries(
        symbol=symbol,
        timeseriesformat=timeseriesformat,
        start_date=start_date,
        end_date=end_date
    )
```
- Register `capital_event_timeseries` in `__all__` to make it discoverable.

---

## 🧪 Verification & Testing Plan

### Automated Integration Tests (`tests/test_cache.py`)

We will add a dedicated integration test case, **`test_19_capital_event_timeseries_caching_and_formats`**, verifying:
1. **Cache Miss**: Querying a symbol writes tracking records to SQLite (`datatype='capital_event'`) and writes Parquet cache files.
2. **Cache Hit**: Subsequent queries read from local Parquet storage instantenously.
3. **Format Conversions**: Validates outputs are correctly cast to standard NumPy record arrays, raw values arrays, or Pandas DataFrames.
4. **Mock Strictness**: Asserting invalid symbols (e.g. `AAPL` or continuous contracts `&FDAX`) raise a proper HTTP client error in Mock Mode.

### Manual Verification (`test__capital_event.ipynb`)

We will create a schema-compliant Jupyter notebook, `test__capital_event.ipynb` demonstrating the usage of `capital_event_timeseries` across all standard formats and verifying the caching metrics.
