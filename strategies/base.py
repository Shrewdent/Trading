"""Shared interface for all strategies.

Every strategy module exposes:
  - NAME: str
  - DEFAULT_PARAMS: dict
  - generate_signals(df, params) -> df with an added 'signal' column

Signal values are events, not states:
  1  = enter long (computed from this bar's close)
 -1  = exit long (computed from this bar's close)
  0  = no action

The backtest engine is responsible for executing signal=1/-1 at the *next*
bar's open (never the bar the signal fired on) to avoid look-ahead bias.
"""

import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    out = 100 - (100 / (1 + rs))
    out = out.fillna(100)
    return out


def rate_of_change(series: pd.Series, period: int) -> pd.Series:
    return (series / series.shift(period) - 1) * 100


def crossing_events(condition: pd.Series) -> pd.Series:
    """Turn a boolean 'in condition' series into 1 (entering) / -1 (leaving) / 0 events."""
    prev = condition.shift(1).fillna(False)
    enter = condition & (~prev)
    exit_ = (~condition) & prev
    signal = pd.Series(0, index=condition.index)
    signal[enter] = 1
    signal[exit_] = -1
    return signal
