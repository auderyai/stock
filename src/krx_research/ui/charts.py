"""Matplotlib charts for the local KRX workstation GUI."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from pandas import DataFrame

from krx_research.analytics import EMA_WINDOWS

from .chart_options import ChartDisplayOptions
from .data import ChartDataset, calculate_volume_profile, select_chart_window
from .on_demand import TIMEFRAME_LABELS

UP_COLOR = "#d62728"
DOWN_COLOR = "#1f77b4"
FLAT_COLOR = "#808080"
PROFILE_COLOR = "#e8e8e8"
# User setting: 95% transparent means 5% opacity in Matplotlib.
PROFILE_ALPHA = 0.05
BOLLINGER_COLOR = "#5f88b1"
MIN_PROFILE_BINS = 6
MAX_PROFILE_BINS = 20
DEFAULT_PROFILE_BINS = 15
EMA_COLORS = (
    "#ffff00",
    "#00ff00",
    "#0000ff",
    "#388e8e",
    "#e600e6",
    "#ff8042",
    "#a52a00",
    "#b30000",
)
EMA_LINESTYLES = ("-", "-", "-", "-", "-", "-", "-", "--")
KOREAN_FONT_CANDIDATES = (
    "Malgun Gothic",
    "맑은 고딕",
    "AppleGothic",
    "Noto Sans CJK KR",
    "Noto Sans KR",
    "NanumGothic",
)
WINDOWS_KOREAN_FONT_FILES = ("malgun.ttf", "malgunsl.ttf")


@lru_cache(maxsize=1)
def _korean_font_family() -> str | None:
    available = {font.name for font in font_manager.fontManager.ttflist}
    return next((name for name in KOREAN_FONT_CANDIDATES if name in available), None)


@lru_cache(maxsize=1)
def _korean_font_path() -> str | None:
    windows_root = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for filename in WINDOWS_KOREAN_FONT_FILES:
        candidate = windows_root / "Fonts" / filename
        if candidate.is_file():
            return str(candidate)
    return None


def _korean_font_properties(size: float | None = None) -> FontProperties | None:
    if path := _korean_font_path():
        return FontProperties(fname=path, size=size)
    if family := _korean_font_family():
        return FontProperties(family=family, size=size)
    return None


def _draw_candles(axis, frame: DataFrame, *, width: float) -> None:
    x = np.asarray(frame.index, dtype="float64")
    opens = frame["open"].to_numpy(dtype="float64")
    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    closes = frame["close"].to_numpy(dtype="float64")
    colors = np.where(closes > opens, UP_COLOR, np.where(closes < opens, DOWN_COLOR, FLAT_COLOR))
    wicks = [[(date, low), (date, high)] for date, low, high in zip(x, lows, highs, strict=True)]
    bodies = []
    for date, open_price, close_price in zip(x, opens, closes, strict=True):
        bottom = min(open_price, close_price)
        top = max(open_price, close_price)
        if top == bottom:
            top = bottom + max(abs(bottom) * 0.0002, 0.1)
        bodies.append(
            [
                (date - width / 2, bottom),
                (date - width / 2, top),
                (date + width / 2, top),
                (date + width / 2, bottom),
            ]
        )
    axis.add_collection(LineCollection(wicks, colors=colors, linewidths=0.55, zorder=2))
    axis.add_collection(
        PolyCollection(
            bodies,
            facecolors=colors,
            edgecolors=colors,
            linewidths=0.35,
            zorder=3,
        )
    )
    axis.update_datalim(np.column_stack([x, lows]))
    axis.update_datalim(np.column_stack([x, highs]))
    axis.autoscale_view()


def _session_frame(frame: DataFrame) -> DataFrame:
    """Replace calendar spacing with consecutive exchange-session positions."""

    result = frame.copy()
    dates = pd.DatetimeIndex(pd.to_datetime(result.index, errors="coerce"))
    if dates.isna().any():
        raise ValueError("차트 자료에 올바르지 않은 거래일이 있습니다.")
    result.attrs.update(getattr(frame, "attrs", {}))
    result.attrs["trade_dates"] = dates
    result.index = pd.RangeIndex(len(result), name="session")
    return result


def _trade_dates(frame: DataFrame) -> pd.DatetimeIndex:
    stored = frame.attrs.get("trade_dates")
    if stored is not None:
        return pd.DatetimeIndex(pd.to_datetime(stored, errors="coerce"))
    return pd.DatetimeIndex(pd.to_datetime(frame.index, errors="coerce"))


def _style_session_axis(axis, trade_dates: pd.DatetimeIndex) -> None:
    if len(trade_dates):
        tick_count = min(10, len(trade_dates))
        positions = np.unique(
            np.linspace(0, len(trade_dates) - 1, tick_count).round().astype(int)
        )
        axis.set_xticks(positions)
        axis.set_xticklabels(
            [pd.Timestamp(trade_dates[position]).strftime("%Y-%m-%d") for position in positions]
        )
    axis.grid(True, color="#ececec", linewidth=0.6)
    axis.tick_params(labelsize=8)
    axis.ticklabel_format(axis="y", style="plain", useOffset=False)


def _build_legacy_chart_figure(
    dataset: ChartDataset,
    trading_days: int | None = 800,
    *,
    profile_bins: int = DEFAULT_PROFILE_BINS,
) -> Figure:
    """Build synchronized price, volume, MACD, RSI, and stochastic panels."""

    if not MIN_PROFILE_BINS <= profile_bins <= MAX_PROFILE_BINS:
        raise ValueError(
            f"매물대 구간 수는 {MIN_PROFILE_BINS}~{MAX_PROFILE_BINS} 사이여야 합니다."
        )
    daily_source, weekly_source = select_chart_window(dataset, trading_days)
    daily_dates = pd.DatetimeIndex(daily_source.index)
    weekly_dates = pd.DatetimeIndex(weekly_source.index)
    daily = _session_frame(daily_source)
    weekly = _session_frame(weekly_source) if not weekly_source.empty else weekly_source
    figure = Figure(figsize=(15, 10.5), dpi=100, facecolor="white")
    grid = figure.add_gridspec(
        6,
        1,
        height_ratios=[4.7, 2.5, 1.15, 1.15, 1.15, 1.15],
        hspace=0.08,
    )
    daily_axis = figure.add_subplot(grid[0])
    weekly_axis = figure.add_subplot(grid[1])
    volume_axis = figure.add_subplot(grid[2], sharex=daily_axis)
    macd_axis = figure.add_subplot(grid[3], sharex=daily_axis)
    rsi_axis = figure.add_subplot(grid[4], sharex=daily_axis)
    stochastic_axis = figure.add_subplot(grid[5], sharex=daily_axis)

    _draw_candles(daily_axis, daily, width=0.72)
    daily_axis.plot(
        daily.index,
        daily["bb_upper_20_2"],
        color=BOLLINGER_COLOR,
        linestyle="--",
        linewidth=0.9,
        zorder=3,
    )
    daily_axis.plot(
        daily.index,
        daily["bb_lower_20_2"],
        color=BOLLINGER_COLOR,
        linestyle="--",
        linewidth=0.9,
        zorder=3,
    )
    for window, color, linestyle in zip(
        EMA_WINDOWS,
        EMA_COLORS,
        EMA_LINESTYLES,
        strict=True,
    ):
        daily_axis.plot(
            daily.index,
            daily[f"ema_{window}"],
            color=color,
            linestyle=linestyle,
            linewidth=0.82,
            label=str(window),
            zorder=4,
        )
    daily_axis.legend(
        loc="upper left",
        ncol=8,
        fontsize=7,
        frameon=False,
        handlelength=1.5,
        columnspacing=0.8,
    )

    if not weekly.empty:
        _draw_candles(weekly_axis, weekly, width=0.72)
        weekly_axis.plot(
            weekly.index,
            weekly["bb_upper_20_2"],
            color=BOLLINGER_COLOR,
            linestyle="--",
            linewidth=0.9,
            zorder=3,
        )
        weekly_axis.plot(
            weekly.index,
            weekly["bb_lower_20_2"],
            color=BOLLINGER_COLOR,
            linestyle="--",
            linewidth=0.9,
            zorder=3,
        )
        for window, color, linestyle in zip(
            EMA_WINDOWS,
            EMA_COLORS,
            EMA_LINESTYLES,
            strict=True,
        ):
            weekly_axis.plot(
                weekly.index,
                weekly[f"ema_{window}"],
                color=color,
                linestyle=linestyle,
                linewidth=0.82,
                label=str(window),
                zorder=4,
            )
        weekly_axis.legend(
            loc="upper left",
            ncol=8,
            fontsize=7,
            frameon=False,
            handlelength=1.5,
            columnspacing=0.8,
        )

    volume_axis.bar(
        daily.index,
        daily["volume"],
        width=0.82,
        color=daily["volume_color"],
        linewidth=0,
    )
    oscillator = daily["macd_oscillator"]
    macd_colors = np.where(
        oscillator > 0,
        UP_COLOR,
        np.where(oscillator < 0, DOWN_COLOR, FLAT_COLOR),
    )
    macd_axis.bar(
        daily.index,
        oscillator.fillna(0.0),
        width=0.82,
        color=macd_colors,
        linewidth=0,
    )
    macd_axis.axhline(0, color="#555555", linewidth=0.6)

    rsi_axis.plot(
        daily.index,
        daily["rsi_14"],
        color="#6a1b9a",
        linewidth=0.9,
        label="RSI(14)",
    )
    rsi_axis.plot(
        daily.index,
        daily["rsi_signal_9"],
        color="#ff9800",
        linewidth=0.85,
        label="Signal(9)",
    )
    rsi_axis.axhline(70, color="#555555", linestyle="--", linewidth=0.65)
    rsi_axis.axhline(30, color="#555555", linestyle="--", linewidth=0.65)
    rsi_axis.set_ylim(-2, 102)
    rsi_axis.set_yticks([0, 30, 70, 100])
    rsi_axis.legend(loc="upper left", fontsize=7, frameon=False)

    stochastic_axis.plot(
        daily.index,
        daily["stoch_slow_k"],
        color="#1f77b4",
        linewidth=0.85,
        label="Slow %K(5,3)",
    )
    stochastic_axis.plot(
        daily.index,
        daily["stoch_slow_d"],
        color="#d62728",
        linewidth=0.85,
        label="Slow %D(3)",
    )
    stochastic_axis.axhline(80, color="#555555", linestyle="--", linewidth=0.65)
    stochastic_axis.axhline(20, color="#555555", linestyle="--", linewidth=0.65)
    stochastic_axis.set_ylim(-2, 102)
    stochastic_axis.set_yticks([0, 20, 80, 100])
    stochastic_axis.legend(loc="upper left", ncol=2, fontsize=7, frameon=False)

    centers, profile_volume, height = calculate_volume_profile(
        daily,
        bins=profile_bins,
    )
    if len(centers):
        profile_axis = daily_axis.inset_axes([0.0, 0.03, 0.17, 0.94])
        profile_axis.barh(
            centers,
            profile_volume,
            height=height,
            color=PROFILE_COLOR,
            edgecolor=PROFILE_COLOR,
            alpha=PROFILE_ALPHA,
        )
        profile_axis.set_ylim(daily_axis.get_ylim())
        profile_axis.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
        profile_axis.patch.set_alpha(0)
        for spine in profile_axis.spines.values():
            spine.set_visible(False)

    for axis in (
        daily_axis,
        volume_axis,
        macd_axis,
        rsi_axis,
        stochastic_axis,
    ):
        _style_session_axis(axis, daily_dates)
    _style_session_axis(weekly_axis, weekly_dates)
    padding = max((len(daily) - 1) * 0.01, 0.72)
    daily_axis.set_xlim(-padding, len(daily) - 1 + padding)
    if len(weekly):
        weekly_padding = max((len(weekly) - 1) * 0.01, 0.72)
        weekly_axis.set_xlim(-weekly_padding, len(weekly) - 1 + weekly_padding)
    daily_axis.tick_params(labelbottom=False)
    volume_axis.tick_params(labelbottom=False)
    macd_axis.tick_params(labelbottom=False)
    rsi_axis.tick_params(labelbottom=False)
    title_options = {"fontsize": 14, "fontweight": "bold"}
    if title_font := _korean_font_properties(14):
        title_options["fontproperties"] = title_font
    figure.suptitle(f"{dataset.name} ({dataset.ticker})", **title_options)
    figure.subplots_adjust(left=0.055, right=0.985, top=0.955, bottom=0.055)
    return figure


def _visible_bars(
    dataset: ChartDataset,
    timeframe: str,
    bars: int | None,
) -> DataFrame:
    frame = dataset.bars(timeframe)
    if frame.empty:
        raise ValueError(
            f"{dataset.ticker}의 {TIMEFRAME_LABELS[timeframe]} 자료가 없습니다."
        )
    if bars is not None and bars < 1:
        raise ValueError("표시 봉수는 1 이상이어야 합니다.")
    return frame.copy() if bars is None else frame.tail(bars).copy()


def _adaptive_candle_width(frame: DataFrame) -> float:
    x = np.asarray(frame.index, dtype="float64")
    if len(x) < 2:
        return 0.72
    positive = np.diff(x)
    positive = positive[positive > 0]
    spacing = float(np.median(positive)) if len(positive) else 1.0
    return max(0.15, spacing * 0.72)


def _plot_price(axis, frame: DataFrame) -> None:
    _draw_candles(axis, frame, width=_adaptive_candle_width(frame))
    for column in ("bb_upper_20_2", "bb_lower_20_2"):
        if column in frame and frame[column].notna().any():
            axis.plot(
                frame.index,
                frame[column],
                color=BOLLINGER_COLOR,
                linestyle="--",
                linewidth=0.9,
                zorder=3,
            )
    plotted = False
    for window, color, linestyle in zip(
        EMA_WINDOWS,
        EMA_COLORS,
        EMA_LINESTYLES,
        strict=True,
    ):
        column = f"ema_{window}"
        if column not in frame or not frame[column].notna().any():
            continue
        axis.plot(
            frame.index,
            frame[column],
            color=color,
            linestyle=linestyle,
            linewidth=0.82,
            label=str(window),
            zorder=4,
        )
        plotted = True
    if plotted:
        axis.legend(
            loc="upper left",
            ncol=8,
            fontsize=7,
            frameon=False,
            handlelength=1.5,
            columnspacing=0.8,
        )


def _plot_investor(
    axis,
    dataset: ChartDataset,
    timeframe: str,
    visible: DataFrame,
    columns: tuple[str, ...],
) -> None:
    flow = dataset.investor_flow(timeframe)
    source_label = str(flow.attrs.get("source_label") or "").strip()
    source_error = str(flow.attrs.get("source_error") or "").strip()
    source_warning = str(flow.attrs.get("source_warning") or "").strip()
    estimated_value = bool(flow.attrs.get("estimated_value", False))
    visible_dates = _trade_dates(visible).normalize()
    session_by_date = {
        pd.Timestamp(trade_date): position
        for position, trade_date in enumerate(visible_dates)
    }
    if not flow.empty:
        flow.index = pd.DatetimeIndex(pd.to_datetime(flow.index, errors="coerce")).normalize()
        flow = flow.loc[flow.index.notna()].sort_index()
        if flow.index.has_duplicates:
            flow = flow.groupby(level=0).sum(min_count=1)
        flow = flow.loc[flow.index.isin(session_by_date)].copy()
        flow["_session"] = [session_by_date[value] for value in flow.index]
    definitions = {
        "institution": ("기관", "#8e44ad"),
        "foreign": ("외국인", "#00897b"),
        "individual": ("개인", "#ef6c00"),
    }
    plotted = False
    for column in columns:
        if flow.empty or column not in flow:
            continue
        label, color = definitions[column]
        values = pd.to_numeric(flow[column], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        if not values.notna().any():
            continue
        scaled = values / 100_000_000
        latest = float(scaled.dropna().iloc[-1])
        axis.plot(
            flow["_session"],
            scaled,
            color=color,
            linewidth=1.2,
            label=f"{label} {latest:+,.1f}억",
            marker="o",
            markevery=[-1],
            markersize=3.2,
        )
        plotted = True
    axis.axhline(0, color="#555555", linewidth=0.6)
    if plotted:
        legend_options = {
            "loc": "upper left",
            "ncol": min(3, len(columns)),
            "frameon": True,
            "framealpha": 0.88,
            "facecolor": "white",
            "edgecolor": "#d0d0d0",
            "handlelength": 2.0,
        }
        if legend_font := _korean_font_properties(9):
            legend_options["prop"] = legend_font
        else:
            legend_options["fontsize"] = 9
        axis.legend(**legend_options)
        if source_label:
            source_rows = int(flow.attrs.get("source_rows") or 0)
            details = source_label
            if source_rows:
                details += f" · 원천 {source_rows:,}거래일"
            if len(flow.index):
                details += (
                    f"\n차트 표시 구간 {flow.index.min():%Y-%m-%d}"
                    f" ~ {flow.index.max():%Y-%m-%d}"
                )
            if source_warning:
                details += f"\n주의: {source_warning}"
            text_options = {}
            if source_font := _korean_font_properties(8):
                text_options["fontproperties"] = source_font
            axis.text(
                0.995,
                0.04,
                details,
                transform=axis.transAxes,
                ha="right",
                va="bottom",
                fontsize=8,
                color="#444444",
                bbox={
                    "boxstyle": "round,pad=0.25",
                    "facecolor": "white",
                    "edgecolor": "#d0d0d0",
                    "alpha": 0.88,
                },
                **text_options,
            )
    else:
        message = "선택 기간의 투자자 수급 원천자료가 없습니다."
        if source_error:
            message = f"수급 자료 확인 필요\n{source_error}"
        text_options = {}
        if message_font := _korean_font_properties(10):
            text_options["fontproperties"] = message_font
        axis.text(
            0.5,
            0.5,
            message,
            transform=axis.transAxes,
            ha="center",
            va="center",
            fontsize=10,
            color="#666666",
            **text_options,
        )
    # Keep the numeric ticks and the investor legend; remove only the Korean Y label.
    axis.set_ylabel("")


def _show_latest_indicator_values(axis, frame: DataFrame, definitions: tuple[tuple[str, str, str], ...]) -> None:
    """Show the last displayed trading day's indicator values in the lower right."""
    rows = []
    for column, label, color in definitions:
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.empty or not np.isfinite(values.iloc[-1]):
            continue
        rows.append((f"{label} {values.iloc[-1]:.1f}", color))
    for position, (label, color) in enumerate(reversed(rows)):
        axis.text(
            0.99, 0.06 + position * 0.16, label,
            transform=axis.transAxes, ha="right", va="bottom", fontsize=10,
            color=color, fontweight="bold",
            bbox={"boxstyle": "round,pad=0.2", "facecolor": "white", "edgecolor": "#d0d0d0", "alpha": 0.9},
            zorder=8,
        )


