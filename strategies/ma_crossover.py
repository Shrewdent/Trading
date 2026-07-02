"""Moving average crossover: fast SMA crosses above slow SMA = BUY, below = SELL."""

from .base import sma

NAME = "ma_crossover"
LABEL = "Moving Average Crossover"
DEFAULT_PARAMS = {"fast_period": 20, "slow_period": 50}


def generate_signals(df, params=None):
    params = {**DEFAULT_PARAMS, **(params or {})}
    fast_period = int(params["fast_period"])
    slow_period = int(params["slow_period"])

    df = df.copy()
    df["sma_fast"] = sma(df["Close"], fast_period)
    df["sma_slow"] = sma(df["Close"], slow_period)

    fast, slow = df["sma_fast"], df["sma_slow"]
    prev_fast, prev_slow = fast.shift(1), slow.shift(1)

    cross_up = (prev_fast <= prev_slow) & (fast > slow)
    cross_down = (prev_fast >= prev_slow) & (fast < slow)

    df["signal"] = 0
    df.loc[cross_up.fillna(False), "signal"] = 1
    df.loc[cross_down.fillna(False), "signal"] = -1

    df.loc[fast.isna() | slow.isna(), "signal"] = 0

    return df
