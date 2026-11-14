import sqlite3
import threading
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from .backtest import run_backtest
from .market_data import MarketDataError, fetch_candles, fetch_latest_price
from .storage import LocalStore
from .strategy import StrategyError, StrategyProgram, compile_strategy


_STARTER_SCRIPT = """\
def on_bar(ctx):
    # Add your own indicator or strategy logic.
    # Example: average = ctx.sma(20)
    # ctx.plot("average", average)
    pass
"""

_COLORS = {
    "background": (0.035, 0.055, 0.09, 1),
    "surface": (0.075, 0.10, 0.15, 1),
    "surface_alt": (0.11, 0.15, 0.21, 1),
    "text": (0.92, 0.95, 0.98, 1),
    "muted": (0.58, 0.66, 0.75, 1),
    "accent": (0.25, 0.84, 0.66, 1),
    "accent_text": (0.025, 0.08, 0.07, 1),
    "error": (1.0, 0.45, 0.43, 1),
    "success": (0.35, 0.88, 0.68, 1),
}

class CryptoStrategyApp(App):
    title = "DTEA"

    def build(self) -> BoxLayout:
        Window.clearcolor = _COLORS["background"]
        self._database_path = Path(self.user_data_dir) / "crypto_strategy_lab.sqlite3"
        self._store = LocalStore(self._database_path)
        self._busy = False
        self._price_loading = False

        scroll = ScrollView(do_scroll_x=False, bar_width=dp(3))
        viewport = FloatLayout(size_hint=(1, None))
        content = BoxLayout(
            orientation="vertical",
            padding=(dp(16), dp(18)),
            spacing=dp(12),
            size_hint=(None, None),
        )
        content.bind(minimum_height=content.setter("height"))
        viewport.add_widget(content)
        viewport.bind(
            width=lambda _widget, width: setattr(
                content, "width", min(width, dp(760))
            )
        )
        content.bind(
            width=lambda _widget, width: setattr(
                content, "x", (viewport.width - width) / 2
            ),
            height=lambda _widget, height: setattr(viewport, "height", height),
        )
        scroll.add_widget(viewport)
        content.add_widget(
            self._label(
                "[b]DTEA[/b]  [color=55d6a8]CRYPTO WORKBENCH[/color]",
                dp(36),
                dp(23),
                markup=True,
            )
        )
        content.add_widget(
            self._label(
                "Build indicators, test your ideas, and keep your work on this device.",
                dp(40),
                dp(13),
                _COLORS["muted"],
            )
        )

        market_card = self._card()
        market_card.add_widget(self._section_heading("MARKET", "Public spot data"))
        market_row = BoxLayout(spacing=dp(10), size_hint_y=None, height=dp(72))
        symbol_column = BoxLayout(orientation="vertical", spacing=dp(4))
        symbol_column.add_widget(self._label("SYMBOL", dp(18), dp(10), _COLORS["muted"]))
        self.symbol_input = self._text_input(
            "BTCUSDT", hint="e.g. BTCUSDT", height=None
        )
        symbol_column.add_widget(self.symbol_input)
        interval_column = BoxLayout(
            orientation="vertical",
            spacing=dp(4),
            size_hint_x=0.7,
        )
        interval_column.add_widget(self._label("CANDLE", dp(18), dp(10), _COLORS["muted"]))
        self.interval_input = Spinner(
            text="1h",
            values=("1m", "5m", "15m", "1h", "4h", "1d"),
            background_normal="",
            background_color=_COLORS["surface_alt"],
            color=_COLORS["text"],
        )
        interval_column.add_widget(self.interval_input)
        market_row.add_widget(symbol_column)
        market_row.add_widget(interval_column)
        market_card.add_widget(market_row)

        quote_row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(64))
        quote_text = BoxLayout(orientation="vertical", spacing=dp(2))
        quote_text.add_widget(self._label("LATEST PRICE", dp(18), dp(10), _COLORS["muted"]))
        self.price_label = self._label("—", dp(30), dp(21))
        quote_text.add_widget(self.price_label)
        self.price_detail_label = self._label(
            "Waiting for connection…", dp(20), dp(11), _COLORS["muted"]
        )
        self.refresh_button = self._button("Refresh", secondary=True, height=dp(40))
        self.refresh_button.size_hint_x = None
        self.refresh_button.width = dp(84)
        self.refresh_button.bind(on_release=self._refresh_price)
        quote_row.add_widget(quote_text)
        quote_row.add_widget(self.refresh_button)
        market_card.add_widget(quote_row)
        market_card.add_widget(
            self._label(
                "Public exchange data only. No account or API key required.",
                dp(20),
                dp(11),
                _COLORS["muted"],
            )
        )
        content.add_widget(market_card)

        strategy_card = self._card()
        strategy_card.add_widget(self._section_heading("STRATEGY", "Your script"))
        strategy_card.add_widget(
            self._label(
                "Write a restricted Python-style indicator or strategy. "
                "Scripts run locally and cannot access files or the network.",
                dp(42),
                dp(12),
                _COLORS["muted"],
            )
        )
        strategy_card.add_widget(
            self._label(
                "API: ctx.close_price • ctx.sma/ema/rsi(period) • "
                "ctx.signal(side, message) • ctx.plot(name, value)",
                dp(38),
                dp(11),
                _COLORS["accent"],
            )
        )
        self.script_name_input = self._text_input(
            "My strategy", hint="Name this script", height=dp(46)
        )
        strategy_card.add_widget(self.script_name_input)
        self.script_input = TextInput(
            text=_STARTER_SCRIPT,
            multiline=True,
            size_hint_y=None,
            height=dp(290),
            font_size=dp(13),
            hint_text="def on_bar(ctx):",
            padding=(dp(12), dp(12)),
            background_normal="",
            background_active="",
            background_color=(0.045, 0.065, 0.10, 1),
            foreground_color=(0.80, 0.90, 0.87, 1),
            hint_text_color=_COLORS["muted"],
            cursor_color=_COLORS["accent"],
        )
        strategy_card.add_widget(self.script_input)

        saved_scripts_row = BoxLayout(
            spacing=dp(10),
            size_hint_y=None,
            height=dp(46),
        )
        self.saved_scripts_spinner = Spinner(
            text="Saved scripts",
            values=(),
            background_normal="",
            background_color=_COLORS["surface_alt"],
            color=_COLORS["text"],
        )
        load_button = self._button("Load", secondary=True)
        load_button.bind(on_release=self._load_script)
        saved_scripts_row.add_widget(self.saved_scripts_spinner)
        saved_scripts_row.add_widget(load_button)
        strategy_card.add_widget(saved_scripts_row)
        save_button = self._button("Save script", secondary=True)
        save_button.bind(on_release=self._save_script)
        strategy_card.add_widget(save_button)
        content.add_widget(strategy_card)

        self.run_button = self._button("Run backtest", height=dp(54))
        self.run_button.bind(on_release=self._start_backtest)
        content.add_widget(self.run_button)

        result_card = self._card()
        result_card.add_widget(self._section_heading("RESULTS", "Latest run"))
        self.status_label = self._label(
            "Your backtest summary will appear here.",
            dp(100),
            dp(13),
            _COLORS["muted"],
        )
        result_card.add_widget(self.status_label)
        result_card.add_widget(
            self._label(
                "Simulation only • one unit • no fees or slippage • no real orders",
                dp(32),
                dp(10),
                _COLORS["muted"],
            )
        )
        content.add_widget(result_card)
        content.add_widget(
            self._label(
                "Scripts and backtests stay on this device.",
                dp(30),
                dp(11),
                _COLORS["muted"],
                halign="center",
            )
        )
        self._restore_local_state()
        Clock.schedule_once(self._refresh_price, 0)
        self._price_event = Clock.schedule_interval(self._refresh_price, 10)
        return scroll

    def _card(self) -> BoxLayout:
        card = BoxLayout(
            orientation="vertical",
            padding=(dp(14), dp(14)),
            spacing=dp(10),
            size_hint_y=None,
        )
        card.bind(minimum_height=card.setter("height"))
        with card.canvas.before:
            Color(*_COLORS["surface"])
            background = RoundedRectangle(
                pos=card.pos,
                size=card.size,
                radius=[dp(16)],
            )
        card.bind(
            pos=lambda widget, value: setattr(background, "pos", value),
            size=lambda widget, value: setattr(background, "size", value),
        )
        return card

    def _section_heading(self, eyebrow: str, title: str) -> BoxLayout:
        heading = BoxLayout(
            orientation="vertical",
            spacing=dp(2),
            size_hint_y=None,
            height=dp(42),
        )
        heading.add_widget(self._label(eyebrow, dp(18), dp(10), _COLORS["accent"]))
        heading.add_widget(
            self._label(
                f"[b]{title}[/b]",
                dp(22),
                dp(17),
                _COLORS["text"],
                markup=True,
            )
        )
        return heading

    @staticmethod
    def _label(
        text: str,
        height: float,
        font_size: float = dp(14),
        color: tuple[float, float, float, float] = _COLORS["text"],
        halign: str = "left",
        markup: bool = False,
    ) -> Label:
        label = Label(
            text=text,
            markup=markup,
            size_hint_y=None,
            height=height,
            font_size=font_size,
            color=color,
            halign=halign,
            valign="middle",
        )
        label.bind(
            width=lambda widget, width: setattr(
                widget, "text_size", (max(0, width - dp(4)), None)
            )
        )
        return label

    @staticmethod
    def _text_input(
        text: str,
        hint: str,
        height: float | None = dp(46),
    ) -> TextInput:
        options = {
            "text": text,
            "multiline": False,
            "hint_text": hint,
            "font_size": dp(15),
            "padding": (dp(10), dp(12)),
            "background_normal": "",
            "background_active": "",
            "background_color": _COLORS["surface_alt"],
            "foreground_color": _COLORS["text"],
            "hint_text_color": _COLORS["muted"],
            "cursor_color": _COLORS["accent"],
        }
        if height is None:
            options["size_hint_y"] = 1
        else:
            options["size_hint_y"] = None
            options["height"] = height
        return TextInput(
            **options,
        )

    @staticmethod
    def _button(
        text: str,
        secondary: bool = False,
        height: float = dp(46),
    ) -> Button:
        return Button(
            text=text,
            size_hint_y=None,
            height=height,
            background_normal="",
            background_down="",
            background_color=(
                _COLORS["surface_alt"] if secondary else _COLORS["accent"]
            ),
            color=_COLORS["text"] if secondary else _COLORS["accent_text"],
            bold=True,
            font_size=dp(14),
        )

    def on_stop(self) -> None:
        self._price_event.cancel()
        self._store.close()

    def _refresh_price(self, _dt: float) -> None:
        if self._price_loading:
            return
        symbol = self.symbol_input.text.strip().upper()
        self._price_loading = True
        self.refresh_button.disabled = True
        self.price_detail_label.text = "Fetching latest public price…"
        self.price_detail_label.color = _COLORS["muted"]
        threading.Thread(
            target=self._load_price,
            args=(symbol,),
            daemon=True,
        ).start()

    def _load_price(self, symbol: str) -> None:
        try:
            price = fetch_latest_price(symbol)
            value = f"{price:.8g}"
            detail = f"{symbol} spot • refreshed every 10 seconds"
            success = True
        except MarketDataError as exc:
            value = "—"
            detail = f"Price unavailable: {exc}"
            success = False
        Clock.schedule_once(
            lambda _dt: self._set_price(symbol, value, detail, success),
            0,
        )

    def _set_price(self, symbol: str, value: str, detail: str, success: bool) -> None:
        self._price_loading = False
        self.refresh_button.disabled = False
        current_symbol = self.symbol_input.text.strip().upper()
        if symbol != current_symbol:
            self._refresh_price(0)
            return
        self.price_label.text = value
        self.price_detail_label.text = detail
        self.price_detail_label.color = (
            _COLORS["success"] if success else _COLORS["error"]
        )

    def _save_script(self, _button: Button) -> None:
        try:
            source = self.script_input.text
            compile_strategy(source)
            self._store.save_script(self.script_name_input.text, source)
        except (StrategyError, ValueError, OSError, sqlite3.Error) as exc:
            self._set_status(f"Could not save script: {exc}")
            return
        name = self.script_name_input.text.strip()
        self._refresh_saved_scripts(name)
        self._set_status(f"Saved '{name}' on this device.")

    def _refresh_saved_scripts(self, selected_name: str | None = None) -> None:
        scripts = self._store.list_scripts()
        names = tuple(name for name, _source in scripts)
        self.saved_scripts_spinner.values = names
        if selected_name in names:
            self.saved_scripts_spinner.text = selected_name
        elif names and self.saved_scripts_spinner.text not in names:
            self.saved_scripts_spinner.text = names[0]
        elif not names:
            self.saved_scripts_spinner.text = "Saved scripts"

    def _load_script(self, _button: Button) -> None:
        name = self.saved_scripts_spinner.text
        if name not in self.saved_scripts_spinner.values:
            self._set_status("Choose a saved script first.")
            return
        try:
            source = self._store.load_script(name)
        except sqlite3.Error as exc:
            self._set_status(f"Could not load script: {exc}")
            return
        if source is None:
            self._set_status(f"Saved script '{name}' was not found.")
            self._refresh_saved_scripts()
            return
        self.script_name_input.text = name
        self.script_input.text = source
        self._set_status(f"Loaded '{name}' from this device.")

    def _restore_local_state(self) -> None:
        try:
            self._refresh_saved_scripts()
            scripts = self._store.list_scripts()
            if scripts:
                self._load_script(self.saved_scripts_spinner)
            runs = self._store.list_backtests(1)
        except (sqlite3.Error, ValueError) as exc:
            self._set_status(f"Could not restore local data: {exc}")
            return
        if runs:
            result = runs[0]["result"]
            trades = result["trades"]
            wins = sum(1 for trade in trades if trade["profit"] > 0)
            win_rate = wins / len(trades) if trades else 0.0
            self._set_status(
                f"Last saved run: {result['symbol']} {result['interval']} • "
                f"{result['candles_tested']} candles\n"
                f"Signals: {len(result['signals'])} • Simulated trades: {len(trades)}\n"
                f"Net P/L: {result['net_profit']:.8g} quote units • "
                f"Win rate: {win_rate:.1%}"
            )

    def _start_backtest(self, _button: Button) -> None:
        if self._busy:
            return
        symbol = self.symbol_input.text.strip().upper()
        interval = self.interval_input.text
        source = self.script_input.text
        try:
            program = compile_strategy(source)
        except StrategyError as exc:
            self._set_status(f"Script error: {exc}")
            return

        try:
            self._store.save_script(self.script_name_input.text, source)
            self._refresh_saved_scripts(self.script_name_input.text.strip())
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._set_status(f"Could not save script: {exc}")
            return

        self._busy = True
        self.run_button.disabled = True
        self.run_button.text = "Running backtest…"
        self._set_status("Downloading up to 500 candles and running the backtest…")
        threading.Thread(
            target=self._run_backtest_worker,
            args=(symbol, interval, program),
            daemon=True,
        ).start()

    def _run_backtest_worker(
        self,
        symbol: str,
        interval: str,
        program: StrategyProgram,
    ) -> None:
        store: LocalStore | None = None
        cache_notice = ""
        message = "Backtest failed unexpectedly."
        try:
            store = LocalStore(self._database_path)
            try:
                candles = fetch_candles(symbol, interval, limit=500)
                store.save_candles(symbol, interval, candles)
            except MarketDataError as exc:
                candles = store.load_candles(symbol, interval, limit=500)
                if not candles:
                    raise
                cache_notice = f"\nUsing {len(candles)} cached candles; refresh failed: {exc}"

            result = run_backtest(program, candles, symbol, interval)
            store.save_backtest(result)
            summary = [
                f"{symbol} {interval} • {result.candles_tested} candles",
                f"Signals: {len(result.signals)} • Simulated trades: {len(result.trades)}",
                f"Net P/L: {result.net_profit:.8g} quote units • Win rate: {result.win_rate:.1%}",
                "One-unit fills; no fees, slippage, leverage, or broker execution.",
            ]
            if result.signals:
                summary.append("Recent signals:")
                for signal in result.signals[-5:]:
                    summary.append(
                        f"{signal.side} @ {signal.price:.8g} — {signal.message or '(no message)'}"
                    )
            else:
                summary.append("No signals were produced by this script.")
            if result.plots:
                latest_values = {}
                for point in result.plots:
                    latest_values[point.name] = point.value
                summary.append("Latest indicator values:")
                for name, value in list(latest_values.items())[-5:]:
                    formatted_value = "warming up" if value is None else f"{value:.8g}"
                    summary.append(f"{name}: {formatted_value}")
            message = "\n".join(summary) + cache_notice
        except (MarketDataError, StrategyError, OSError, sqlite3.Error, ValueError) as exc:
            message = f"Backtest failed: {exc}"
        finally:
            if store is not None:
                store.close()
        Clock.schedule_once(lambda _dt, text=message: self._finish_backtest(text), 0)

    def _finish_backtest(self, message: str) -> None:
        self._busy = False
        self.run_button.disabled = False
        self.run_button.text = "Run backtest"
        self._set_status(message)

    def _set_status(self, message: str) -> None:
        self.status_label.text = message
        if message.startswith(("Could not", "Script error", "Backtest failed")):
            self.status_label.color = _COLORS["error"]
        elif message.startswith(("Saved ", "Loaded ")):
            self.status_label.color = _COLORS["success"]
        elif message.startswith("Downloading"):
            self.status_label.color = _COLORS["accent"]
        else:
            self.status_label.color = _COLORS["text"]
        line_count = max(1, len(message.splitlines()))
        self.status_label.height = dp(min(360, max(100, line_count * 24)))
