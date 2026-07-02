# Backtesting & Paper Trading Platform — Build Spec

Build a local backtesting and paper trading platform using Python, yfinance, pandas, and Alpaca's free paper trading API.

## Goal

Create a working desktop app to test a trading strategy on historical data (5+ years) and then paper trade it live with zero real money. Design it to answer: "Does this strategy actually work before I risk capital?"

## Build order (important)

Build in two phases. **Phase 1 (Backtester + Results History) must be fully working and verified before starting Phase 2 (Paper Trader).** The backtester is useful standalone and doesn't require any API keys, so it can be tested immediately.

## Tech requirements

- Python backend with yfinance for historical daily data, pandas for OHLC manipulation and strategy logic.
- Alpaca API free tier (`paper=True`) for paper trading — no real money. Use the official `alpaca-py` SDK.
- PyWebView for the frontend (same pattern as Sideload: `app.py` + `gui/index.html`).
- HTML/CSS/JavaScript for the UI — responsive, dark theme.
- **Charts rendered in JavaScript inside the webview** using TradingView's `lightweight-charts` library (or Plotly.js as fallback). Do NOT use matplotlib — static image charts are clunky in pywebview. The Python backend returns OHLC + indicator + trade-marker data as JSON; the frontend renders it.
- SQLite for backtest results; JSON for the paper trade log and app config.
- No cloud dependencies; everything runs locally. Alpaca keys stored in a git-ignored `config.json` (add `.gitignore` with `config.json` and `*.db` from the start). Ship a `config.example.json` with placeholder keys.
- Paper trader loop runs in a **background worker thread** (same pattern as Sideload's download queue) so the UI never freezes. Provide a clean stop flag.

## Data source realities (design around these)

- yfinance daily bars: fine for 5+ year backtests. Cache downloaded data locally (e.g., `data/{ticker}.parquet` or SQLite) and only re-fetch when the cached range doesn't cover the request — yfinance rate-limits aggressively.
- yfinance intraday data is limited (roughly 7–60 days depending on interval) — do NOT use it for the paper trader.
- Paper trader uses **Alpaca's own market data** (free IEX feed) for live bars. Poll latest bars on an interval (e.g., every 60s for minute bars) rather than websockets for v1 — simpler and good enough.
- Handle market-closed hours gracefully: show "Market closed" status instead of erroring.

## Core features

### Backtester

- Load historical daily price data for any ticker (user inputs ticker + date range; validate the ticker exists and the range has data).
- Implement three strategies (each in its own module with a shared interface: `generate_signals(df) -> df with 'signal' column`):
  - **Moving average crossover**: Fast SMA (20) crosses above slow SMA (50) = BUY; crosses below = SELL.
  - **RSI**: Buy when RSI(14) crosses back above 30 (exiting oversold), sell when RSI crosses back below 70 (exiting overbought). Use crossings, not levels, to avoid firing every bar while oversold/overbought.
  - **Momentum**: Buy if close > SMA(20) and 10-day rate of change > 0; sell otherwise.
- **Execution rules (critical for honest results):**
  - Signals are computed on bar close; trades execute at the **next bar's open**. Never trade on the same bar the signal was generated — that's look-ahead bias and inflates results.
  - Long-only, one position at a time, position size = 100% of current equity (configurable fixed-dollar option later).
  - Apply commission (default $0 — modern brokers are commission-free, but keep it configurable) **and slippage** (default 0.05% per side). Slippage matters more than commission and is what makes results believable.
- Calculate and display:
  - Total return (%), **buy-and-hold return (%) for the same ticker/period as a benchmark**, win rate (%), max drawdown (%), annualized Sharpe ratio (daily returns × √252, risk-free rate 0 for v1), number of trades, and average trade duration.
  - The benchmark comparison is non-negotiable: a strategy that returns +40% when buy-and-hold returned +90% is a losing strategy, and the UI should make that obvious (e.g., "vs Buy & Hold: −50%" in red).
- **Train/test split option**: checkbox to reserve the final 20% of the date range as out-of-sample data, showing metrics for both segments side by side. A strategy that only works in-sample is overfit.
- Chart: candlesticks with MA lines overlaid, RSI in a subplot when relevant, and trade markers (green triangle = entry, red triangle = exit). Equity curve vs buy-and-hold curve below the price chart.
- Save every backtest run to SQLite with timestamp, strategy, ticker, date range, parameters, and all metrics.
- Compare multiple saved backtests side-by-side in a table.

### Paper Trader (Phase 2)

- Connect to Alpaca with `paper=True`. On startup, verify the connection and show a clear error toast if keys are missing/invalid (reuse the `friendly_error` pattern from Sideload).
- Select a strategy and ticker; run the same strategy module on live minute or hourly bars from Alpaca.
- Dashboard:
  - Current position (long/flat), entry price, unrealized P&L.
  - Trade history (all fills since app started, persisted to JSON so it survives restarts).
  - Account balance and buying power, refreshed every 30s.
  - Live chart with current signal state and recent trades marked.
  - Status line: market open/closed, last data update time, strategy running/stopped.
- Toast notification when a signal fires.
- Start/Stop buttons; stopping must cleanly kill the worker thread. Stopping does NOT liquidate the position automatically — show a separate "Close position" button.

## Controls & navigation

- Left sidebar tabs: **Backtester**, **Paper Trader**, **Results History**.
- Backtester tab: ticker, start date, end date, strategy dropdown, train/test split checkbox, "Run Backtest" button. Results table + chart below. Show a spinner while data downloads.
- Paper Trader tab: strategy + ticker dropdowns, Start/Stop, dashboard.
- Results tab: sortable/filterable table of past backtests (date, ticker, strategy, return vs benchmark). Click a row to re-view its chart and metrics. Delete button per row.

## Visual design

- Dark theme, green accents for profit, red for loss (matching the Ledger aesthetic).
- Header with app name and (Phase 2) paper account summary.
- Collapsible left sidebar (~60px collapsed).
- Sortable tables with alternating row colors; status badges ("Strategy: RSI", "Ticker: AAPL", "Live: Yes/No"); loading spinners and error toasts on all API/data calls.

## Data & state

- SQLite `backtests` table: id, ticker, strategy, params (JSON), start_date, end_date, return_pct, benchmark_return_pct, win_rate, max_dd, sharpe, num_trades, chart_data (JSON), created_at.
- Paper trade log JSON: `[{ timestamp, ticker, signal, price, side, qty, status }, …]`.
- Cached price data in `data/` (git-ignored).
- App config (theme, last-used settings, Alpaca keys) in `config.json` (git-ignored).

## Implementation expectations

- Build the complete working app, not a shell.
- Modular code: `strategies/` (one file per strategy + shared base), `data.py` (fetch + cache), `backtest.py` (engine + metrics), `broker.py` (Alpaca connector), `app.py` (pywebview API bridge), `gui/` (HTML/CSS/JS).
- Backtester must fetch real data and generate honest metrics (next-bar execution, slippage, benchmark).
- Charts render in the webview without errors.
- Start in the Backtester tab; no landing page.
- README with setup instructions: pip install, how to get free Alpaca paper keys, `config.example.json` → `config.json`, run command.

## Verification

1. Run the app with NO Alpaca keys configured — Backtester and Results tabs must work fully; Paper Trader tab shows a friendly "add your keys" message instead of crashing.
2. Backtest SPY, MA crossover, last 5 years. Verify: return and benchmark both display, win rate is plausible (roughly 30–60% for a crossover system), max drawdown is nonzero, trade markers align with visible crossovers on the chart.
3. Re-run the same backtest — data loads from cache (fast, no re-download).
4. Run with train/test split enabled and see both metric sets.
5. Add Alpaca paper keys, start the Paper Trader on a different ticker. Verify balance and buying power display, status updates on the polling interval, and the UI stays responsive.
6. Stop trading and close the app without errors or orphaned threads.

## Deliverable

- Complete Python + HTML/CSS/JS project running under PyWebView.
- README covering setup and the three strategies.
- Short summary of results from the SPY verification backtest and suggested next steps (position sizing options, stop-loss/take-profit rules, more strategies, parameter sweep tool).

## Quality bar

The backtester must produce **honest** results — next-bar execution, slippage, and a buy-and-hold benchmark are what separate a learning tool from a fantasy generator. It should be easy to see when a strategy loses to buy-and-hold, because most will, and that's the insight the app exists to deliver. Paper trading must feel live and responsive. Avoid overengineering; smooth UX over perfect financial modeling.
