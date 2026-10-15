from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg

pg.setConfigOptions(useOpenGL=False, antialias=False, foreground="#000000", background="#ffffff")

import finplot as fplt
from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtWidgets import QLabel, QSplitter, QVBoxLayout, QWidget

from krx_research_nextgen.models.chart_data import ChartBundle, TIMEFRAME_LABELS
from krx_research_nextgen.presentation.number_format import format_number


UP, DOWN, FLAT = "#d62728", "#1f77b4", "#808080"
BOLLINGER = "#5f88b1"
EMA_WINDOWS = (5, 10, 15, 33, 56, 112, 224, 448)
EMA_COLORS = ("#ffff00", "#00ff00", "#0000ff", "#388e8e", "#e600e6", "#ff8042", "#a52a00", "#b30000")
INVESTOR_COLORS = {"institution": "#8e44ad", "foreign": "#00897b", "individual": "#ef6c00"}
INVESTOR_LABELS = {"institution": "기관", "foreign": "외국인", "individual": "개인"}
Y_AXIS_WIDTH = 64


def _price_colors(_item, _datasrc, frame):
    open_col, close_col = frame.columns[1:3]
    for mask, color in (
        (frame[close_col] > frame[open_col], UP),
        (frame[close_col] < frame[open_col], DOWN),
        (frame[close_col] == frame[open_col], FLAT),
    ):
        yield [color, color, color, frame.loc[mask]]


def _volume_colors(_item, _datasrc, frame):
    open_col, close_col = frame.columns[3:5]
    for mask, color in (
        (frame[close_col] > frame[open_col], UP),
        (frame[close_col] < frame[open_col], DOWN),
        (frame[close_col] == frame[open_col], FLAT),
    ):
        yield [color, color, color, frame.loc[mask]]


