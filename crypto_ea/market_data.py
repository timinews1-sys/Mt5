import json
import math
import re
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Candle


class MarketDataError(RuntimeError):
    pass


_BASE_URL = "https://api.binance.com/api/v3"
_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d"}
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{5,20}$")


def fetch_latest_price(symbol: str, timeout: float = 10.0) -> float:
    _validate_symbol(symbol)
    payload = _get_json("ticker/price", {"symbol": symbol}, timeout)
    if not isinstance(payload, dict) or "price" not in payload:
        raise MarketDataError("The exchange returned an invalid price response.")
    try:
        return _positive_number(payload["price"], "price")
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarketDataError(f"The exchange returned an invalid price: {exc}") from exc


def fetch_candles(
    symbol: str,
    interval: str = "1h",
    limit: int = 500,
    timeout: float = 15.0,
) -> list[Candle]:
    _validate_symbol(symbol)
    if interval not in _INTERVALS:
        raise MarketDataError(
            f"Unsupported interval '{interval}'. Choose from {', '.join(sorted(_INTERVALS))}."
        )
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise MarketDataError("Candle limit must be an integer from 1 to 1,000.")

    payload = _get_json(
        "klines",
        {"symbol": symbol, "interval": interval, "limit": limit},
        timeout,
    )
    if not isinstance(payload, list):
        raise MarketDataError("The exchange returned an invalid candle response.")

    candles: list[Candle] = []
    try:
        for row in payload:
            if not isinstance(row, list) or len(row) < 7:
                raise ValueError("A candle row is incomplete.")
            close_time = int(row[6])
            if close_time >= int(time.time() * 1000):
                continue
            candle = Candle(
                open_time=int(row[0]),
                open=_positive_number(row[1], "open"),
                high=_positive_number(row[2], "high"),
                low=_positive_number(row[3], "low"),
                close=_positive_number(row[4], "close"),
                volume=_nonnegative_number(row[5], "volume"),
            )
            if candle.high < max(candle.open, candle.close):
                raise ValueError("A candle high is below its open or close.")
            if candle.low > min(candle.open, candle.close):
                raise ValueError("A candle low is above its open or close.")
            if candles and candle.open_time <= candles[-1].open_time:
                raise ValueError("Candle timestamps are not strictly increasing.")
            candles.append(candle)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarketDataError(f"The exchange returned invalid candle data: {exc}") from exc

    if not candles:
        raise MarketDataError("The exchange returned no candles.")
    return candles


def _validate_symbol(symbol: str) -> None:
    if not isinstance(symbol, str) or not _SYMBOL_PATTERN.fullmatch(symbol):
        raise MarketDataError("Use an uppercase exchange symbol such as BTCUSDT.")


def _get_json(path: str, params: dict[str, object], timeout: float) -> object:
    url = f"{_BASE_URL}/{path}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "DTEA/0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise MarketDataError(
            f"Exchange request failed with HTTP {exc.code}."
        ) from exc
    except (URLError, TimeoutError, OSError, HTTPException) as exc:
        raise MarketDataError(f"Could not connect to the crypto data provider: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketDataError("The crypto data provider returned invalid JSON.") from exc


def _positive_number(value: object, field: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be a positive finite number.")
    return number


def _nonnegative_number(value: object, field: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be a non-negative finite number.")
    return number
