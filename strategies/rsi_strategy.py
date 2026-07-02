"""RSI: buy when RSI crosses back above 30 (exiting oversold),
sell when RSI crosses back below 70 (exiting overbought).

Uses crossings rather than raw levels so the signal fires once per
event instead of every bar spent oversold/overbought.
"""

from .base import rsi

NAME = "rsi"
LABEL = "RSI (14)"
DEFAULT_PARAMS = {"period": 14, "oversold": 30, "overbought": 70}


def generate_signals(df, params=None):
    params = {**DEFAULT_PARAMS, **(params or {})}
    period = int(params["period"])
    oversold = float(params["oversold"])
    overbought = float(params["overbought"])

    df = df.copy()
    df["rsi"] = rsi(df["Close"], period)

    r, prev_r = df["rsi"], df["rsi"].shift(1)

    cross_up_from_oversold = (prev_r < oversold) & (r >= oversold)
    cross_down_from_overbought = (prev_r > overbought) & (r <= overbought)

    df["signal"] = 0
    df.loc[cross_up_from_oversold.fillna(False), "signal"] = 1
    df.loc[cross_down_from_overbought.fillna(False), "signal"] = -1

    df.loc[df["rsi"].isna(), "signal"] = 0

    return df
