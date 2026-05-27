import os
from enum import IntEnum, Enum
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
import pandas as pd


from .client import NorgateDataClient
from .norgatedata_cache import NorgateDataCache

class StockPriceAdjustmentType(IntEnum):
    NONE = 0
    CAPITAL = 1
    CAPITALSPECIAL = 2
    TOTALRETURN = 3

class PaddingType(IntEnum):
    NONE = 0
    ALLMARKETDAYS = 1
    ALLWEEKDAYS = 2
    ALLCALENDARDAYS = 3

class TimeSeriesFormat(Enum):
    PANDAS_DATAFRAME = 'pandas-dataframe'
    NUMPY_RECARRAY = 'numpy-recarray'
    NUMPY_NDARRAY = 'numpy-ndarray'

# Global cache instance management
_global_cache: Optional[NorgateDataCache] = None

def _get_cache() -> NorgateDataCache:
    global _global_cache
    if _global_cache is None:
        # Load from default config.json if it exists in the current directory or nearby
        config_path = "config.json"
        if not os.path.exists(config_path) and os.path.exists("../config.json"):
            config_path = "../config.json"
        _global_cache = NorgateDataCache(config_path=config_path)
    return _global_cache

def price_timeseries(
    symbol: str,
    stock_price_adjustment_setting: Union[str, int, StockPriceAdjustmentType] = StockPriceAdjustmentType.TOTALRETURN,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    key_by_assetid: bool = False
) -> pd.DataFrame:
    # Convert Enum to integer/string value if passed as Enum
    if isinstance(stock_price_adjustment_setting, StockPriceAdjustmentType):
        stock_price_adjustment_setting = stock_price_adjustment_setting.name
    return _get_cache().price_timeseries(
        symbol=symbol,
        stock_price_adjustment_setting=stock_price_adjustment_setting,
        start_date=start_date,
        end_date=end_date,
        key_by_assetid=key_by_assetid
    )

def index_constituent_timeseries(
    symbol: str,
    indexname: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> pd.DataFrame:
    return _get_cache().index_constituent_timeseries(
        symbol=symbol,
        indexname=indexname,
        start_date=start_date,
        end_date=end_date
    )

def dividend_yield_timeseries(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> pd.DataFrame:
    return _get_cache().dividend_yield_timeseries(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date
    )

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

def watchlists() -> List[str]:
    return _get_cache().watchlists()

def watchlist_symbols(watchlistname: str) -> List[str]:
    return _get_cache().watchlist_symbols(watchlistname)

def watchlist_details(watchlistname: str) -> List[Dict[str, Any]]:
    return _get_cache().watchlist_details(watchlistname)

def watchlist(watchlistname: str) -> List[Dict[str, Any]]:
    return _get_cache().watchlist(watchlistname)

def security_name(symbol: str) -> Optional[str]:
    return _get_cache().security_name(symbol)

def fundamental(symbol: str, fieldname: str, datetimeformat: str = 'iso') -> tuple:
    return _get_cache().fundamental(symbol, fieldname, datetimeformat)

def exchange_name(symbol: str) -> Optional[str]:
    return _get_cache().exchange_name(symbol)

def exchange_name_full(symbol: str) -> Optional[str]:
    return _get_cache().exchange_name_full(symbol)

def last_database_update_time(database: str) -> Optional[datetime]:
    return _get_cache().last_database_update_time(database)

def last_price_update_time(symbol: str) -> Optional[datetime]:
    return _get_cache().last_price_update_time(symbol)

def assetid(symbol: str) -> Optional[int]:
    return _get_cache().assetid(symbol)

def base_type(symbol: str) -> Optional[str]:
    return _get_cache().base_type(symbol)

def classification(symbol: str, schemename: str, classificationresulttype: str = "Name", level: Optional[int] = None) -> Optional[str]:
    return _get_cache().classification(symbol, schemename, classificationresulttype, level)


def corresponding_industry_index(symbol: str, indexfamilycode: str, level: int, indexreturntype: str) -> Optional[str]:
    return _get_cache().corresponding_industry_index(symbol, indexfamilycode, level, indexreturntype)

def subtype1(symbol: str) -> Optional[str]:
    return _get_cache().subtype1(symbol)

def subtype2(symbol: str) -> Optional[str]:
    return _get_cache().subtype2(symbol)

def subtype3(symbol: str) -> Optional[str]:
    return _get_cache().subtype3(symbol)

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

__all__ = [
    "NorgateDataClient",
    "NorgateDataCache",
    "StockPriceAdjustmentType",
    "PaddingType",
    "TimeSeriesFormat",
    "price_timeseries",
    "index_constituent_timeseries",
    "dividend_yield_timeseries",
    "unadjusted_close_timeseries",
    "major_exchange_listed_timeseries",
    "capital_event_timeseries",
    "watchlists",
    "watchlist_symbols",
    "watchlist_details",
    "watchlist",
    "security_name",
    "fundamental",
    "exchange_name",
    "exchange_name_full",
    "last_database_update_time",
    "last_price_update_time",
    "assetid",
    "base_type",
    "classification",
    "corresponding_industry_index",
    "subtype1",
    "subtype2",
    "subtype3",
    "margin",
    "point_value",
    "tick_value",
    "lowest_ever_tick_size",
    "futures_market_session_info"
]




