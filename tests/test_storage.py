import tempfile
import unittest
from pathlib import Path

from crypto_ea import Candle, run_backtest
from crypto_ea.storage import LocalStore


class LocalStoreTests(unittest.TestCase):
    def test_persists_scripts_candles_and_backtests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory) / "app.sqlite3")
            try:
                source = "def on_bar(ctx):\n    ctx.signal('INFO', 'hello')\n"
                candles = [
                    Candle(1, 10, 11, 9, 10, 5),
                    Candle(2, 11, 12, 10, 11, 7),
                ]
                store.save_script("My indicator", source)
                store.save_candles("BTCUSDT", "1m", candles)
                self.assertEqual(store.load_script("My indicator"), source)
                self.assertEqual(store.list_scripts(), [("My indicator", source)])
                self.assertEqual(store.load_candles("BTCUSDT", "1m"), candles)

                result = run_backtest(source, candles, "BTCUSDT", "1m")
                run_id = store.save_backtest(result)
                runs = store.list_backtests()

                self.assertGreater(run_id, 0)
                self.assertEqual(runs[0]["symbol"], "BTCUSDT")
                self.assertEqual(runs[0]["result"]["signals"][0]["message"], "hello")
            finally:
                store.close()

    def test_rejects_invalid_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory) / "app.sqlite3")
            try:
                with self.assertRaises(ValueError):
                    store.load_candles("BTCUSDT", "1m", 0)
                with self.assertRaises(ValueError):
                    store.list_backtests(101)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
