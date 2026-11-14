# DTEA

An Android-first, local app for user-authored crypto strategies and indicators.
This project is not MetaTrader 5 and does not execute `.mq5` or `.ex5` files.

## V1 scope

- Crypto spot market data from Binance's public API; no exchange account or API
  key is used. The app polls the latest price every 10 seconds and downloads
  historical candles for backtests.
- Scripts, candles, and backtest results are stored in SQLite on the device.
- Strategies produce signals and optional simulated trades only. No broker,
  order routing, leverage, or real-money execution is included.
- The mobile app is built with Kivy and can be packaged for Android with
  Buildozer.

Data availability depends on the provider, network, and region. Check exchange
terms before distributing the app or caching/reselling market data.

## Strategy scripts

Scripts use a restricted Python syntax. The app validates scripts and compiles
them into its own small instruction format, then interprets only those
instructions; it does not call Python `exec` and does not run arbitrary imports,
loops, file access, or network access.

```python
def on_bar(ctx):
    average = ctx.sma(20)
    ctx.plot("average", average)
    if average is not None and ctx.close_price > average:
        ctx.signal("BUY", "Price above average")
```

Available context properties: `open`, `high`, `low`, `close_price`, `volume`,
`position` (`0` for flat, `1` for holding spot), and `index`.

Available methods:

- `ctx.sma(period[, offset])`, `ctx.ema(period[, offset])`,
  `ctx.rsi(period[, offset])` (Wilder-smoothed RSI); periods are 1–1,000.
- `ctx.plot(name, value)` for user-defined indicator output.
- `ctx.signal("BUY" | "SELL" | "INFO", message)` for user-defined signals.
- `ctx.buy()` opens a simulated spot holding; `ctx.sell()` and
  `ctx.close_position()` close it. Short positions are not supported in v1.

The script entry point must be `def on_bar(ctx):`. Supported constructs are
assignments, `if`/`elif`/`else`, arithmetic, comparisons, and boolean operators.
Only documented `ctx` API calls are allowed; loops, imports, and general Python
execution are deliberately restricted.

Simulated order actions are filled at the next candle's open. Open positions are
closed at the last candle's close. The current model uses one unit and excludes
fees, slippage, funding, and exchange execution behavior, so its P/L is only a
basic simulation.

## Development

Run the core tests:

```sh
python3 -m unittest discover -s tests -v
```

To package on a Linux Android build host, install Buildozer and its Android
SDK/NDK prerequisites, then run:

```sh
buildozer android debug
```

## Install a GitHub Actions build

The `Android APK` workflow builds a debug APK on pushes to `main`, pull requests,
or when started manually from the GitHub Actions tab. After a successful run,
download the `dtea-debug-apk` artifact and extract it. It contains separate APKs
for each supported CPU architecture; install the one matching the phone or
tablet. Most modern Android devices use `arm64-v8a`. Android may ask you to
allow installation from the browser or file manager used to open it.

The Android build targets Android 8.0 (API 26) and newer and produces
ABI-specific APKs for 64-bit ARM, 32-bit ARM, 64-bit x86, and 32-bit x86.
Install the APK matching the device CPU architecture. The interface supports
portrait and landscape layouts, including wider tablet screens.

This is a debug build for testing, not a Play Store release. A production
release should use a protected signing key and a dedicated release workflow.
