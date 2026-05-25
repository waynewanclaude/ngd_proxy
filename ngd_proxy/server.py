import os
import sys
import argparse
import time
from typing import Optional, List
from io import BytesIO

import pandas as pd
import numpy as np
import psutil
from fastapi import FastAPI, Depends, HTTPException, Header, Query, status
from fastapi.responses import StreamingResponse, JSONResponse

# Initialize FastAPI App
app = FastAPI(
    title="Norgate Data Proxy Server",
    description="A high-performance HTTP & Parquet proxy for Norgate Data",
    version="1.0.0"
)

# Global variables for mode and library
MOCK_MODE = False
norgatedata = None
API_KEY = "norgate-secure-default-key-replace-me"  # Default fallback, should be changed or set via environment

# Setup command-line argument parsing
parser = argparse.ArgumentParser(description="Run the Norgate Data Proxy Server.")
parser.add_argument("--mock", action="store_true", help="Force mock mode even if norgatedata is available")
parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")
parser.add_argument("--host", type=str, default="127.0.0.1", help="Host IP to bind the server to")
parser.add_argument("--api-key", type=str, help="API Key for secure access")

# Parse arguments safely in Uvicorn / script context
if "uvicorn" in sys.argv[0] or any(arg.startswith("--") for arg in sys.argv):
    try:
        args, unknown = parser.parse_known_args()
        if args.mock:
            MOCK_MODE = True
        if args.api_key:
            API_KEY = args.api_key
    except Exception:
        # Gracefully handle parsing errors if run under test runner
        pass

# Attempt to load norgatedata library
if not MOCK_MODE:
    try:
        import norgatedata
        print("[INFO] Successfully imported native 'norgatedata' library.")
    except ImportError:
        print("[WARNING] Could not import native 'norgatedata' library. Falling back to MOCK MODE.")
        MOCK_MODE = True

# --- API Key Authentication Dependency ---
def verify_api_key(x_api_key: Optional[str] = Header(None)):
    # Read API Key from environment or defaults
    expected_key = os.getenv("NORGATEDATA_API_KEY", API_KEY)
    if not expected_key:
        return  # Security is disabled if API key is explicitly empty
    if x_api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header"
        )

# --- Helper: Serialize DataFrame based on Accept Header ---
def serialize_dataframe(df: pd.DataFrame, accept_header: Optional[str]) -> StreamingResponse:
    """
    Serializes a Pandas DataFrame into Parquet if requested, otherwise returns standard JSON.
    """
    if accept_header == "application/x-parquet":
        buffer = BytesIO()
        df.to_parquet(buffer, engine="pyarrow", compression="snappy", index=True)
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/x-parquet",
            headers={"Content-Disposition": "attachment; filename=timeseries.parquet"}
        )
    else:
        # Reset index if date index to preserve date in JSON output
        if isinstance(df.index, pd.DatetimeIndex):
            df_json = df.reset_index()
            # Convert timestamp to ISO format string
            df_json[df_json.index.name or 'Date'] = df_json[df_json.index.name or 'Date'].dt.strftime('%Y-%m-%d')
        else:
            df_json = df
        
        return JSONResponse(content=df_json.to_dict(orient="records"))

# --- Mock Data Generator ---
def generate_mock_price_timeseries(
    symbol: str, 
    start_date: str = "2020-01-01", 
    end_date: Optional[str] = None
) -> pd.DataFrame:
    """
    Generates realistic looking EOD price timeseries using random walks.
    """
    if not end_date:
        end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
        
    dates = pd.bdate_range(start=start_date, end=end_date)
    n = len(dates)
    if n == 0:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    
    # Generate random prices
    np.random.seed(abs(hash(symbol)) % 2**32)
    returns = np.random.normal(0.0005, 0.015, n)  # slight upward bias
    price_factor = np.exp(np.cumsum(returns))
    
    # Base price derived from ticker name
    base_price = max(10.0, float(sum(ord(c) for c in symbol)) / 5.0)
    close_prices = base_price * price_factor
    
    opens = close_prices * (1.0 + np.random.normal(0, 0.005, n))
    highs = np.maximum(opens, close_prices) * (1.0 + np.abs(np.random.normal(0, 0.005, n)))
    lows = np.minimum(opens, close_prices) * (1.0 - np.abs(np.random.normal(0, 0.005, n)))
    volumes = np.random.randint(100000, 5000000, n).astype(float)
    
    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": close_prices,
        "Volume": volumes
    }, index=dates)
    df.index.name = "Date"
    return df

