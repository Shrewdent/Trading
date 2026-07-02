"""Momentum: buy if close > SMA(20) and 10-day rate of change > 0; sell otherwise.

Entries/exits fire on the bar the condition changes state, not on every bar
the condition holds.
"""

from .base import sma, rate_of_change, crossing_events

NAME = "momentum"
LABEL = "Momentum"
DEFAULT_PARAMS = {"sma_period": 20, "roc_period": 10}


def generate_signals(df, params=None):
    params = {**DEFAULT_PARAMS, **(params or {})}
    sma_period = int(params["sma_period"])
    roc_period = int(params["roc_period"])

    df = df.copy()
    df["sma"] = sma(df["Close"], sma_period)
    df["roc"] = rate_of_change(df["Close"], roc_period)

    condition = (df["Close"] > df["sma"]) & (df["roc"] > 0)
    condition = condition.where(df["sma"].notna() & df["roc"].notna(), other=False)

    df["signal"] = crossing_events(condition)
    df.loc[df["sma"].isna() | df["roc"].isna(), "signal"] = 0

    return df
