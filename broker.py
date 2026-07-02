"""Alpaca paper-trading connector. Always paper=True -- no real money, ever.

Uses Alpaca's own market data (free IEX feed) for live bars, since yfinance's
intraday data is too limited for a live-polling paper trader.
"""

import pandas as pd
from alpaca.common.exceptions import APIError
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest


class BrokerError(Exception):
    """Raised for any Alpaca connectivity/auth/order problem, with a friendly message."""


class AlpacaBroker:
    def __init__(self, api_key: str, secret_key: str):
        if not api_key or not secret_key:
            raise BrokerError("Alpaca API key and secret key are required.")
        try:
            self.trading_client = TradingClient(api_key, secret_key, paper=True)
            self.data_client = StockHistoricalDataClient(api_key, secret_key)
        except Exception as e:
            raise BrokerError(f"Could not initialize Alpaca client: {e}")

    def verify_connection(self) -> dict:
        try:
            account = self.trading_client.get_account()
        except APIError as e:
            raise BrokerError(f"Alpaca rejected the connection - check your keys. ({str(e).strip()})")
        except Exception as e:
            raise BrokerError(f"Could not reach Alpaca: {e}")
        return {"account_number": account.account_number, "status": account.status.value}

    def get_account(self) -> dict:
        try:
            account = self.trading_client.get_account()
        except Exception as e:
            raise BrokerError(f"Could not fetch account info: {e}")
        return {
            "equity": float(account.equity),
            "buying_power": float(account.buying_power),
            "cash": float(account.cash),
        }

    def is_market_open(self) -> bool:
        try:
            clock = self.trading_client.get_clock()
            return bool(clock.is_open)
        except Exception as e:
            raise BrokerError(f"Could not fetch market clock: {e}")

    def get_position(self, symbol: str) -> dict | None:
        try:
            pos = self.trading_client.get_open_position(symbol)
        except APIError:
            return None
        except Exception as e:
            raise BrokerError(f"Could not fetch position: {e}")
        return {
            "symbol": pos.symbol,
            "qty": float(pos.qty),
            "entry_price": float(pos.avg_entry_price),
            "market_value": float(pos.market_value),
            "unrealized_pl": float(pos.unrealized_pl),
            "unrealized_pl_pct": float(pos.unrealized_plpc) * 100,
        }

    def get_all_positions(self) -> list[dict]:
        try:
            positions = self.trading_client.get_all_positions()
        except Exception as e:
            raise BrokerError(f"Could not fetch positions: {e}")
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "entry_price": float(p.avg_entry_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_pl_pct": float(p.unrealized_plpc) * 100,
            }
            for p in positions
        ]

    def get_recent_bars(self, symbol: str, lookback: pd.Timedelta) -> pd.DataFrame:
        """Recent minute bars from Alpaca's free IEX feed."""
        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Minute,
                start=pd.Timestamp.utcnow() - lookback,
                feed=DataFeed.IEX,
            )
            bars = self.data_client.get_stock_bars(request)
        except APIError as e:
            raise BrokerError(f"Alpaca data request failed: {e}")
        except Exception as e:
            raise BrokerError(f"Could not fetch live bars: {e}")

        df = bars.df
        if df.empty:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        if isinstance(df.index, pd.MultiIndex):
            df = df.loc[symbol]
        df = df.rename(
            columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
        )
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df[["Open", "High", "Low", "Close", "Volume"]]

    def submit_market_order(self, symbol: str, qty: float, side: str) -> dict:
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        try:
            order = self.trading_client.submit_order(
                MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=order_side,
                    time_in_force=TimeInForce.DAY,
                )
            )
        except APIError as e:
            raise BrokerError(f"Order rejected: {e}")
        except Exception as e:
            raise BrokerError(f"Could not submit order: {e}")
        return {"id": str(order.id), "status": order.status.value}

    def get_order(self, order_id: str) -> dict | None:
        try:
            order = self.trading_client.get_order_by_id(order_id)
        except Exception as e:
            raise BrokerError(f"Could not fetch order status: {e}")
        return {
            "status": order.status.value,
            "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        }

    def close_position(self, symbol: str) -> dict:
        try:
            order = self.trading_client.close_position(symbol)
        except APIError as e:
            raise BrokerError(f"Could not close position: {e}")
        except Exception as e:
            raise BrokerError(f"Could not close position: {e}")
        return {"id": str(order.id), "status": order.status.value}
