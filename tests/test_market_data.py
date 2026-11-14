import json
import unittest
from io import BytesIO
from unittest.mock import patch

from crypto_ea.market_data import (
    MarketDataError,
    fetch_candles,
    fetch_latest_price,
)


class MarketDataTests(unittest.TestCase):
    @patch("crypto_ea.market_data.urlopen")
    def test_fetches_public_price_without_credentials(self, mock_urlopen) -> None:
        mock_urlopen.return_value.__enter__.return_value = BytesIO(
            b'{"symbol":"BTCUSDT","price":"67123.45"}'
        )

        price = fetch_latest_price("BTCUSDT")

        self.assertEqual(price, 67123.45)
        request = mock_urlopen.call_args.args[0]
        self.assertIn("symbol=BTCUSDT", request.full_url)

    @patch("crypto_ea.market_data.urlopen")
    def test_parses_crypto_candles(self, mock_urlopen) -> None:
        rows = [
            [1000, "10", "12", "9", "11", "5", 1999],
            [2000, "11", "13", "10", "12", "7", 2999],
        ]
        mock_urlopen.return_value.__enter__.return_value = BytesIO(
            json.dumps(rows).encode("utf-8")
        )

        candles = fetch_candles("ETHUSDT", "5m", 2)

        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[0].open_time, 1000)
        self.assertEqual(candles[1].close, 12)
        self.assertEqual(candles[1].volume, 7)
        self.assertIn("interval=5m", mock_urlopen.call_args.args[0].full_url)

    @patch("crypto_ea.market_data.urlopen")
    def test_ignores_unfinished_candle(self, mock_urlopen) -> None:
        rows = [
            [1000, "10", "12", "9", "11", "5", 1999],
            [2000, "11", "13", "10", "12", "7", 9_999_999_999_999],
        ]
        mock_urlopen.return_value.__enter__.return_value = BytesIO(
            json.dumps(rows).encode("utf-8")
        )

        candles = fetch_candles("ETHUSDT", "5m", 2)

        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].open_time, 1000)

    def test_rejects_bad_symbols_intervals_and_limits(self) -> None:
        with self.assertRaises(MarketDataError):
            fetch_candles("btc/usdt")
        with self.assertRaises(MarketDataError):
            fetch_candles("BTCUSDT", "2m")
        with self.assertRaises(MarketDataError):
            fetch_candles("BTCUSDT", limit=1001)

    @patch("crypto_ea.market_data.urlopen")
    def test_rejects_malformed_exchange_data(self, mock_urlopen) -> None:
        mock_urlopen.return_value.__enter__.return_value = BytesIO(b'[["bad"]]')

        with self.assertRaisesRegex(MarketDataError, "invalid candle data"):
            fetch_candles("BTCUSDT", "1m", 1)


if __name__ == "__main__":
    unittest.main()
