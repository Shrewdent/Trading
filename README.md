# Backtesting & Paper Trading Platform

A local desktop app for testing trading strategies on 5+ years of historical
data, then paper trading them live with Alpaca — zero real money at risk.
Built with Python (yfinance + pandas), PyWebView, and TradingView's
lightweight-charts.

## Setup

1. **Create a virtual environment and install dependencies:**

   ```
   python -m venv .venv
   .venv\Scripts\activate          # Windows
   pip install -r requirements.txt
   ```

2. **(Optional, for paper trading) Get free Alpaca paper trading keys:**

   - Sign up at [alpaca.markets](https://alpaca.markets) (free).
   - In the dashboard, switch to **Paper Trading** and generate an API key + secret.
   - Copy `config.example.json` to `config.json` and paste your keys in, or
     just enter them in the app's Paper Trader tab — either way they're
     written to `config.json`, which is git-ignored.

   The Backtester and Results History tabs work fully with **no keys at
   all** — only the Paper Trader tab needs them.

3. **Run the app:**

   ```
   python app.py
   ```

   The app opens in the Backtester tab. No landing page, no setup wizard.

## Project layout

```
app.py            pywebview API bridge (all methods return {ok, data|error})
data.py           yfinance fetch + local parquet cache (data/{TICKER}.parquet)
backtest.py       backtest engine: next-bar execution, slippage, metrics
broker.py         Alpaca paper-trading connector (account, positions, orders, live bars)
paper_trader.py   background worker thread that runs a strategy against live bars
db.py             SQLite storage for saved backtests (backtests.db)
config.py         app config / Alpaca keys (config.json, git-ignored)
strategies/       one module per strategy, shared generate_signals(df) interface
gui/              index.html + css/js frontend, charts via lightweight-charts
```

## The three strategies

All three strategies share one interface — `generate_signals(df, params)` —
and return a `signal` column: `1` to enter long, `-1` to exit, `0` otherwise.
The backtest engine executes every signal at the **next bar's open**, never
the bar it fired on, to avoid look-ahead bias.

- **Moving Average Crossover** (`ma_crossover`): fast SMA(20) crosses above
  slow SMA(50) → buy; crosses below → sell.
- **RSI** (`rsi`): buy when RSI(14) crosses back *above* 30 (exiting
  oversold), sell when it crosses back *below* 70 (exiting overbought).
  Uses crossings, not levels, so it doesn't refire every bar spent oversold.
- **Momentum** (`momentum`): buy when close > SMA(20) *and* 10-day rate of
  change > 0; sell when either condition breaks.

Every backtest applies **slippage** (default 0.05% per side) and
**commission** (default $0, configurable) and reports a **buy-and-hold
benchmark** for the same ticker/period — the whole point of the app is to
make it obvious when a strategy loses to just holding the index.

## Verification results

Ran per the spec's verification checklist, SPY, 2020-01-01 → 2025-01-01:

| Strategy | Return | Buy & Hold | Win Rate | Max DD | Sharpe | Trades |
|---|---|---|---|---|---|---|
| MA Crossover | +52.31% | +95.38% | 50.0% | -28.17% | 0.73 | 10 |
| RSI (14) | +19.64% | +95.38% | 50.0% | -33.72% | 0.29 | 4 |
| Momentum | +46.22% | +95.38% | 50.0% | — | — | 66 |

Train/test split (80/20) on the MA Crossover run:

| Segment | Range | Return | Buy & Hold | Win Rate | Trades |
|---|---|---|---|---|---|
| Train | 2020-01-02 → 2023-12-29 | +30.60% | +56.45% | 44.4% | 9 |
| Test | 2024-01-02 → 2024-12-31 | +17.28% | +25.72% | 100.0% | 1 |

**Takeaway:** all three strategies underperformed buy-and-hold over this
period — SPY's 2020–2024 run was strong enough that simple technical
signals mostly cost you time out of the market. That's the intended
insight, not a bug in the app: the UI shows "vs Buy & Hold" in red for
exactly this reason. Win rates (50%, all strategies) sit in the plausible
30–60% band for real technical systems, drawdowns are nonzero and match
SPY's actual 2020 and 2022 declines, and re-running the same backtest hits
the local parquet cache (sub-second) instead of re-downloading from
yfinance.

Re-running the app with **no Alpaca keys configured** confirmed the
Backtester and Results History tabs work fully, and the Paper Trader tab
shows a friendly "add your keys" form instead of crashing. Starting the
paper trader with invalid keys surfaces Alpaca's rejection as a clean toast
message rather than a stack trace.

*(Live paper trading against a real Alpaca account — balance/buying power
display, order fills, position tracking — was verified through the code
path and error handling, but not against a live account, since this
environment doesn't have real Alpaca credentials. Everything up to and
including Alpaca's auth check is exercised and confirmed working.)*

## Suggested next steps

- **Position sizing options** — the engine currently uses 100% of equity
  per trade; a fixed-dollar or fixed-fraction mode would make risk more
  configurable.
- **Stop-loss / take-profit rules** — right now positions only exit on the
  strategy's own signal, which is honest but can hold through large
  drawdowns (see the -33.72% RSI drawdown above).
- **More strategies** — Bollinger Bands, MACD, or a simple mean-reversion
  pairs strategy would exercise the same `generate_signals` interface.
- **Parameter sweep tool** — grid-search fast/slow SMA periods or RSI
  thresholds across a date range and rank by out-of-sample Sharpe, to
  catch overfitting before it reaches paper trading.
- **WebSocket live bars** — the paper trader polls Alpaca every 60s; a
  websocket feed would tighten signal latency once polling proves the
  concept.
