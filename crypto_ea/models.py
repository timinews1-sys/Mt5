from dataclasses import dataclass


@dataclass(frozen=True)
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    open_time: int
    price: float
    side: str
    message: str


@dataclass(frozen=True)
class PlotPoint:
    open_time: int
    name: str
    value: float | None


@dataclass(frozen=True)
class Trade:
    side: str
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    profit: float


@dataclass(frozen=True)
class BacktestResult:
    symbol: str
    interval: str
    candles_tested: int
    signals: tuple[Signal, ...]
    plots: tuple[PlotPoint, ...]
    trades: tuple[Trade, ...]
    net_profit: float

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for trade in self.trades if trade.profit > 0)
        return wins / len(self.trades)
