"""Backtest engine: next-bar execution, slippage/commission, honest metrics.

Signals are computed on bar close but executed at the *next* bar's open —
trading on the same bar a signal fires is look-ahead bias and inflates
results. This engine enforces that by shifting the signal series by one bar
before it ever touches an execution price.
"""

import math
import numpy as np
import pandas as pd

import data
import db
import strategies

INITIAL_CAPITAL = 10_000.0
DEFAULT_COMMISSION_PCT = 0.0
DEFAULT_SLIPPAGE_PCT = 0.0005  # 0.05% per side


def _simulate(df: pd.DataFrame, commission_pct: float, slippage_pct: float) -> dict:
    """Walk the bars once, executing exec_signal[i] (= signal[i-1]) at Open[i].

    Returns per-bar equity series and a list of closed trades.
    """
    exec_signal = df["signal"].shift(1).fillna(0)

    cash = INITIAL_CAPITAL
    shares = 0.0
    entry_price = None
    entry_date = None
    position = False

    equity_values = []
    trades = []

    for i, ts in enumerate(df.index):
        sig = exec_signal.iloc[i]
        open_px = df["Open"].iloc[i]

        if sig == 1 and not position:
            buy_price = open_px * (1 + slippage_pct)
            commission = cash * commission_pct
            investable = cash - commission
            shares = investable / buy_price
            cash = 0.0
            position = True
            entry_price = buy_price
            entry_date = ts

        elif sig == -1 and position:
            sell_price = open_px * (1 - slippage_pct)
            proceeds = shares * sell_price
            commission = proceeds * commission_pct
            cash = proceeds - commission
            trade_return_pct = (sell_price / entry_price - 1) * 100
            duration_days = (ts - entry_date).days
            trades.append(
                {
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "exit_date": ts.strftime("%Y-%m-%d"),
                    "entry_price": round(float(entry_price), 4),
                    "exit_price": round(float(sell_price), 4),
                    "return_pct": round(float(trade_return_pct), 4),
                    "duration_days": duration_days,
                }
            )
            shares = 0.0
            position = False
            entry_price = None
            entry_date = None

        mark = cash if not position else shares * df["Close"].iloc[i]
        equity_values.append(mark)

    equity = pd.Series(equity_values, index=df.index, name="equity")

    if position:
        # Mark the still-open position as an unrealized trade for reporting,
        # but don't force-close it — the equity curve already reflects it.
        last_price = df["Close"].iloc[-1]
        trade_return_pct = (last_price / entry_price - 1) * 100
        duration_days = (df.index[-1] - entry_date).days
        trades.append(
            {
                "entry_date": entry_date.strftime("%Y-%m-%d"),
                "exit_date": None,
                "entry_price": round(float(entry_price), 4),
                "exit_price": None,
                "return_pct": round(float(trade_return_pct), 4),
                "duration_days": duration_days,
                "open": True,
            }
        )

    return {"equity": equity, "trades": trades}


