"""Historical daily price data: fetch via yfinance, cache locally as parquet.

Only re-downloads when the cached range doesn't cover the requested range —
yfinance rate-limits aggressively, so avoiding redundant calls matters.
"""

import os
import datetime as dt

import pandas as pd
import yfinance as yf

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)


class DataError(Exception):
    """Raised when a ticker can't be resolved or has no data for the range."""


def _cache_path(ticker: str) -> str:
    safe = ticker.strip().upper().replace("/", "_")
    return os.path.join(DATA_DIR, f"{safe}.parquet")


def _load_cache(ticker: str) -> pd.DataFrame | None:
    path = _cache_path(ticker)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_parquet(path)
        df.index = pd.to_datetime(df.index)
        return df
    except Exception:
        return None


def _save_cache(ticker: str, df: pd.DataFrame) -> None:
    df.to_parquet(_cache_path(ticker))


def _download(ticker: str, start: str, end: str) -> pd.DataFrame:
    # yfinance's `end` is exclusive; pad by a day so the requested end date is included.
    end_padded = (pd.to_datetime(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    raw = yf.download(
        ticker,
        start=start,
        end=end_padded,
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    if raw is None or raw.empty:
        raise DataError(
            f"No data returned for '{ticker}'. Check the ticker symbol and date range."
        )
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    raw.index.name = "Date"
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    return raw.dropna(how="all")


def fetch_price_data(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Return OHLCV daily bars for [start_date, end_date], using/refreshing the cache."""
    ticker = ticker.strip().upper()
    if not ticker:
        raise DataError("Ticker is required.")

    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    if start_ts >= end_ts:
        raise DataError("Start date must be before end date.")

    today = pd.Timestamp(dt.date.today())
    if end_ts > today:
        end_ts = today

    cached = _load_cache(ticker)
    needs_fetch = True
    fetch_start, fetch_end = start_date, end_ts.strftime("%Y-%m-%d")

    if cached is not None and not cached.empty:
        cached_start, cached_end = cached.index.min(), cached.index.max()
        # Cache covers the request if it starts on/before and ends on/after
        # (allowing a couple of days' slack at the end for weekends/holidays).
        if cached_start <= start_ts and cached_end >= end_ts - pd.Timedelta(days=4):
            needs_fetch = False

    if needs_fetch:
        # Fetch a superset: earliest of (cached start, requested start) through today,
        # so the cache only grows and future requests hit it more often.
        merged_start = start_date
        if cached is not None and not cached.empty:
            merged_start = min(cached.index.min(), start_ts).strftime("%Y-%m-%d")
        fresh = _download(ticker, merged_start, today.strftime("%Y-%m-%d"))
        if cached is not None and not cached.empty:
            combined = pd.concat([cached, fresh])
            combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        else:
            combined = fresh
        _save_cache(ticker, combined)
        cached = combined

    result = cached.loc[(cached.index >= start_ts) & (cached.index <= end_ts)].copy()
    if result.empty:
        raise DataError(
            f"No trading data for '{ticker}' between {start_date} and {end_date}."
        )
    return result


def validate_ticker(ticker: str) -> bool:
    try:
        end = dt.date.today()
        start = end - dt.timedelta(days=14)
        fetch_price_data(ticker, start.isoformat(), end.isoformat())
        return True
    except DataError:
        return False
