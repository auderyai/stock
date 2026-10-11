from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable

import pandas as pd
from PySide6.QtWidgets import QWidget


class ChartNavigationMode(str, Enum):
    NEW_WINDOW = "new_window"
    SYNCHRONIZED = "synchronized"


class ChartNavigationStrategy(ABC):
    """Strategy boundary for chart-opening behavior.

    The controller chooses a strategy; views never decide business flow.
    """

    mode: ChartNavigationMode

    def __init__(self, create_window: Callable[..., QWidget], keep_window: Callable[[QWidget], QWidget]):
        self._create_window = create_window
        self._keep_window = keep_window

    @abstractmethod
    def open(
        self,
        *,
        ticker: str,
        quote_venue: str,
        frame: pd.DataFrame,
        labels: dict[str, str],
        parent: QWidget,
    ) -> QWidget:
        raise NotImplementedError

    def selection_changed(self, ticker: str, quote_venue: str) -> None:
        return None


class NewChartWindowStrategy(ChartNavigationStrategy):
    mode = ChartNavigationMode.NEW_WINDOW

    def open(self, *, ticker: str, quote_venue: str, frame: pd.DataFrame, labels: dict[str, str], parent: QWidget) -> QWidget:
        window = self._create_window(ticker=ticker, quote_venue=quote_venue, parent=parent, navigation_enabled=False)
        return self._keep_window(window)


class SynchronizedChartStrategy(ChartNavigationStrategy):
    mode = ChartNavigationMode.SYNCHRONIZED

    def __init__(self, create_window: Callable[..., QWidget], keep_window: Callable[[QWidget], QWidget]):
        super().__init__(create_window, keep_window)
        self._window: QWidget | None = None

    def open(self, *, ticker: str, quote_venue: str, frame: pd.DataFrame, labels: dict[str, str], parent: QWidget) -> QWidget:
        if self._window is None:
            self._window = self._create_window(
                ticker=ticker,
                quote_venue=quote_venue,
                parent=parent,
                navigation_enabled=True,
                navigation_frame=frame,
                navigation_labels=labels,
            )
            self._keep_window(self._window)
            self._window.destroyed.connect(lambda *_: self._clear())
        else:
            self._window.set_navigation_results(frame, labels, selected_ticker=ticker)
            self._window.set_ticker(ticker, quote_venue)
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()
        return self._window

    def selection_changed(self, ticker: str, quote_venue: str) -> None:
        if self._window is None:
            return
        self._window.select_navigation_ticker(ticker)
        self._window.set_ticker(ticker, quote_venue)
        self._window.raise_()

    def _clear(self) -> None:
        self._window = None
