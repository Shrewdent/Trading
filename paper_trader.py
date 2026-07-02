"""Background worker that runs a strategy against live Alpaca bars and
places paper orders. Mirrors Sideload's download-queue pattern: one
daemon thread, a stop flag, and a status snapshot the UI polls.
"""

import datetime as dt
import json
import os
import threading
import time

import pandas as pd

import broker as broker_module
import strategies

TRADE_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trades.json")
_TRADE_LOG_LOCK = threading.Lock()

ACCOUNT_REFRESH_SECONDS = 30
BAR_POLL_SECONDS = 60
TICK_SECONDS = 5


def load_all_trades() -> list:
    if os.path.exists(TRADE_LOG_PATH):
        try:
            with open(TRADE_LOG_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _append_trade(entry: dict) -> None:
    """Read-modify-write under a lock so concurrent sessions (different
    tickers, different threads) never clobber each other's log entries."""
    with _TRADE_LOG_LOCK:
        all_trades = load_all_trades()
        all_trades.append(entry)
        with open(TRADE_LOG_PATH, "w") as f:
            json.dump(all_trades, f, indent=2)


def record_manual_close(ticker: str, price: float, qty: float, status: str) -> None:
    """Logs a manual close for a ticker with no active PaperTrader session
    (an orphaned position closed from the Open Positions panel)."""
    entry = {
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "ticker": ticker,
        "signal": "manual_close",
        "price": round(float(price), 4) if price else None,
        "side": "sell",
        "qty": qty,
        "status": status,
    }
    _append_trade(entry)


def compute_realized_pnl(trades: list) -> dict:
    """Pairs sequential buy/sell events per ticker across the whole trade
    log and sums up completed round-trips. Trades logged before the exit-
    price accuracy fix may understate/overstate individual trades, but the
    pairing logic itself is unaffected."""
    by_ticker: dict[str, list] = {}
    for t in trades:
        by_ticker.setdefault(t["ticker"], []).append(t)

    closed = []
    for ticker_trades in by_ticker.values():
        open_trade = None
        for t in ticker_trades:
            if t["side"] == "buy":
                open_trade = t
            elif t["side"] == "sell" and open_trade and t.get("price") and open_trade.get("price"):
                qty = t.get("qty") or 0
                pnl_pct = (t["price"] / open_trade["price"] - 1) * 100
                pnl_dollars = (t["price"] - open_trade["price"]) * qty
                closed.append({"pnl_pct": pnl_pct, "pnl_dollars": pnl_dollars})
                open_trade = None

    total_pnl_dollars = sum(c["pnl_dollars"] for c in closed)
    wins = sum(1 for c in closed if c["pnl_pct"] > 0)
    win_rate = (wins / len(closed) * 100) if closed else 0.0

    return {
        "total_pnl_dollars": round(total_pnl_dollars, 2),
        "num_closed_trades": len(closed),
        "win_rate": round(win_rate, 2),
    }


class PaperTrader:
    def __init__(self, api_key: str, secret_key: str):
        self.broker = broker_module.AlpacaBroker(api_key, secret_key)

        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._lock = threading.Lock()

        self.ticker = None
        self.strategy_name = None
        self.allocated_dollars = None
        self.running = False
        self.market_open = False
        self.position = "flat"
        self.entry_price = None
        self.unrealized_pl = None
        self.equity = None
        self.buying_power = None
        self.last_update = None
        self.chart_data = None
        self.notifications = []
        self.trade_history = []

        self._last_bar_check = 0.0
        self._last_account_check = 0.0

    # ---------- trade log persistence ----------

    def _record_trade(self, signal, side, price, qty=0, status="filled"):
        entry = {
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "ticker": self.ticker,
            "signal": signal,
            "price": round(float(price), 4),
            "side": side,
            "qty": qty,
            "status": status,
        }
        _append_trade(entry)
        self.trade_history.append(entry)

    def _push_notification(self, message, level="info"):
        with self._lock:
            self.notifications.append({"message": message, "level": level})

    # ---------- lifecycle ----------

    def start(self, ticker: str, strategy_name: str, allocated_dollars: float):
        if self.running:
            raise ValueError("Paper trading is already running. Stop it first.")
        if allocated_dollars <= 0:
            raise ValueError("Allocated dollars must be greater than 0.")

        self.broker.verify_connection()

        self.ticker = ticker.strip().upper()
        self.strategy_name = strategy_name
        self.allocated_dollars = allocated_dollars
        self.trade_history = [t for t in load_all_trades() if t["ticker"] == self.ticker]
        self._last_bar_check = 0.0
        self._last_account_check = 0.0
        self._stop_flag.clear()
        self.running = True

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.running:
            return
        self._stop_flag.set()
        if self._thread:
            self._thread.join(timeout=10)
        self.running = False

    def close_position(self):
        if self.position != "long":
            raise ValueError("No open position to close.")
        pos = self.broker.get_position(self.ticker)
        exit_price = (pos["market_value"] / pos["qty"]) if pos and pos["qty"] else (self.entry_price or 0)
        qty = pos["qty"] if pos else 0
        result = self.broker.close_position(self.ticker)
        self._record_trade("manual_close", "sell", exit_price, qty=qty, status=result["status"])
        self.position = "flat"
        self.entry_price = None
        self._push_notification(f"Position closed for {self.ticker}.", "info")

    # ---------- worker loop ----------

    def _run_loop(self):
        strategy = strategies.get_strategy(self.strategy_name)
        while not self._stop_flag.is_set():
            try:
                self._tick(strategy)
            except broker_module.BrokerError as e:
                self._push_notification(str(e), "error")
            except Exception as e:
                self._push_notification(f"Unexpected error: {e}", "error")
            self._stop_flag.wait(TICK_SECONDS)

    def _tick(self, strategy):
        now = time.time()

        if now - self._last_account_check >= ACCOUNT_REFRESH_SECONDS:
            account = self.broker.get_account()
            self.equity = account["equity"]
            self.buying_power = account["buying_power"]
            self.market_open = self.broker.is_market_open()
            self._last_account_check = now

            pos = self.broker.get_position(self.ticker)
            if pos:
                self.position = "long"
                self.entry_price = pos["entry_price"]
                self.unrealized_pl = pos["unrealized_pl_pct"]
            else:
                self.position = "flat"
                self.entry_price = None
                self.unrealized_pl = None

        if not self.market_open:
            self.last_update = dt.datetime.now().strftime("%H:%M:%S")
            return

        if now - self._last_bar_check >= BAR_POLL_SECONDS:
            self._last_bar_check = now
            self.last_update = dt.datetime.now().strftime("%H:%M:%S")

            bars = self.broker.get_recent_bars(self.ticker, pd.Timedelta(days=5))
            if len(bars) < 30:
                return

            sig_df = strategy.generate_signals(bars)
            self.chart_data = self._build_chart_data(sig_df)

            latest_signal = sig_df["signal"].iloc[-1]
            latest_price = float(bars["Close"].iloc[-1])

            if latest_signal == 1 and self.position == "flat":
                qty = self._position_size(latest_price)
                if qty > 0:
                    result = self.broker.submit_market_order(self.ticker, qty, "buy")
                    fill_price = self._wait_for_fill(result["id"], latest_price)
                    self._record_trade("buy_signal", "buy", fill_price, qty, result["status"])
                    self.position = "long"
                    self.entry_price = fill_price
                    self._push_notification(
                        f"BUY signal fired for {self.ticker} @ ${fill_price:.2f}", "success"
                    )

            elif latest_signal == -1 and self.position == "long":
                pos = self.broker.get_position(self.ticker)
                qty = pos["qty"] if pos else 0
                if qty > 0:
                    result = self.broker.submit_market_order(self.ticker, qty, "sell")
                    fill_price = self._wait_for_fill(result["id"], latest_price)
                    self._record_trade("sell_signal", "sell", fill_price, qty, result["status"])
                    self.position = "flat"
                    self.entry_price = None
                    self._push_notification(
                        f"SELL signal fired for {self.ticker} @ ${fill_price:.2f}", "success"
                    )

    def _wait_for_fill(self, order_id: str, fallback_price: float, timeout: float = 3.0, interval: float = 0.3) -> float:
        """Polls briefly for the order's real average fill price. Market
        orders during regular hours typically fill in well under a second;
        if it hasn't reported a fill by the timeout, falls back to the bar
        close price that triggered the trade rather than blocking longer.

        The order was already submitted by the time this runs -- a
        transient error here must not abort the caller, or a real fill
        would go completely unlogged even though it happened on Alpaca."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                order = self.broker.get_order(order_id)
            except broker_module.BrokerError:
                order = None
            if order and order["filled_avg_price"]:
                return order["filled_avg_price"]
            time.sleep(interval)
        return fallback_price

    def _position_size(self, price):
        if not self.buying_power or not self.allocated_dollars or price <= 0:
            return 0
        spendable = min(self.allocated_dollars, self.buying_power)
        raw_qty = (spendable * 0.95) / price
        return round(raw_qty, 4) if raw_qty > 0 else 0

    # ---------- chart data ----------

    def _build_chart_data(self, sig_df: pd.DataFrame) -> dict:
        ohlc = [
            {
                "time": int(ts.timestamp()),
                "open": round(float(o), 4),
                "high": round(float(h), 4),
                "low": round(float(l), 4),
                "close": round(float(c), 4),
            }
            for ts, o, h, l, c in zip(
                sig_df.index, sig_df["Open"], sig_df["High"], sig_df["Low"], sig_df["Close"]
            )
        ]

        indicators = {}
        for col in ("sma_fast", "sma_slow", "rsi", "sma", "roc", "bb_upper", "bb_middle", "bb_lower"):
            if col not in sig_df.columns:
                continue
            indicators[col] = [
                {"time": int(ts.timestamp()), "value": round(float(v), 4)}
                for ts, v in sig_df[col].items()
                if pd.notna(v)
            ]

        return {
            "ohlc": ohlc,
            "indicators": indicators,
            "trades": self._trade_pairs(),
            "equity_curve": [],
            "train_test_cutoff": None,
        }

    def _trade_pairs(self) -> list:
        # self.trade_history is already scoped to self.ticker (see start()).
        pairs = []
        open_trade = None
        for t in self.trade_history:
            ts = int(pd.Timestamp(t["timestamp"]).timestamp())
            if t["side"] == "buy":
                open_trade = {"entry_date": ts, "entry_price": t["price"]}
            elif t["side"] == "sell" and open_trade:
                open_trade["exit_date"] = ts
                open_trade["exit_price"] = t["price"]
                pairs.append(open_trade)
                open_trade = None
        if open_trade:
            open_trade["exit_date"] = None
            pairs.append(open_trade)
        return pairs

    # ---------- status ----------

    def get_status(self) -> dict:
        with self._lock:
            notifications, self.notifications = self.notifications, []
        return {
            "running": self.running,
            "ticker": self.ticker,
            "strategy": self.strategy_name,
            "allocated_dollars": self.allocated_dollars,
            "market_open": self.market_open,
            "position": self.position,
            "entry_price": self.entry_price,
            "unrealized_pl": self.unrealized_pl,
            "last_update": self.last_update,
            "chart_data": self.chart_data,
            "trade_history": self.trade_history,
            "notifications": notifications,
        }