def generate_mock_constituent_timeseries(
    symbol: str,
    indexname: str,
    start_date: str = "2020-01-01",
    end_date: Optional[str] = None
) -> pd.DataFrame:
    """
    Generates simulated index constituent boolean (1/0) series.
    """
    if not end_date:
        end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
    dates = pd.bdate_range(start=start_date, end=end_date)
    n = len(dates)
    if n == 0:
        return pd.DataFrame(columns=["is_constituent"])
    
    # Simulate membership based on symbol hash: some are always in, some never, some transition
    np.random.seed(abs(hash(symbol + indexname)) % 2**32)
    mode = np.random.choice([0, 1, 2]) # 0=Never, 1=Always, 2=Transitions
    
    if mode == 0:
        membership = np.zeros(n, dtype=int)
    elif mode == 1:
        membership = np.ones(n, dtype=int)
    else:
        # Transition halfway
        midpoint = n // 2
        initial = np.random.choice([0, 1])
        membership = np.empty(n, dtype=int)
        membership[:midpoint] = initial
        membership[midpoint:] = 1 - initial
        
    df = pd.DataFrame({"is_constituent": membership}, index=dates)
    df.index.name = "Date"
    return df

def generate_mock_dividend_timeseries(
    symbol: str,
    start_date: str = "2020-01-01",
    end_date: Optional[str] = None
) -> pd.DataFrame:
    """
    Generates simulated dividend yield timeseries (mostly 0 with occasional dividend spikes).
    """
    if not end_date:
        end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
    dates = pd.bdate_range(start=start_date, end=end_date)
    n = len(dates)
    if n == 0:
        return pd.DataFrame(columns=["dividend_yield"])
    
    yields = np.zeros(n, dtype=float)
    # Give it a dividend quarterly (approx every 60 business days)
    np.random.seed(abs(hash(symbol)) % 2**32)
    div_value = np.random.uniform(0.01, 0.03)
    for i in range(15, n, 60):
        yields[i] = div_value
        
    df = pd.DataFrame({"dividend_yield": yields}, index=dates)
    df.index.name = "Date"
    return df

# --- API Endpoints ---

@app.get("/status", dependencies=[Depends(verify_api_key)])
def get_status():
    """
    Check server status, NDU connectivity, and resource usage.
    """
    ndu_connected = True
    if not MOCK_MODE:
        try:
            # Try a quick call to check if NDU is running/accessible
            # In Norgate, norgatedata.watchlists() is a quick, light metadata query
            norgatedata.watchlists()
        except Exception:
            ndu_connected = False

    return {
        "status": "ok",
        "mode": "mock" if MOCK_MODE else "real",
        "ndu_connected": ndu_connected,
        "system": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "uptime_seconds": time.time() - psutil.boot_time()
        }
    }

@app.get("/price_timeseries", dependencies=[Depends(verify_api_key)])
def get_price_timeseries(
    symbol: str,
    adjustment: str = "TOTALRETURN",
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    key_by_assetid: bool = False,
    accept: Optional[str] = Header(None)
):
    """
    Fetch price timeseries for a security.
    Supports JSON or binary Parquet streaming via Accept header.
    """
    if MOCK_MODE:
        df = generate_mock_price_timeseries(
            symbol=symbol,
            start_date=start_date or "2020-01-01",
            end_date=end_date
        )
        return serialize_dataframe(df, accept)
    
    # Real Mode using norgatedata
    adj_setting = None
    try:
        # Map adjustment string/int to norgatedata adjustment settings
        adj_setting = norgatedata.StockPriceAdjustmentType.TOTALRETURN
        if str(adjustment).upper() in ("CAPITAL", "2"):
            adj_setting = norgatedata.StockPriceAdjustmentType.CAPITAL
        elif str(adjustment).upper() in ("NONE", "0"):
            adj_setting = norgatedata.StockPriceAdjustmentType.NONE

        # Resolve target symbol or assetid
        target = symbol
        if key_by_assetid:
            try:
                target = int(symbol)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid Asset ID: {symbol}. Must be an integer.")

        df = norgatedata.price_timeseries(
            target,
            stock_price_adjustment_setting=adj_setting,
            start_date=start_date,
            end_date=end_date,
            timeseriesformat="pandas-dataframe"
        )
        
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"No price data found for symbol {symbol}")
            
        df.index.name = "Date"
        return serialize_dataframe(df, accept)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Norgate API Error: {str(e)}")

