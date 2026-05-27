# Implementation Plan: Caching historical `major_exchange_listed_timeseries`

This implementation plan outlines the architectural additions, route definitions, caching protocols, and format conversions required to implement the historical listing timeseries function **`major_exchange_listed_timeseries`** as a fully cached, drop-in replacement for the native `norgatedata` library.

---

## 🛠️ Feature Overview

- **Official Function Signature**:
  ```python
  norgatedata.major_exchange_listed_timeseries(
      symbol, 
      timeseriesformat="numpy-recarray",
      start_date=None,
      end_date=None
  )
  ```
- **Return Value**: An indicator series specifying whether a stock traded on a major US exchange vs OTC:
  - `1`: Listed on a major US exchange (NYSE, Nasdaq, NYSE American, etc.).
  - `0`: Trading on an OTC/Pink Sheet market.
- **Return Formats**: Configurable via `timeseriesformat`:
  - `"pandas-dataframe"`: `pd.DataFrame` containing a `Date` index and a single column `"MajorExchangeListed"`.
  - `"numpy-recarray"` (Default): `numpy.recarray` structured records containing fields (e.g. `Date` and `MajorExchangeListed`).
  - `"numpy-ndarray"`: A raw `numpy.ndarray` containing listing status.
- **Caching Mechanism**: **Fully Cached**. Leverages the proxy's unified SQLite tracking db (`cache_metadata` table) and Snappy-compressed Parquet disk cache engine. This ensures sub-millisecond local reads, automatic LRU cache size evictions, and smart trailing range delta syncing.

---

## 📐 Detailed Component Changes

### 1. 🖥️ Proxy Server (`ngd_proxy/server.py`)

We will add mock EOD listing indicator generators and `/major_exchange_listed_timeseries` FastAPI routing support:

- **Mock EOD Listing Status Generator**:
  ```python
  def generate_mock_major_exchange_listed(
      symbol: str, 
      start_date: str = "2020-01-01", 
      end_date: Optional[str] = None
  ) -> pd.DataFrame:
      """Generates simulated EOD listing status timeseries (all 1s for major stocks TSLA/MSFT)."""
      if not end_date:
          end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
      dates = pd.bdate_range(start=start_date, end=end_date)
      n = len(dates)
      if n == 0:
          return pd.DataFrame(columns=["MajorExchangeListed"])
          
      # Since MSFT and TSLA are major companies, return all 1s indicating major exchange listing
      status_vals = np.ones(n, dtype=int)
      df = pd.DataFrame({"MajorExchangeListed": status_vals}, index=dates)
      df.index.name = "Date"
      return df
  ```
- **FastAPI Route Definition**:
  - **Endpoint**: `/major_exchange_listed_timeseries`
  - **HTTP Method**: `GET`
  - **Mock Mode Handling (`MOCK_MODE = True`)**:
    - Translate integer IDs to tickers (e.g. `1001` -> `TSLA`, `1002` -> `MSFT`).
    - Validate ticker strictly: support only `TSLA` and `MSFT`. Continuous futures and other tickers must raise a standard `404` exception.
    - Generate mock data using `generate_mock_major_exchange_listed()`.
    - Stream serialized parquet/JSON data using `serialize_dataframe()`.
  - **Real Mode Handling (`MOCK_MODE = False`)**:
    - Resolve the symbol/ID to native format using `resolve_symbol()`.
    - Fetch from the native library:
      ```python
      df = norgatedata.major_exchange_listed_timeseries(
          resolved_symbol, 
          timeseriesformat="pandas-dataframe",
          start_date=start_date,
          end_date=end_date
      )
      ```
    - Verify data presence, set column name to `"MajorExchangeListed"` if single-column, and serialize.

---

### 2. 📡 Proxy Client (`ngd_proxy/client.py`)

We will define a lightweight HTTP client method leveraging the existing `self._request_dataframe` utility:

```python
    def major_exchange_listed_timeseries(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Fetches historical EOD major exchange listed timeseries from the proxy host.
        """
        params = {"symbol": symbol}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
            
        return self._request_dataframe("/major_exchange_listed_timeseries", params)
```

---

### 3. 💾 Cache Manager (`ngd_proxy/norgatedata_cache.py`)

We will implement the cache wrapper method backed by the standard Parquet cacher and casting logic:

```python
    def major_exchange_listed_timeseries(
        self,
        symbol: str,
        timeseriesformat: Any = "numpy-recarray",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ):
        """Exposes SQLite-tracked and Parquet-cached major exchange listing status history."""
        if not self.cache_enabled:
            df = self.client.major_exchange_listed_timeseries(symbol, start_date, end_date)
            return self._convert_format(df, timeseriesformat)
            
        # Lambda fetch delegate
        fetch_func = lambda start_date, end_date: self.client.major_exchange_listed_timeseries(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date
        )
        
        df_cached = self._get_timeseries(
            "major_exchange_listed", 
            symbol, 
            "MAJOR_EXCHANGE_LISTED", 
            start_date, 
            end_date, 
            fetch_func
        )
        return self._convert_format(df_cached, timeseriesformat)
```

---

### 📦 4. Package Export (`ngd_proxy/__init__.py`)

We will expose the listing timeseries convenience function at the top-level package namespace:

```python
def major_exchange_listed_timeseries(
    symbol: str,
    timeseriesformat: Union[str, TimeSeriesFormat] = TimeSeriesFormat.NUMPY_RECARRAY,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Returns major exchange listing status timeseries.
    Matches the official norgatedata.major_exchange_listed_timeseries signature.
    """
    if isinstance(timeseriesformat, TimeSeriesFormat):
        timeseriesformat = timeseriesformat.value
    return _get_cache().major_exchange_listed_timeseries(
        symbol=symbol,
        timeseriesformat=timeseriesformat,
        start_date=start_date,
        end_date=end_date
    )
```
- Register `major_exchange_listed_timeseries` in `__all__` to make it discoverable.

---

## 🧪 Verification & Testing Plan

### Automated Integration Tests (`tests/test_cache.py`)

We will add a dedicated integration test case, **`test_18_major_exchange_listed_timeseries_caching_and_formats`**, verifying:
1. **Cache Miss**: Querying a symbol writes tracking records to SQLite (`datatype='major_exchange_listed'`) and writes Parquet cache files.
2. **Cache Hit**: Subsequent queries read from local Parquet storage instantaneously.
3. **Format Conversions**: Validates outputs are correctly cast to standard NumPy record arrays, raw values arrays, or Pandas DataFrames.
4. **Mock Strictness**: Asserting invalid symbols (e.g. `AAPL` or continuous contracts `&FDAX`) raise a proper HTTP client error in Mock Mode.

### Manual Verification (`test__major_exchange_listed.ipynb`)

We will create a schema-compliant Jupyter notebook, `test__major_exchange_listed.ipynb` demonstrating the usage of `major_exchange_listed_timeseries` across all standard formats and verifying the caching metrics.