def _build_selectable_chart_figure(
    dataset: ChartDataset,
    bars: int | None,
    *,
    profile_bins: int,
    options: ChartDisplayOptions,
) -> Figure:
    selected = options.validate()
    if not MIN_PROFILE_BINS <= profile_bins <= MAX_PROFILE_BINS:
        raise ValueError(
            f"매물대 구간 수는 {MIN_PROFILE_BINS}~{MAX_PROFILE_BINS} 사이여야 합니다."
        )
    calendar_frame = _visible_bars(dataset, selected.timeframe, bars)
    trade_dates = pd.DatetimeIndex(calendar_frame.index)
    frame = _session_frame(calendar_frame)
    panels: list[str] = []
    if selected.show_volume:
        panels.append("volume")
    if selected.show_rsi:
        panels.append("rsi")
    if selected.show_stochastic:
        panels.append("stochastic")
    if selected.investor_columns:
        panels.append("investor")
    if selected.show_macd:
        panels.append("macd")

    figure = Figure(
        figsize=(15, max(7.0, 5.2 + 1.25 * len(panels))),
        dpi=100,
        facecolor="white",
    )
    grid = figure.add_gridspec(
        1 + len(panels),
        1,
        height_ratios=[4.8, *([1.15] * len(panels))],
        hspace=0.08,
    )
    price_axis = figure.add_subplot(grid[0])
    axes = {name: figure.add_subplot(grid[index + 1], sharex=price_axis) for index, name in enumerate(panels)}
    _plot_price(price_axis, frame)

    if "volume" in axes:
        axes["volume"].bar(
            frame.index,
            frame["volume"],
            width=_adaptive_candle_width(frame),
            color=frame["volume_color"],
            linewidth=0,
        )
    if "rsi" in axes:
        axis = axes["rsi"]
        axis.plot(frame.index, frame["rsi_14"], color="#6a1b9a", linewidth=0.9, label="RSI(14)")
        axis.plot(frame.index, frame["rsi_signal_9"], color="#ff9800", linewidth=0.85, label="Signal(9)")
        axis.axhline(70, color="#555555", linestyle="--", linewidth=0.65)
        axis.axhline(30, color="#555555", linestyle="--", linewidth=0.65)
        axis.set_ylim(-2, 102)
        axis.set_yticks([0, 30, 70, 100])
        axis.legend(loc="upper left", fontsize=7, frameon=False)
        _show_latest_indicator_values(axis, frame, (
            ("rsi_14", "RSI(14)", "#6a1b9a"),
            ("rsi_signal_9", "Signal(9)", "#ff9800"),
        ))
    if "stochastic" in axes:
        axis = axes["stochastic"]
        axis.plot(frame.index, frame["stoch_slow_k"], color="#1f77b4", linewidth=0.85, label="Slow %K(5,3)")
        axis.plot(frame.index, frame["stoch_slow_d"], color="#d62728", linewidth=0.85, label="Slow %D(3)")
        axis.axhline(80, color="#555555", linestyle="--", linewidth=0.65)
        axis.axhline(20, color="#555555", linestyle="--", linewidth=0.65)
        axis.set_ylim(-2, 102)
        axis.set_yticks([0, 20, 80, 100])
        axis.legend(loc="upper left", ncol=2, fontsize=7, frameon=False)
        _show_latest_indicator_values(axis, frame, (
            ("stoch_slow_k", "Slow %K", "#1f77b4"),
            ("stoch_slow_d", "Slow %D", "#d62728"),
        ))
    if "investor" in axes:
        _plot_investor(
            axes["investor"],
            dataset,
            selected.timeframe,
            frame,
            selected.investor_columns,
        )
    if "macd" in axes:
        axis = axes["macd"]
        oscillator = frame["macd_oscillator"]
        colors = np.where(
            oscillator > 0,
            UP_COLOR,
            np.where(oscillator < 0, DOWN_COLOR, FLAT_COLOR),
        )
        axis.bar(
            frame.index,
            oscillator.fillna(0.0),
            width=_adaptive_candle_width(frame),
            color=colors,
            linewidth=0,
        )
        axis.axhline(0, color="#555555", linewidth=0.6)
        _show_latest_indicator_values(axis, frame, (
            ("macd_oscillator", "MACD", "#333333"),
        ))

    centers, profile_volume, height = calculate_volume_profile(frame, bins=profile_bins)
    if len(centers):
        profile_axis = price_axis.inset_axes([0.0, 0.03, 0.17, 0.94])
        profile_axis.barh(
            centers,
            profile_volume,
            height=height,
            color=PROFILE_COLOR,
            edgecolor=PROFILE_COLOR,
            alpha=PROFILE_ALPHA,
        )
        profile_axis.set_ylim(price_axis.get_ylim())
        profile_axis.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
        profile_axis.patch.set_alpha(0)
        for spine in profile_axis.spines.values():
            spine.set_visible(False)

    ordered_axes = [price_axis, *(axes[name] for name in panels)]
    for axis in ordered_axes:
        _style_session_axis(axis, trade_dates)
    padding = max((len(frame) - 1) * 0.01, _adaptive_candle_width(frame))
    price_axis.set_xlim(-padding, len(frame) - 1 + padding)
    for axis in ordered_axes[:-1]:
        axis.tick_params(labelbottom=False)
    title_options = {"fontsize": 14, "fontweight": "bold"}
    if title_font := _korean_font_properties(14):
        title_options["fontproperties"] = title_font
    figure.suptitle(
        f"{dataset.name} ({dataset.ticker}) · {TIMEFRAME_LABELS[selected.timeframe]}",
        **title_options,
    )
    figure.subplots_adjust(left=0.06, right=0.985, top=0.95, bottom=0.055)
    return figure


def build_chart_figure(
    dataset: ChartDataset,
    trading_days: int | None = 800,
    *,
    profile_bins: int = DEFAULT_PROFILE_BINS,
    options: ChartDisplayOptions | None = None,
) -> Figure:
    """Build either the legacy layout or the user-selectable v31 layout.

    Omitting ``options`` preserves the established public API and test layout.
    The GUI always supplies options and therefore displays only selected panes.
    """

    if options is None:
        return _build_legacy_chart_figure(
            dataset,
            trading_days,
            profile_bins=profile_bins,
        )
    return _build_selectable_chart_figure(
        dataset,
        trading_days,
        profile_bins=profile_bins,
        options=options,
    )