@app.get("/index_constituent_timeseries", dependencies=[Depends(verify_api_key)])
def get_index_constituent_timeseries(
    symbol: str,
    indexname: str,
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    accept: Optional[str] = Header(None)
):
    """
    Fetch index constituent timeseries.
    """
    if MOCK_MODE:
        df = generate_mock_constituent_timeseries(
            symbol=symbol,
            indexname=indexname,
            start_date=start_date or "2020-01-01",
            end_date=end_date
        )
        return serialize_dataframe(df, accept)

    try:
        df = norgatedata.index_constituent_timeseries(
            symbol,
            indexname,
            start_date=start_date,
            end_date=end_date,
            timeseriesformat="pandas-dataframe"
        )
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"No constituent data found for symbol {symbol} and index {indexname}")
            
        df.index.name = "Date"
        # Make sure columns are named consistently
        if len(df.columns) == 1:
            df.columns = ["is_constituent"]
            
        return serialize_dataframe(df, accept)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Norgate API Error: {str(e)}")

@app.get("/dividend_yield_timeseries", dependencies=[Depends(verify_api_key)])
def get_dividend_yield_timeseries(
    symbol: str,
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    accept: Optional[str] = Header(None)
):
    """
    Fetch dividend yield timeseries.
    """
    if MOCK_MODE:
        df = generate_mock_dividend_timeseries(
            symbol=symbol,
            start_date=start_date or "2020-01-01",
            end_date=end_date
        )
        return serialize_dataframe(df, accept)

    try:
        df = norgatedata.dividend_yield_timeseries(
            symbol,
            start_date=start_date,
            end_date=end_date,
            timeseriesformat="pandas-dataframe"
        )
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"No dividend data found for symbol {symbol}")
            
        df.index.name = "Date"
        if len(df.columns) == 1:
            df.columns = ["dividend_yield"]
            
        return serialize_dataframe(df, accept)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Norgate API Error: {str(e)}")

@app.get("/watchlists", dependencies=[Depends(verify_api_key)])
def get_watchlists():
    """
    Retrieve all available watchlist names.
    """
    if MOCK_MODE:
        return ["S&P 500", "Nasdaq 100", "Dow Jones Industrial Average", "ASX 200"]
        
    try:
        return norgatedata.watchlists()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Norgate API Error: {str(e)}")

@app.get("/watchlist/symbols", dependencies=[Depends(verify_api_key)])
def get_watchlist_symbols(watchlistname: str):
    """
    Retrieve just the symbols in a watchlist.
    """
    if MOCK_MODE:
        if watchlistname == "S&P 500":
            return ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META"]
        return ["AAPL", "MSFT", "GOOGL"]
        
    try:
        symbols = norgatedata.watchlist_symbols(watchlistname)
        if symbols is None:
            raise HTTPException(status_code=404, detail=f"Watchlist {watchlistname} not found")
        return symbols
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Norgate API Error: {str(e)}")

@app.get("/watchlist/details", dependencies=[Depends(verify_api_key)])
def get_watchlist_details(watchlistname: str):
    """
    Retrieve security details of a watchlist (assetid, symbol, name).
    """
    if MOCK_MODE:
        return [
            {"assetid": 1001, "symbol": "AAPL", "name": "Apple Inc."},
            {"assetid": 1002, "symbol": "MSFT", "name": "Microsoft Corporation"},
            {"assetid": 1003, "symbol": "GOOGL", "name": "Alphabet Inc."},
        ]
        
    try:
        details = norgatedata.watchlist(watchlistname)
        if details is None:
            raise HTTPException(status_code=404, detail=f"Watchlist {watchlistname} not found")
        
        # details is usually a list of tuples or dicts, standardise to list of dicts
        formatted = []
        for item in details:
            # Handle tuple format (assetid, symbol, name)
            if isinstance(item, tuple) and len(item) >= 3:
                formatted.append({
                    "assetid": item[0],
                    "symbol": item[1],
                    "name": item[2]
                })
            elif isinstance(item, dict):
                formatted.append({
                    "assetid": item.get("assetid") or item.get("AssetId"),
                    "symbol": item.get("symbol") or item.get("Symbol"),
                    "name": item.get("name") or item.get("Name")
                })
        return formatted
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Norgate API Error: {str(e)}")

# Add entry point to run via python server.py directly or CLI command
def main():
    import uvicorn
    host_ip = "127.0.0.1"
    port_num = 8000
    
    try:
        args, unknown = parser.parse_known_args()
        host_ip = args.host or host_ip
        port_num = args.port or port_num
    except Exception:
        pass
        
    uvicorn.run("ngd_proxy.server:app", host=host_ip, port=port_num)

if __name__ == "__main__":
    main()
