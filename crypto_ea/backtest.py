import math
from dataclasses import dataclass

from .models import BacktestResult, Candle, PlotPoint, Signal, Trade
from .strategy import StrategyContext, StrategyError, StrategyProgram, compile_strategy


@dataclass(frozen=True)
class _Position:
    side: int
    entry_index: int
    entry_price: float


class _BarContext(StrategyContext):
    def __init__(
        self,
        candles: tuple[Candle, ...],
        index: int,
        position: int,
        signals: list[Signal],
        plots: list[PlotPoint],
        indicator_cache: dict[tuple[str, int], tuple[float | None, ...]],
    ) -> None:
        self._candles = candles
        self._index = index
        self._position = position
        self._signals = signals
        self._plots = plots
        self._indicator_cache = indicator_cache
        self.action: str | None = None

    def read_attr(self, name: str) -> object:
        candle = self._candles[self._index]
        if name == "open":
            return candle.open
        if name == "high":
            return candle.high
        if name == "low":
            return candle.low
        if name == "close_price":
            return candle.close
        if name == "volume":
            return candle.volume
        if name == "position":
            return self._position
        if name == "index":
            return self._index
        raise StrategyError(f"ctx.{name} is not a readable property.")

    def call(self, name: str, args: list[object]) -> object:
        if name in {"sma", "ema", "rsi"}:
            period, offset = self._indicator_args(name, args)
            return self._indicator(name, period, offset)
        if name == "signal":
            if len(args) not in (1, 2):
                raise StrategyError("ctx.signal expects side and optional message.")
            side = args[0]
            message = args[1] if len(args) == 2 else ""
            if side not in ("BUY", "SELL", "INFO"):
                raise StrategyError("Signal side must be BUY, SELL, or INFO.")
            if not isinstance(message, str):
                raise StrategyError("Signal message must be text.")
            if len(message) > 256:
                raise StrategyError("Signal messages may not exceed 256 characters.")
            if len(self._signals) >= 20_000:
                raise StrategyError("The script produced too many signals (maximum 20,000).")
            self._signals.append(
                Signal(
                    self._candles[self._index].open_time,
                    self._candles[self._index].close,
                    side,
                    message,
                )
            )
            return None
        if name == "plot":
            if len(args) != 2 or not isinstance(args[0], str):
                raise StrategyError("ctx.plot expects a name and a numeric value.")
            if not args[0] or len(args[0]) > 80:
                raise StrategyError("Plot names must contain 1 to 80 characters.")
            value = args[1]
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise StrategyError("Plot values must be finite numbers or None.")
            if len(self._plots) >= 20_000:
                raise StrategyError("The script produced too many plot points (maximum 20,000).")
            self._plots.append(
                PlotPoint(
                    self._candles[self._index].open_time,
                    args[0],
                    float(value) if value is not None else None,
                )
            )
            return None
        if name in {"buy", "sell", "close_position"}:
            if args:
                raise StrategyError(f"ctx.{name} does not accept arguments.")
            if self.action is not None:
                raise StrategyError("Only one simulated order action is allowed per candle.")
            self.action = {
                "buy": "BUY",
                "sell": "CLOSE",
                "close_position": "CLOSE",
            }[name]
            return None
        raise StrategyError(f"ctx.{name} is not available.")

    def _indicator_args(self, name: str, args: list[object]) -> tuple[int, int]:
        if len(args) not in (1, 2):
            raise StrategyError(f"ctx.{name} expects period and optional offset.")
        period, offset = args[0], args[1] if len(args) == 2 else 0
        if (
            isinstance(period, bool)
            or not isinstance(period, int)
            or not 1 <= period <= 1000
        ):
            raise StrategyError("Indicator period must be an integer from 1 to 1000.")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 1000:
            raise StrategyError("Indicator offset must be an integer from 0 to 1000.")
        return period, offset

    def _indicator(self, name: str, period: int, offset: int) -> float | None:
        target_index = self._index - offset
        if target_index < 0:
            return None
        key = (name, period)
        if key not in self._indicator_cache:
            self._indicator_cache[key] = _calculate_indicator(
                name,
                period,
                self._candles,
            )
        return self._indicator_cache[key][target_index]


