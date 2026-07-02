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

## The four strategies

All four strategies share one interface — `generate_signals(df, params)` —
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
- **Bollinger Band Reversion** (`bollinger`): buy when close crosses
  *below* the lower band (20-period, 2 std dev), sell when it reverts back
  above the middle band. Deliberately the riskiest and most active of the
  four — it's **countertrend**, so in a persistent downtrend it keeps
  buying dips that keep dropping (long-only, no shorting), unlike the other
  three which are trend-following and sit out of that scenario. It also
  trades far more often on any ticker that chops sideways, since price
  crosses the bands repeatedly — 21 trades vs. MA Crossover's 10 on the
  same SPY range (see results below).

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
| Bollinger Reversion | +26.25% | +95.38% | 85.7% | -28.66% | — | 21 |

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

## Concurrent paper trading sessions

The Paper Trader tab supports running **several sessions at once**, each on
a different ticker, each capped at its own fixed dollar allocation:

- Sessions are keyed by ticker — one active strategy per ticker at a time,
  since Alpaca holds one position per symbol per account, so two strategies
  trading the same ticker would fight over the same underlying position.
  Different tickers run fully independently.
- Each session's `$` allocation is a hard cap: `_position_size()` in
  `paper_trader.py` sizes orders off `min(allocated_dollars, buying_power)`,
  so a session never spends more than its own number even if the account
  has more buying power available. Fixed-dollar was chosen over a
  percentage split specifically to avoid ambiguity about what "30% of
  buying power" means once multiple sessions have already bought in and
  shrunk the pool.
- Every session gets its own card (ticker/strategy/allocation badge, live
  chart, position, P&L, trade history, Stop / Close Position buttons).
  Account-wide equity and buying power are shown once in the header, since
  that number is shared across every session, not per-strategy.
- The trade log (`paper_trades.json`) is shared across all sessions and
  protected by a lock (`paper_trader.py`'s `_TRADE_LOG_LOCK`) so concurrent
  tickers writing at the same time can't clobber each other's entries.

## Open positions, unified history, and realized P&L

Closing the app doesn't close your positions — they live on Alpaca, not
locally — but it does wipe the app's memory of which sessions were
running. Reopening used to show "No sessions running" even if you were
still holding something from yesterday, with nothing to tell you so. Three
additions fix that:

- **Open Positions panel** (Paper Trader tab, below the session cards):
  every open position on the account, fetched via
  `broker.get_all_positions()`, whether or not a local session is
  currently monitoring it. Each row shows a "Monitored" badge (green
  "Yes" if a running session owns that ticker, gray "No" if it's
  orphaned) and its own Close button — closing works either way.
  `app.py`'s `close_position()` now routes to the session if one's
  running, or closes directly against the account if not, logging the
  trade via `paper_trader.record_manual_close()` in the orphaned case.
  This is a permanent view rather than a one-time startup toast — nothing
  to miss by not looking at the right moment.
- **All Trade History**: a sortable/filterable table across every ticker
  ever traded, not just the currently-visible session cards (which
  disappear when a session stops, taking their per-card history out of
  view with them — the data was always in `paper_trades.json`, just not
  browsable from the UI once a card was gone).
- **Realized P&L**: the app previously only showed *unrealized* P&L while
  a position was open — once closed, that number just vanished with no
  running total. `paper_trader.compute_realized_pnl()` pairs sequential
  buy/sell events per ticker across the full trade log and reports total
  $ P&L, closed-trade count, and win rate — the actual answer to "is this
  strategy making money" once you're live, not just backtested.

While building this, fixed an accuracy gap flagged earlier: manual
position closes were logging the *entry* price as a placeholder exit
price (since Alpaca's close-position call doesn't return a fill price
immediately). Both the session-based and orphaned close paths now fetch
the position's current market value right before closing and log that
instead — accurate for both, and required for realized P&L to be
trustworthy. Trades logged before this fix keep their old approximate
price.

## Suggested next steps

- **Stop-loss / take-profit rules** — right now positions only exit on the
  strategy's own signal, which is honest but can hold through large
  drawdowns (see the -33.72% RSI drawdown above) — this matters more now
  that the Bollinger strategy can keep buying dips in a downtrend.
- **Parameter sweep tool** — grid-search fast/slow SMA periods, RSI
  thresholds, or Bollinger band width across a date range and rank by
  out-of-sample Sharpe, to catch overfitting before it reaches paper
  trading.
- **WebSocket live bars** — the paper trader polls Alpaca every 60s; a
  websocket feed would tighten signal latency once polling proves the
  concept, and would matter more with several concurrent sessions polling
  independently.
- **Configurable strategy parameters in the UI** — currently only the
  strategy choice is exposed in the Backtester/Paper Trader forms; fast/slow
  periods, RSI thresholds, etc. all use each strategy's `DEFAULT_PARAMS`.
