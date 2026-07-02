"""SQLite storage for saved backtest runs."""

import json
import os
import sqlite3
import datetime as dt

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtests.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    strategy TEXT NOT NULL,
    params TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    return_pct REAL,
    benchmark_return_pct REAL,
    win_rate REAL,
    max_dd REAL,
    sharpe REAL,
    num_trades INTEGER,
    avg_trade_duration REAL,
    chart_data TEXT,
    created_at TEXT NOT NULL
);
"""


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    try:
        conn.execute(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def save_backtest(record: dict) -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO backtests
                (ticker, strategy, params, start_date, end_date, return_pct,
                 benchmark_return_pct, win_rate, max_dd, sharpe, num_trades,
                 avg_trade_duration, chart_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["ticker"],
                record["strategy"],
                json.dumps(record["params"]),
                record["start_date"],
                record["end_date"],
                record["return_pct"],
                record["benchmark_return_pct"],
                record["win_rate"],
                record["max_dd"],
                record["sharpe"],
                record["num_trades"],
                record["avg_trade_duration"],
                json.dumps(record["chart_data"]),
                dt.datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_backtests() -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, ticker, strategy, params, start_date, end_date, return_pct,
                   benchmark_return_pct, win_rate, max_dd, sharpe, num_trades,
                   avg_trade_duration, created_at
            FROM backtests ORDER BY created_at DESC
            """
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d["params"])
            out.append(d)
        return out
    finally:
        conn.close()


def get_backtest(backtest_id: int) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM backtests WHERE id = ?", (backtest_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["params"] = json.loads(d["params"])
        d["chart_data"] = json.loads(d["chart_data"])
        return d
    finally:
        conn.close()


def delete_backtest(backtest_id: int) -> bool:
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM backtests WHERE id = ?", (backtest_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


init_db()
