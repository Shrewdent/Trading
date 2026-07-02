"""PyWebView API bridge. Every method returns {"ok": True, "data": ...} on
success or {"ok": False, "error": "friendly message"} on failure — the JS
side never has to deal with raw exceptions or tracebacks.
"""

import functools
import logging
import os
import webview

GUI_INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui", "index.html")

import backtest
import broker as broker_module
import config
import data
import db
import paper_trader
import strategies

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")


def friendly_error(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            result = fn(*args, **kwargs)
            return {"ok": True, "data": result}
        except data.DataError as e:
            return {"ok": False, "error": str(e)}
        except broker_module.BrokerError as e:
            return {"ok": False, "error": str(e)}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.exception("Unhandled error in %s", fn.__name__)
            return {"ok": False, "error": f"Something went wrong: {e}"}

    return wrapper


class Api:
    def __init__(self):
        self._trader: paper_trader.PaperTrader | None = None

    # ---------- Backtester ----------

    @friendly_error
    def run_backtest(self, options: dict):
        ticker = (options.get("ticker") or "").strip()
        start_date = options.get("start_date")
        end_date = options.get("end_date")
        strategy_name = options.get("strategy")
        params = options.get("params") or {}
        train_test_split = bool(options.get("train_test_split", False))
        commission_pct = float(options.get("commission_pct", backtest.DEFAULT_COMMISSION_PCT))
        slippage_pct = float(options.get("slippage_pct", backtest.DEFAULT_SLIPPAGE_PCT))

        if not ticker:
            raise ValueError("Ticker is required.")
        if not start_date or not end_date:
            raise ValueError("Start and end dates are required.")
        if strategy_name not in strategies.REGISTRY:
            raise ValueError(f"Unknown strategy '{strategy_name}'.")

        result = backtest.run_backtest(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            strategy_name=strategy_name,
            params=params,
            commission_pct=commission_pct,
            slippage_pct=slippage_pct,
            train_test_split=train_test_split,
        )

        cfg = config.load()
        cfg["last_used"] = {
            "ticker": ticker.upper(),
            "strategy": strategy_name,
            "start_date": start_date,
            "end_date": end_date,
        }
        config.save(cfg)

        return result

    @friendly_error
    def get_strategies(self):
        return strategies.list_strategies()

    # ---------- Results History ----------

    @friendly_error
    def get_history(self):
        return db.list_backtests()

    @friendly_error
    def get_backtest_detail(self, backtest_id: int):
        record = db.get_backtest(int(backtest_id))
        if record is None:
            raise ValueError(f"Backtest #{backtest_id} not found.")
        return record

    @friendly_error
    def delete_backtest(self, backtest_id: int):
        deleted = db.delete_backtest(int(backtest_id))
        if not deleted:
            raise ValueError(f"Backtest #{backtest_id} not found.")
        return {"deleted": True}

    # ---------- Config ----------

    @friendly_error
    def get_config(self):
        cfg = config.load()
        # Never send raw secret key contents to the frontend beyond a presence flag.
        return {
            "theme": cfg.get("theme", "dark"),
            "last_used": cfg.get("last_used", {}),
            "has_alpaca_keys": config.has_alpaca_keys(),
        }

    @friendly_error
    def save_alpaca_keys(self, api_key: str, secret_key: str):
        cfg = config.load()
        cfg["alpaca"] = {"api_key": api_key.strip(), "secret_key": secret_key.strip()}
        config.save(cfg)
        return {"saved": True, "has_alpaca_keys": config.has_alpaca_keys()}

    # ---------- Paper Trader ----------

    @friendly_error
    def start_paper_trader(self, options: dict):
        ticker = (options.get("ticker") or "").strip()
        strategy_name = options.get("strategy")
        if not ticker:
            raise ValueError("Ticker is required.")
        if strategy_name not in strategies.REGISTRY:
            raise ValueError(f"Unknown strategy '{strategy_name}'.")
        if not config.has_alpaca_keys():
            raise ValueError("Add your Alpaca paper trading keys first.")

        cfg = config.load()
        keys = cfg["alpaca"]
        if self._trader is None or not self._trader.running:
            self._trader = paper_trader.PaperTrader(keys["api_key"], keys["secret_key"])
        self._trader.start(ticker=ticker, strategy_name=strategy_name)
        return {"started": True}

    @friendly_error
    def stop_paper_trader(self):
        if self._trader:
            self._trader.stop()
        return {"stopped": True}

    @friendly_error
    def close_position(self):
        if not self._trader:
            raise ValueError("Paper trading isn't running.")
        self._trader.close_position()
        return {"closed": True}

    @friendly_error
    def get_paper_status(self):
        if self._trader is None:
            return {
                "running": False,
                "ticker": None,
                "strategy": None,
                "market_open": False,
                "position": "flat",
                "entry_price": None,
                "unrealized_pl": None,
                "equity": None,
                "buying_power": None,
                "last_update": None,
                "chart_data": None,
                "trade_history": [],
                "notifications": [],
            }
        return self._trader.get_status()


def main():
    api = Api()
    window = webview.create_window(
        "Backtesting & Paper Trading Platform",
        GUI_INDEX,
        js_api=api,
        width=1440,
        height=900,
        min_size=(1100, 700),
        background_color="#0d1117",
    )

    def on_closing():
        if api._trader and api._trader.running:
            api._trader.stop()

    window.events.closing += on_closing
    webview.start(debug=False, http_server=True)


if __name__ == "__main__":
    main()
