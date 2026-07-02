"""Bollinger Band mean-reversion: buy when price closes below the lower
band (oversold dip), sell when it reverts back above the middle band.

Deliberately riskier than the trend-following strategies: it's countertrend,
so in a persistent downtrend it keeps buying dips that keep dropping
(long-only, no shorting). It also trades far more often than MA Crossover
or RSI on any ticker that chops sideways, since price crosses the bands
repeatedly.
"""

from .base import sma

NAME = "bollinger"
LABEL = "Bollinger Band Reversion"
DEFAULT_PARAMS = {"period": 20, "num_std": 2.0}


def generate_signals(df, params=None):
    params = {**DEFAULT_PARAMS, **(params or {})}
    period = int(params["period"])
    num_std = float(params["num_std"])

    df = df.copy()
    middle = sma(df["Close"], period)
    std = df["Close"].rolling(window=period, min_periods=period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std

    df["bb_middle"] = middle
    df["bb_upper"] = upper
    df["bb_lower"] = lower

    close = df["Close"]
    prev_close = close.shift(1)
    prev_lower = lower.shift(1)
    prev_middle = middle.shift(1)

    cross_below_lower = (prev_close >= prev_lower) & (close < lower)
    cross_above_middle = (prev_close <= prev_middle) & (close > middle)

    df["signal"] = 0
    df.loc[cross_below_lower.fillna(False), "signal"] = 1
    df.loc[cross_above_middle.fillna(False), "signal"] = -1

    df.loc[middle.isna() | upper.isna() | lower.isna(), "signal"] = 0

    return df