def _calculate_indicator(
    name: str,
    period: int,
    candles: tuple[Candle, ...],
) -> tuple[float | None, ...]:
    closes = [candle.close for candle in candles]
    output: list[float | None] = [None] * len(closes)
    if name == "sma":
        rolling_sum = 0.0
        for index, close in enumerate(closes):
            rolling_sum += close
            if index >= period:
                rolling_sum -= closes[index - period]
            if index >= period - 1:
                output[index] = rolling_sum / period
    elif name == "ema":
        if len(closes) >= period:
            value = sum(closes[:period]) / period
            output[period - 1] = value
            alpha = 2.0 / (period + 1)
            for index in range(period, len(closes)):
                value = closes[index] * alpha + value * (1.0 - alpha)
                output[index] = value
    else:
        gains = [0.0] * len(closes)
        losses = [0.0] * len(closes)
        for index in range(1, len(closes)):
            change = closes[index] - closes[index - 1]
            gains[index] = max(change, 0.0)
            losses[index] = max(-change, 0.0)
        if len(closes) > period:
            average_gain = sum(gains[1 : period + 1]) / period
            average_loss = sum(losses[1 : period + 1]) / period
            output[period] = _rsi_value(average_gain, average_loss)
            for index in range(period + 1, len(closes)):
                average_gain = (
                    average_gain * (period - 1) + gains[index]
                ) / period
                average_loss = (
                    average_loss * (period - 1) + losses[index]
                ) / period
                output[index] = _rsi_value(average_gain, average_loss)
    return tuple(output)


def _rsi_value(average_gain: float, average_loss: float) -> float:
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def run_backtest(
    source: str | StrategyProgram,
    candles: list[Candle] | tuple[Candle, ...],
    symbol: str,
    interval: str,
) -> BacktestResult:
    if not candles:
        raise StrategyError("At least one candle is required for a backtest.")
    if len(candles) > 5000:
        raise StrategyError("A backtest may use at most 5,000 candles on this device.")
    if isinstance(source, str):
        program = compile_strategy(source)
    elif isinstance(source, StrategyProgram):
        program = source
    else:
        raise StrategyError("A backtest requires strategy source or a compiled strategy.")
    bars = tuple(candles)
    signals: list[Signal] = []
    plots: list[PlotPoint] = []
    indicator_cache: dict[tuple[str, int], tuple[float | None, ...]] = {}
    trades: list[Trade] = []
    position: _Position | None = None
    pending_action: str | None = None

    for index, candle in enumerate(bars):
        if pending_action is not None:
            target_side = {"BUY": 1, "CLOSE": 0}[pending_action]
            if position is not None and position.side != target_side:
                trades.append(
                    _close_position(position, index, candle.open, bars)
                )
                position = None
            if target_side and position is None:
                position = _Position(target_side, index, candle.open)
            pending_action = None

        context = _BarContext(
            bars,
            index,
            position.side if position is not None else 0,
            signals,
            plots,
            indicator_cache,
        )
        try:
            program.run(context)
        except StrategyError as exc:
            raise StrategyError(f"Strategy failed on candle {index}: {exc}") from exc
        pending_action = context.action

    if position is not None:
        trades.append(_close_position(position, len(bars) - 1, bars[-1].close, bars))

    return BacktestResult(
        symbol=symbol,
        interval=interval,
        candles_tested=len(bars),
        signals=tuple(signals),
        plots=tuple(plots),
        trades=tuple(trades),
        net_profit=sum(trade.profit for trade in trades),
    )


def _close_position(
    position: _Position,
    exit_index: int,
    exit_price: float,
    candles: tuple[Candle, ...],
) -> Trade:
    profit = (exit_price - position.entry_price) * position.side
    return Trade(
        side="LONG" if position.side > 0 else "SHORT",
        entry_time=candles[position.entry_index].open_time,
        exit_time=candles[exit_index].open_time,
        entry_price=position.entry_price,
        exit_price=exit_price,
        profit=profit,
    )
