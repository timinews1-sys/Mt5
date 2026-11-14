import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import BacktestResult, Candle


class LocalStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_tables()

    def close(self) -> None:
        self._connection.close()

    def save_script(self, name: str, source: str) -> None:
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 80:
            raise ValueError("Script name must contain 1 to 80 characters.")
        if len(source) > 16_384:
            raise ValueError("Script source exceeds the 16 KB limit.")
        self._connection.execute(
            """
            INSERT INTO scripts(name, source, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (clean_name, source, int(time.time() * 1000)),
        )
        self._connection.commit()

    def load_script(self, name: str) -> str | None:
        row = self._connection.execute(
            "SELECT source FROM scripts WHERE name = ?",
            (name,),
        ).fetchone()
        return str(row["source"]) if row else None

    def list_scripts(self) -> list[tuple[str, str]]:
        rows = self._connection.execute(
            "SELECT name, source FROM scripts ORDER BY updated_at DESC, name"
        ).fetchall()
        return [(str(row["name"]), str(row["source"])) for row in rows]

    def save_candles(self, symbol: str, interval: str, candles: list[Candle]) -> None:
        self._connection.executemany(
            """
            INSERT INTO candles(symbol, interval, open_time, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, interval, open_time) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume
            """,
            [
                (
                    symbol,
                    interval,
                    candle.open_time,
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                )
                for candle in candles
            ],
        )
        self._connection.commit()

    def load_candles(self, symbol: str, interval: str, limit: int = 1000) -> list[Candle]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("Candle limit must be a positive integer.")
        rows = self._connection.execute(
            """
            SELECT open_time, open, high, low, close, volume
            FROM (
                SELECT open_time, open, high, low, close, volume
                FROM candles
                WHERE symbol = ? AND interval = ?
                ORDER BY open_time DESC
                LIMIT ?
            )
            ORDER BY open_time
            """,
            (symbol, interval, limit),
        ).fetchall()
        return [
            Candle(
                open_time=int(row["open_time"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for row in rows
        ]

    def save_backtest(self, result: BacktestResult) -> int:
        result_json = json.dumps(asdict(result), allow_nan=False, separators=(",", ":"))
        cursor = self._connection.execute(
            """
            INSERT INTO backtests(symbol, interval, created_at, candles_tested, result_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                result.symbol,
                result.interval,
                int(time.time() * 1000),
                result.candles_tested,
                result_json,
            ),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    def list_backtests(self, limit: int = 20) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("Backtest limit must be an integer from 1 to 100.")
        rows = self._connection.execute(
            """
            SELECT id, symbol, interval, created_at, candles_tested, result_json
            FROM backtests
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "symbol": str(row["symbol"]),
                "interval": str(row["interval"]),
                "created_at": int(row["created_at"]),
                "candles_tested": int(row["candles_tested"]),
                "result": json.loads(str(row["result_json"])),
            }
            for row in rows
        ]

    def _create_tables(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS scripts (
                name TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS candles (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                open_time INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                PRIMARY KEY(symbol, interval, open_time)
            );
            CREATE TABLE IF NOT EXISTS backtests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                candles_tested INTEGER NOT NULL,
                result_json TEXT NOT NULL
            );
            """
        )
        self._connection.commit()