class EmbeddedFinplotWidget(QWidget):
    """Finplot renderer matching the established legacy chart presentation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(3)
        self.instrument_title = QLabel()
        self.instrument_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.instrument_title.setStyleSheet("font-size:14px;font-weight:700;background:white")
        self.instrument_title.setFixedHeight(24); layout.addWidget(self.instrument_title)
        axes = fplt.create_plot_widget(master=self, rows=6, init_zoom_periods=500)
        if not isinstance(axes, (tuple, list)) or len(axes) != 6:
            raise RuntimeError("Finplot did not return six embedded axes.")
        self.ax_price, self.ax_volume, self.ax_rsi, self.ax_stochastic, self.ax_investor, self.ax_macd = axes
        self.axs = list(axes)
        self.panel_splitter = QSplitter(Qt.Orientation.Vertical)
        self.panel_splitter.setChildrenCollapsible(False); self.panel_splitter.setOpaqueResize(True)
        self.panel_splitter.setHandleWidth(5)
        self.panel_splitter.setStyleSheet("QSplitter::handle:vertical{background:#d9d9d9}")
        layout.addWidget(self.panel_splitter, 1)
        for index, ax in enumerate(self.axs, 1):
            self.panel_splitter.addWidget(ax.ax_widget)
            self.panel_splitter.setStretchFactor(index - 1, 4 if index == 1 else 1)
            ax.vb.setBackgroundColor("#ffffff")
            ax.showGrid(x=True, y=True, alpha=0.18)
            ax.showAxis("left"); ax.hideAxis("right")
            ax.getAxis("left").setWidth(Y_AXIS_WIDTH); ax.getAxis("right").setWidth(0)
            for side in ("left", "right", "bottom"):
                try:
                    axis = ax.getAxis(side); axis.setStyle(tickFont=axis.tickFont)
                    axis.setPen(pg.mkPen("#000000", width=0.6)); axis.setTextPen(pg.mkPen("#000000"))
                except Exception:
                    pass
        self._overlays = {
            self.ax_price: self._overlay(self.ax_price),
            self.ax_investor: self._overlay(self.ax_investor),
            self.ax_macd: self._overlay(self.ax_macd),
        }
        self._latest = {
            self.ax_rsi: self._overlay(self.ax_rsi),
            self.ax_stochastic: self._overlay(self.ax_stochastic),
            self.ax_macd: self._overlay(self.ax_macd),
        }
        self._investor_plots: dict[str, object] = {}
        self.strategy_overlay = self._overlay(self.ax_price)
        self.strategy_overlay.setWordWrap(True)
        self.strategy_overlay.setTextFormat(Qt.TextFormat.PlainText)
        self.strategy_overlay.setStyleSheet("background:rgba(255,255,255,215);border:1px solid #bdbdbd;padding:3px;font-size:10px")
        self.strategy_overlay.hide()
        self._strategy_items: list[tuple[object, object]] = []
        for ax in self.axs: ax.ax_widget.installEventFilter(self)
        self.panel_splitter.setSizes([480, 115, 115, 115, 115, 115])
        self.ax_investor.ax_widget.hide()
        self._initialized = False

    @staticmethod
    def _overlay(ax) -> QLabel:
        label = QLabel(ax.ax_widget); label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label.setTextFormat(Qt.TextFormat.RichText); label.setStyleSheet("background:transparent;font-size:10px")
        label.show(); return label

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_labels()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Resize and any(watched is ax.ax_widget for ax in self.axs):
            QTimer.singleShot(0, self._position_labels)
        return super().eventFilter(watched, event)

    def _position_labels(self) -> None:
        for ax, label in self._overlays.items():
            x = Y_AXIS_WIDTH + 8 if ax in (self.ax_price, self.ax_investor) else 8
            label.setGeometry(x, 2, max(0, ax.ax_widget.width() - x - 10), max(0, ax.ax_widget.height() - 8))
            label.raise_()
        for ax, label in self._latest.items():
            label.adjustSize(); label.move(max(8, ax.ax_widget.width() - label.width() - 10), max(4, ax.ax_widget.height() - label.height() - 6))
            label.raise_()
        x, width = Y_AXIS_WIDTH + 8, min(900, max(0, self.ax_price.ax_widget.width() - Y_AXIS_WIDTH - 18))
        self.strategy_overlay.setFixedWidth(width); self.strategy_overlay.adjustSize()
        self.strategy_overlay.setGeometry(x, 24, width, min(100, self.strategy_overlay.sizeHint().height() + 8))
        self.strategy_overlay.raise_()

    def _sync_bottom_axis(self) -> None:
        visible = [ax for ax in self.axs if not ax.ax_widget.isHidden()]
        for ax in self.axs: ax.set_visible(xaxis=bool(visible and ax is visible[-1]))

    def initialize_finplot(self) -> None:
        if not self._initialized:
            fplt.show(qt_exec=False); self._initialized = True

    def clear(self) -> None:
        for ax in self.axs: ax.reset()
        self._strategy_items.clear()
        for label in self._overlays.values(): label.clear()
        for label in self._latest.values(): label.clear()
        self.strategy_overlay.clear(); self.strategy_overlay.hide()

    def set_strategy_text(self, text: str) -> None:
        self.strategy_overlay.setText(text); self.strategy_overlay.setVisible(bool(text)); self._position_labels()

    def set_strategy(self, assessment, frame: pd.DataFrame) -> None:
        for axis, item in self._strategy_items:
            try: axis.removeItem(item)
            except Exception: pass
        self._strategy_items.clear()
        if assessment is None: self.set_strategy_text(""); fplt.refresh(); return
        self.set_strategy_text(assessment.overlay_text())
        color = {"엘리어트 파동": "#6a1b9a", "제시 리버모어": "#2e7d32", "알렉산더 엘더": "#ef6c00"}[assessment.strategy]
        points = [point for point in assessment.points if frame.index.min() <= point[0] <= frame.index.max()]
        if len(points) > 1:
            plot = fplt.plot(pd.Series([point[1] for point in points], index=pd.DatetimeIndex(point[0] for point in points)), ax=self.ax_price, color=color, width=2)
            self._strategy_items.append((self.ax_price, plot))
            x_values = plot.getData()[0]
            for x, (_, price, label) in zip(x_values, points, strict=False):
                marker = pg.TextItem(label, color=color, anchor=(.5, 1)); marker.setPos(float(x), price)
                self.ax_price.addItem(marker); self._strategy_items.append((self.ax_price, marker))
        axes = {"price": self.ax_price, "volume": self.ax_volume, "stochastic": self.ax_stochastic, "macd": self.ax_macd}
        for panel, value, label in assessment.levels:
            line = pg.InfiniteLine(pos=value, angle=0, pen=pg.mkPen(color, width=1.2, style=Qt.PenStyle.DashLine), label=label, labelOpts={"position": .88, "color": color})
            axes[panel].addItem(line); self._strategy_items.append((axes[panel], line))
        fplt.refresh()

    def render(self, bundle: ChartBundle, *, profile_bins: int = 15, timeframe: str = "D") -> None:
        df = bundle.frame.copy(); self._validate(df)
        if not 6 <= profile_bins <= 20:
            raise ValueError("매물대 구간 수는 6~20 사이여야 합니다.")
        selected = timeframe.strip().upper()
        if selected not in TIMEFRAME_LABELS: raise ValueError(f"Unsupported chart timeframe: {timeframe}")
        self.clear(); self.instrument_title.setText(f"{bundle.symbol} · {TIMEFRAME_LABELS[selected]}")

        candles = fplt.candlestick_ochl(
            df[["open", "close", "high", "low"]], candle_width=0.72,
            ax=self.ax_price, colorfunc=_price_colors,
        )
        candles.shadow_width = 0.55
        fplt.plot(df["bb_upper"], ax=self.ax_price, color=BOLLINGER, width=0.9, style="--")
        fplt.plot(df["bb_lower"], ax=self.ax_price, color=BOLLINGER, width=0.9, style="--")
        for window, color in zip(EMA_WINDOWS, EMA_COLORS, strict=True):
            fplt.plot(
                df[f"ema_{window}"], ax=self.ax_price, color=color, width=0.82,
                style="--" if window == 448 else "-",
            )
        self._overlays[self.ax_price].setText(
            " &nbsp; ".join(f'<span style="color:{color};font-weight:600">- {window}</span>' for window, color in zip(EMA_WINDOWS, EMA_COLORS, strict=True))
        )
        self._overlays[self.ax_price].raise_()
        volume = fplt.volume_ocv(
            df[["open", "close", "volume"]], candle_width=0.82,
            ax=self.ax_volume, colorfunc=_volume_colors,
        )
        volume.shadow_width = 0

        fplt.plot(df["rsi"], ax=self.ax_rsi, color="#6a1b9a", width=0.9)
        fplt.plot(df["rsi_signal"], ax=self.ax_rsi, color="#ff9800", width=0.85)
        self.ax_rsi.addLine(y=70, pen=pg.mkPen("#555555", width=0.65, style=Qt.PenStyle.DashLine))
        self.ax_rsi.addLine(y=30, pen=pg.mkPen("#555555", width=0.65, style=Qt.PenStyle.DashLine))
        self._indicator_latest(self.ax_rsi, "RSI(14)", "#6a1b9a", df["rsi"], "Signal(9)", "#ff9800", df["rsi_signal"])

        fplt.plot(df["stoch_slow_k"], ax=self.ax_stochastic, color="#1f77b4", width=0.85)
        fplt.plot(df["stoch_slow_d"], ax=self.ax_stochastic, color="#d62728", width=0.85)
        self.ax_stochastic.addLine(y=80, pen=pg.mkPen("#555555", width=0.65, style=Qt.PenStyle.DashLine))
        self.ax_stochastic.addLine(y=20, pen=pg.mkPen("#555555", width=0.65, style=Qt.PenStyle.DashLine))
        self._indicator_latest(self.ax_stochastic, "Slow %K(5,3)", "#1f77b4", df["stoch_slow_k"], "Slow %D(3)", "#d62728", df["stoch_slow_d"])

        self._histogram(self.ax_macd, df["macd_hist"], 0.82)
        self.ax_macd.addLine(y=0, pen=pg.mkPen("#555555", width=0.6))
        latest_macd = pd.to_numeric(df["macd_hist"], errors="coerce").dropna()
        self._latest[self.ax_macd].setText(
            "" if latest_macd.empty else f'<span style="background:#f5f5f5;color:#333333"><b>MACD {latest_macd.iloc[-1]:.1f}</b></span>'
        )
        self._render_investor(bundle.investor_flow, df.index)
        self._volume_profile(df, profile_bins)
        fplt.refresh()
        for ax in self.axs:
            ax.showAxis("left"); ax.hideAxis("right")
            ax.getAxis("left").setWidth(Y_AXIS_WIDTH); ax.getAxis("right").setWidth(0)
        self._sync_bottom_axis()
        self.ax_rsi.vb.setRange(yRange=(-2, 102), padding=0)
        self.ax_stochastic.vb.setRange(yRange=(-2, 102), padding=0)
        macd = pd.to_numeric(df["macd_hist"], errors="coerce").fillna(0.0)
        low, high = min(0.0, float(macd.min())), max(0.0, float(macd.max()))
        pad = max((high - low) * 0.05, 1.0)
        self.ax_macd.vb.setRange(yRange=(low - pad, high + pad), padding=0)
        self.ax_rsi.getAxis("left").setTicks([[(0, "0"), (30, "30"), (70, "70"), (100, "100")]])
        self.ax_stochastic.getAxis("left").setTicks([[(0, "0"), (20, "20"), (80, "80"), (100, "100")]])
        self._position_labels()
        self.setToolTip(bundle.symbol)

    def set_panel_visibility(
        self, *, volume: bool, rsi: bool, stochastic: bool, macd: bool,
        institution: bool = False, foreign: bool = False, individual: bool = False,
    ) -> None:
        for axis, visible in (
            (self.ax_volume, volume), (self.ax_rsi, rsi),
            (self.ax_stochastic, stochastic), (self.ax_macd, macd),
        ):
            axis.ax_widget.setVisible(visible)
        selected = {"institution": institution, "foreign": foreign, "individual": individual}
        for key, plot in self._investor_plots.items(): plot.setVisible(selected[key])
        self.ax_investor.ax_widget.setVisible(any(selected.values()))
        self._sync_bottom_axis(); QTimer.singleShot(0, self._position_labels)

    def _render_investor(self, flow: pd.DataFrame, chart_index: pd.DatetimeIndex) -> None:
        self._investor_plots.clear()
        legends = []
        for key, color in INVESTOR_COLORS.items():
            stored = pd.to_numeric(flow.get(key, pd.Series(dtype=float)), errors="coerce").dropna()
            if stored.empty: continue
            values = pd.to_numeric(flow.get(key), errors="coerce").reindex(chart_index) / 100_000_000
            self._investor_plots[key] = fplt.plot(values, ax=self.ax_investor, color=color, width=1.2)
            legends.append(f'<span style="color:{color}">{INVESTOR_LABELS[key]} {format_number(stored.iloc[-1] / 100_000_000, 1)}억</span>')
        self.ax_investor.addLine(y=0, pen=pg.mkPen("#555555", width=0.6))
        self._overlays[self.ax_investor].setText(" &nbsp; ".join(legends) if legends else "선택 기간의 투자자 수급 원천자료가 없습니다.")

    def _indicator_latest(self, ax, left, left_color, left_values, right, right_color, right_values) -> None:
        a, b = pd.to_numeric(left_values, errors="coerce").dropna(), pd.to_numeric(right_values, errors="coerce").dropna()
        self._latest[ax].setText(
            "" if a.empty or b.empty else
            f'<span style="background:#f5f5f5;color:{left_color}"><b>{left} {a.iloc[-1]:.1f}</b></span><br>'
            f'<span style="background:#f5f5f5;color:{right_color}"><b>{right} {b.iloc[-1]:.1f}</b></span>'
        )

    @staticmethod
    def _histogram(ax, values: pd.Series, width: float) -> None:
        series = pd.to_numeric(values, errors="coerce").fillna(0.0)
        frame = pd.DataFrame({"open": 0.0, "close": series, "value": series}, index=values.index)
        fplt.volume_ocv(frame, candle_width=width, ax=ax, colorfunc=_volume_colors)

    def _volume_profile(self, frame: pd.DataFrame, bins: int) -> None:
        low, high = float(frame["low"].min()), float(frame["high"].max())
        if not np.isfinite(low + high): return
        if high <= low: high = low + max(abs(low) * 0.01, 1.0)
        edges = np.linspace(low, high, bins + 1)
        lows, highs = frame["low"].to_numpy(float), frame["high"].to_numpy(float)
        overlap = np.clip(np.minimum(highs[:, None], edges[None, 1:]) - np.maximum(lows[:, None], edges[None, :-1]), 0, None)
        total = overlap.sum(axis=1)
        weights = np.divide(overlap, total[:, None], out=np.zeros_like(overlap), where=total[:, None] > 0)
        volumes = (weights * frame["volume"].to_numpy(float)[:, None]).sum(axis=0)
        if not volumes.max(): return
        centers = (edges[:-1] + edges[1:]) / 2
        widths = volumes / volumes.max() * max(1, (len(frame) - 1) * 0.17)
        brush = pg.mkBrush(232, 232, 232, 13)
        self.ax_price.addItem(pg.BarGraphItem(x0=np.zeros(bins), x1=widths, y=centers, height=(edges[1]-edges[0])*0.84, brush=brush, pen=None))

    @staticmethod
    def _validate(df: pd.DataFrame) -> None:
        required = {
            "open", "high", "low", "close", "volume", "rsi", "rsi_signal",
            "macd_hist", "stoch_slow_k", "stoch_slow_d", "bb_upper", "bb_lower",
            *(f"ema_{window}" for window in EMA_WINDOWS),
        }
        missing = sorted(required.difference(df.columns))
        if missing: raise ValueError(f"Embedded chart data missing columns: {missing}")
        if not isinstance(df.index, pd.DatetimeIndex): raise TypeError("EmbeddedFinplotWidget requires a DatetimeIndex.")