def _max_drawdown_pct(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    return float(drawdown.min() * 100)


def _sharpe_ratio(equity: pd.Series) -> float:
    daily_returns = equity.pct_change().dropna()
    if daily_returns.empty or daily_returns.std() == 0:
        return 0.0
    return float((daily_returns.mean() / daily_returns.std()) * math.sqrt(252))


def _win_rate_pct(trades: list) -> float:
    closed = [t for t in trades if t.get("exit_date") is not None]
    if not closed:
        return 0.0
    wins = sum(1 for t in closed if t["return_pct"] > 0)
    return round(wins / len(closed) * 100, 2)


def _avg_trade_duration(trades: list) -> float:
    closed = [t for t in trades if t.get("exit_date") is not None]
    if not closed:
        return 0.0
    return round(sum(t["duration_days"] for t in closed) / len(closed), 2)


def _benchmark_return_pct(df: pd.DataFrame, start_idx: int = 0, end_idx: int = -1) -> float:
    first_open = df["Open"].iloc[start_idx]
    last_close = df["Close"].iloc[end_idx]
    return float((last_close / first_open - 1) * 100)


def _segment_metrics(df: pd.DataFrame, equity: pd.Series, trades: list, start_idx: int, end_idx: int) -> dict:
    seg_equity = equity.iloc[start_idx : end_idx + 1]
    seg_start_val = seg_equity.iloc[0]
    seg_return_pct = float((seg_equity.iloc[-1] / seg_start_val - 1) * 100) if seg_start_val else 0.0

    seg_start_date = df.index[start_idx]
    seg_end_date = df.index[end_idx]
    seg_trades = [
        t
        for t in trades
        if seg_start_date.strftime("%Y-%m-%d") <= t["entry_date"] <= seg_end_date.strftime("%Y-%m-%d")
    ]

    return {
        "start_date": seg_start_date.strftime("%Y-%m-%d"),
        "end_date": seg_end_date.strftime("%Y-%m-%d"),
        "return_pct": round(seg_return_pct, 2),
        "benchmark_return_pct": round(_benchmark_return_pct(df, start_idx, end_idx), 2),
        "win_rate": _win_rate_pct(seg_trades),
        "max_dd": round(_max_drawdown_pct(seg_equity), 2),
        "sharpe": round(_sharpe_ratio(seg_equity), 2),
        "num_trades": len([t for t in seg_trades if t.get("exit_date") is not None]),
        "avg_trade_duration": _avg_trade_duration(seg_trades),
    }


def _indicator_series(sig_df: pd.DataFrame) -> dict:
    candidates = ["sma_fast", "sma_slow", "rsi", "sma", "roc"]
    out = {}
    for col in candidates:
        if col not in sig_df.columns:
            continue
        series = sig_df[col]
        points = [
            {"time": ts.strftime("%Y-%m-%d"), "value": round(float(v), 4)}
            for ts, v in series.items()
            if pd.notna(v)
        ]
        out[col] = points
    return out


def run_backtest(
    ticker: str,
    start_date: str,
    end_date: str,
    strategy_name: str,
    params: dict | None = None,
    commission_pct: float = DEFAULT_COMMISSION_PCT,
    slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
    train_test_split: bool = False,
    save: bool = True,
) -> dict:
    df = data.fetch_price_data(ticker, start_date, end_date)
    if len(df) < 30:
        raise data.DataError(
            f"Only {len(df)} trading days in range — need at least 30 for indicators to warm up."
        )

    strategy = strategies.get_strategy(strategy_name)
    sig_df = strategy.generate_signals(df, params)

    sim = _simulate(sig_df, commission_pct, slippage_pct)
    equity, trades = sim["equity"], sim["trades"]

    full_metrics = {
        "return_pct": round(float(equity.iloc[-1] / INITIAL_CAPITAL - 1) * 100, 2),
        "benchmark_return_pct": round(_benchmark_return_pct(df), 2),
        "win_rate": _win_rate_pct(trades),
        "max_dd": round(_max_drawdown_pct(equity), 2),
        "sharpe": round(_sharpe_ratio(equity), 2),
        "num_trades": len([t for t in trades if t.get("exit_date") is not None]),
        "avg_trade_duration": _avg_trade_duration(trades),
    }

    split_result = None
    cutoff_date = None
    if train_test_split and len(df) >= 50:
        cutoff_idx = int(len(df) * 0.8)
        cutoff_date = df.index[cutoff_idx].strftime("%Y-%m-%d")
        train_metrics = _segment_metrics(df, equity, trades, 0, cutoff_idx - 1)
        test_metrics = _segment_metrics(df, equity, trades, cutoff_idx, len(df) - 1)
        split_result = {"train": train_metrics, "test": test_metrics}

    benchmark_curve = (df["Close"] / df["Open"].iloc[0]) * 100
    equity_curve_pct = (equity / INITIAL_CAPITAL) * 100
    equity_curve = [
        {
            "time": ts.strftime("%Y-%m-%d"),
            "strategy": round(float(s), 4),
            "benchmark": round(float(b), 4),
        }
        for ts, s, b in zip(df.index, equity_curve_pct, benchmark_curve)
    ]

    ohlc = [
        {
            "time": ts.strftime("%Y-%m-%d"),
            "open": round(float(o), 4),
            "high": round(float(h), 4),
            "low": round(float(l), 4),
            "close": round(float(c), 4),
        }
        for ts, o, h, l, c in zip(df.index, df["Open"], df["High"], df["Low"], df["Close"])
    ]

    chart_data = {
        "ohlc": ohlc,
        "indicators": _indicator_series(sig_df),
        "trades": trades,
        "equity_curve": equity_curve,
        "train_test_cutoff": cutoff_date,
        "split": split_result,
    }

    resolved_params = {**strategy.DEFAULT_PARAMS, **(params or {})}
    result = {
        "ticker": ticker.strip().upper(),
        "strategy": strategy_name,
        "params": resolved_params,
        "start_date": start_date,
        "end_date": end_date,
        "commission_pct": commission_pct,
        "slippage_pct": slippage_pct,
        "train_test_split": train_test_split,
        "chart_data": chart_data,
        **full_metrics,
    }

    if save:
        result["id"] = db.save_backtest(result)

    return result
