import unittest

from crypto_ea import Candle, StrategyError, compile_strategy, run_backtest


def candles(*closes: float) -> list[Candle]:
    return [
        Candle(
            open_time=index * 60_000,
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=10,
        )
        for index, close in enumerate(closes)
    ]


class StrategyCompilerTests(unittest.TestCase):
    def test_runs_user_signal_and_plot_script(self) -> None:
        script = """\
def on_bar(ctx):
    average = ctx.sma(2)
    ctx.plot("average", average)
    if average is not None and ctx.close_price > average:
        ctx.signal("BUY", "above average")
"""
        result = run_backtest(script, candles(10, 11, 10), "BTCUSDT", "1m")

        self.assertEqual(len(result.signals), 1)
        self.assertEqual(result.signals[0].side, "BUY")
        self.assertEqual(result.signals[0].message, "above average")
        self.assertEqual(len(result.plots), 3)
        self.assertIsNone(result.plots[0].value)
        self.assertEqual(result.plots[-1].value, 10.5)

    def test_orders_fill_on_next_candle_and_close_at_next_open(self) -> None:
        script = """\
def on_bar(ctx):
    if ctx.index == 0:
        ctx.buy()
    elif ctx.index == 2:
        ctx.close_position()
"""
        result = run_backtest(script, candles(10, 11, 12, 9), "BTCUSDT", "1m")

        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.side, "LONG")
        self.assertEqual(trade.entry_time, 60_000)
        self.assertEqual(trade.exit_time, 180_000)
        self.assertEqual(trade.entry_price, 11)
        self.assertEqual(trade.exit_price, 9)
        self.assertEqual(result.net_profit, -2)
        self.assertEqual(result.win_rate, 0)

    def test_sell_closes_spot_position_at_next_open(self) -> None:
        script = """\
def on_bar(ctx):
    if ctx.index == 0:
        ctx.buy()
    elif ctx.index == 1:
        ctx.sell()
"""
        result = run_backtest(script, candles(10, 11, 12), "BTCUSDT", "1m")

        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].side, "LONG")
        self.assertEqual(result.trades[0].entry_price, 11)
        self.assertEqual(result.trades[0].exit_price, 12)
        self.assertEqual(result.net_profit, 1)

    def test_rsi_uses_wilder_smoothing_and_old_offsets(self) -> None:
        script = """\
def on_bar(ctx):
    ctx.plot("rsi", ctx.rsi(2))
    ctx.plot("old", ctx.sma(2, 2))
"""
        result = run_backtest(script, candles(10, 11, 12, 11, 13), "BTCUSDT", "1m")

        self.assertIsNone(result.plots[0].value)
        self.assertEqual(result.plots[4].value, 100)
        self.assertAlmostEqual(result.plots[8].value, 83.3333333333)
        self.assertIsNone(result.plots[1].value)
        self.assertIsNone(result.plots[5].value)
        self.assertEqual(result.plots[7].value, 10.5)

    def test_rejects_imports_loops_and_arbitrary_calls(self) -> None:
        unsupported_scripts = (
            "import os\ndef on_bar(ctx):\n    pass\n",
            "def on_bar(ctx):\n    while True:\n        pass\n",
            "def on_bar(ctx):\n    print(ctx.close_price)\n",
            "def on_bar(ctx):\n    ctx.__class__\n",
        )
        for script in unsupported_scripts:
            with self.subTest(script=script), self.assertRaises(StrategyError):
                compile_strategy(script)

    def test_rejects_use_before_assignment(self) -> None:
        script = """\
def on_bar(ctx):
    if unknown > 0:
        ctx.signal("BUY")
"""
        with self.assertRaisesRegex(StrategyError, "used before assignment"):
            run_backtest(script, candles(10), "BTCUSDT", "1m")

    def test_prevents_unbounded_string_arithmetic(self) -> None:
        script = """\
def on_bar(ctx):
    message = "x" * 100000000
    ctx.signal("INFO", message)
"""
        with self.assertRaisesRegex(StrategyError, "numeric values"):
            run_backtest(script, candles(10), "BTCUSDT", "1m")

    def test_bounds_strategy_complexity_and_backtest_size(self) -> None:
        with self.assertRaisesRegex(StrategyError, "16 KB"):
            compile_strategy(" " * 16_385)
        with self.assertRaisesRegex(StrategyError, "at most 5,000"):
            run_backtest(
                "def on_bar(ctx):\n    pass\n",
                candles(*([1.0] * 5001)),
                "BTCUSDT",
                "1m",
            )


if __name__ == "__main__":
    unittest.main()
