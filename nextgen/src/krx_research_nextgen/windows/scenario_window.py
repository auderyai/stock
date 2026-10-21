from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from krx_research_nextgen.models.scenario import EMA_SPANS, INDICATORS
from krx_research_nextgen.workers.scenario_worker import ScenarioWorker
from krx_research_nextgen.widgets.result_table import ResultTable


_CHECKPOINT_LABELS = {
    "reference_date": "기준일", "baseline_price": "AI 기본 예상가",
    "scenario_price": "AI 지표변경 예상가", "target_path_price": "목표 도달 가상가격",
    "prediction_range": "AI 10~90% 범위", "validation_error": "검증 오차",
    "direction_accuracy": "방향 일치", "signal": "판정",
}


class ScenarioPlotWidget(pg.PlotWidget):
    """Date-axis plot that exposes the scenario price for the nearest day."""

    price_hovered = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__(axisItems={"bottom": pg.DateAxisItem()})
        self._x = self._prices = np.array([])
        self._details = ()
        self._dates = pd.DatetimeIndex([])
        self._cursor = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#777", style=Qt.PenStyle.DashLine))
        self._price_label = pg.TextItem(anchor=(0, 0), color="#fff", fill=pg.mkBrush(21, 101, 192, 245), border=pg.mkPen("#0d47a1", width=2))
        self._proxy = pg.SignalProxy(self.scene().sigMouseMoved, rateLimit=30, slot=self._show_price)

    def prepare(self, dates, prices) -> np.ndarray:
        self.clear(); self.showGrid(x=True, y=True, alpha=.2)
        if self.plotItem.legend is None: self.addLegend()
        else: self.plotItem.legend.clear()
        self._dates = pd.DatetimeIndex(dates); self._x = self._dates.asi8 / 1_000_000_000; self._prices = np.asarray(prices, dtype=float); self._details = ()
        self.addItem(self._cursor, ignoreBounds=True); self.addItem(self._price_label, ignoreBounds=True)
        self._cursor.hide(); self._price_label.hide()
        return self._x

    def set_price_details(self, details) -> None:
        self._details = tuple((name, color, np.asarray(values, dtype=float)) for name, color, values in details)

    def _show_price(self, event) -> None:
        pos = event[0]
        if not len(self._x) or not self.sceneBoundingRect().contains(pos):
            self._cursor.hide(); self._price_label.hide(); return
        point = self.plotItem.vb.mapSceneToView(pos); index = int(np.abs(self._x - point.x()).argmin())
        self._cursor.setPos(self._x[index]); self._cursor.show()
        date, price = f"{self._dates[index]:%Y-%m-%d}", f"{self._prices[index]:,.0f}원"
        self._price_label.setHtml(f'<span style="font-size:12pt;color:white"><b>{date}</b><br>가상 종가: <b>{price}</b></span>')
        self._price_label.setPos(self._x[index], self.plotItem.vb.viewRange()[1][1]); self._price_label.show()
        details = "　".join(
            f'<span style="color:{color}"><b>■ {name}: {values[index]:,.0f}원</b></span>'
            for name, color, values in self._details if index < len(values) and np.isfinite(values[index])
        )
        self.price_hovered.emit(f"<b>기준일: {date}　|　가상 종가: {price}</b>" + (f"<br>{details}" if details else ""))


class ScenarioWindow(QMainWindow):
    """PyQt6/PyQtGraph indicator-scenario view; calculation stays in Controller/Service."""

    def __init__(self, controller, daily: pd.DataFrame, ticker: str, parent=None) -> None:
        super().__init__(parent); self._controller, self.daily, self._analysis, self._worker = controller, daily.copy(), None, None
        self.setWindowTitle("보조지표 시나리오·AI · PyQt6 · PyQtGraph"); self.resize(1500, 900); self._build(); self._indicator_changed()

    def _build(self) -> None:
        root = QWidget(); self.setCentralWidget(root); layout = QVBoxLayout(root); controls = QHBoxLayout(); layout.addLayout(controls)
        controls.addWidget(QLabel("변동시킬 지표")); self.indicator = QComboBox(); self.indicator.addItems(INDICATORS); controls.addWidget(self.indicator)
        controls.addWidget(QLabel("목표값")); self.target = QLineEdit(); self.target.setMaximumWidth(100); controls.addWidget(self.target)
        controls.addWidget(QLabel("도달 기간(거래일)")); self.horizon = QLineEdit("20"); self.horizon.setValidator(QIntValidator(1, 60)); self.horizon.setMaximumWidth(70); controls.addWidget(self.horizon)
        controls.addWidget(QLabel("과거 학습 기간")); self.lookback = QLineEdit(); self.lookback.setValidator(QIntValidator(80, 20000)); self.lookback.setPlaceholderText("빈칸=전체"); self.lookback.setMaximumWidth(100); controls.addWidget(self.lookback)
        self.run_button = QPushButton("시나리오 실행"); self.run_button.clicked.connect(self._run); controls.addWidget(self.run_button); controls.addStretch()
        self.indicator.currentTextChanged.connect(self._indicator_changed)
        self.status = QLabel("지표 목표값과 기간을 입력해 시나리오를 실행하세요."); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.table = ResultTable(); self.table.setMaximumHeight(140); self._configure_table_header(); layout.addWidget(self.table)
        self.training = QLabel("실행 후 시간순 학습·검증 구간을 표시합니다."); self.training.setWordWrap(True); layout.addWidget(self.training)
        buttons = QHBoxLayout(); layout.addLayout(buttons); buttons.addWidget(QLabel("보조지표 보기"))
        for label in ("전체", *tuple(INDICATORS)[:6], "EMA 변화율 전체"):
            button = QPushButton(label); button.clicked.connect(lambda _=False, x=label: self._show_indicators(x)); buttons.addWidget(button)
        buttons.addStretch()
        self.price_readout = QLabel("그래프에서 날짜를 가리키면 해당 날짜의 가상 종가가 표시됩니다.")
        self.price_readout.setTextFormat(Qt.TextFormat.RichText); self.price_readout.setWordWrap(True)
        self.price_readout.setStyleSheet("QLabel { background:#e3f2fd; border:1px solid #1565c0; padding:6px; font-size:13px; }"); layout.addWidget(self.price_readout)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs, 1); self.price_plot, self.indicator_plot = ScenarioPlotWidget(), ScenarioPlotWidget()
        self.price_plot.price_hovered.connect(self.price_readout.setText); self.indicator_plot.price_hovered.connect(self.price_readout.setText)
        self.tabs.addTab(self.price_plot, "가격 시나리오"); self.tabs.addTab(self.indicator_plot, "전체 보조지표 변동")
        self.summary = QLabel("실행 후 모든 지표의 현재값과 종료값을 표시합니다."); self.summary.setWordWrap(True); layout.addWidget(self.summary)
        note = QLabel("AI 예상가는 과거 자료의 시간순 학습·검증 결과이며, 목표 도달 가격과 보조지표는 가상 OHLCV 경로로 재계산됩니다. 매매 판정은 검증 기준 충족 시에만 표시합니다."); note.setWordWrap(True); layout.addWidget(note)

    def _configure_table_header(self) -> None:
        header = self.table.horizontalHeader(); header.setStretchLastSection(False)
        for column, width in enumerate((110, 145, 155, 155, 175, 155, 115, 210)): header.resizeSection(column, width)

    def _indicator_changed(self) -> None:
        try: self.target.setPlaceholderText(f"현재 {self._controller.scenario_current(self.daily, self.indicator.currentText()):.2f}")
        except Exception as exc: self.target.setPlaceholderText(str(exc))

    def _run(self) -> None:
        try: request = self._controller.scenario_request(self.daily, self.indicator.currentText(), self.target.text(), self.horizon.text(), self.lookback.text())
        except Exception as exc: QMessageBox.critical(self, "입력 오류", str(exc)); return
        self.run_button.setEnabled(False); self.status.setText("과거 일봉 시간순 검증과 목표 지표 경로를 계산 중입니다…")
        self._worker = ScenarioWorker(self._controller, self.daily.copy(), request, self); self._worker.succeeded.connect(self._ready); self._worker.failed.connect(self._failed); self._worker.start()

    def _failed(self, message: str) -> None:
        self.run_button.setEnabled(True); self.status.setText(message); QMessageBox.critical(self, "시나리오 계산 오류", message)

    def _ready(self, analysis) -> None:
        self.run_button.setEnabled(True); self._analysis = analysis; self._fill_table(); self._draw_price(); self._show_indicators("전체")
        verdict = "목표 도달" if analysis.feasible else "가장 가까운 가상 경로"
        self.status.setText(f"{verdict}: {analysis.current_value:.2f} → {analysis.achieved_value:.2f} (목표 {analysis.requested_value:.2f}), 가상 종가 {analysis.path.close.iloc[-1]:,.0f}원")
        self.training.setText(" | ".join(f"{r.days}일: 학습 {r.train_period}, 검증 {r.test_period}" for r in analysis.checkpoints))

    def _fill_table(self) -> None:
        rows, path = self._analysis.checkpoints, self._analysis.path
        frame = pd.DataFrame(({
            "reference_date": path.index[item.days - 1].date(),
            "baseline_price": item.baseline_price,
            "scenario_price": item.scenario_price,
            "target_path_price": path.close.iloc[item.days - 1],
            "prediction_range": f"{item.lower_price:,.0f} ~ {item.upper_price:,.0f}",
            "validation_error": f"{item.mae:.2f}% (기준 {item.naive_mae:.2f}%)",
            "direction_accuracy": f"{item.direction:.1f}%",
            "signal": item.signal,
        } for item in rows), columns=_CHECKPOINT_LABELS)
        self.table.set_frame(frame, labels=_CHECKPOINT_LABELS)
        self._configure_table_header()

    def _draw_price(self) -> None:
        plot, a, rows = self.price_plot, self._analysis, self._analysis.checkpoints; current = a.current_price
        prices = np.array([current, *a.path.close]); x = plot.prepare([self.daily.index[-1], *a.path.index], prices); checkpoints = [0, *[r.days for r in rows]]
        plot.plot(x[checkpoints], [current, *[r.baseline_price for r in rows]], pen=pg.mkPen("#777", width=2, style=Qt.PenStyle.DashLine), symbol="o", name="AI 기본 예상")
        plot.plot(x[checkpoints], [current, *[r.scenario_price for r in rows]], pen=pg.mkPen("#e67e22", width=2, style=Qt.PenStyle.DashLine), symbol="o", name="AI 지표변경 예상")
        plot.plot(x, prices, pen=pg.mkPen("#1565c0", width=3), name="목표 일치 가상가격")

    def _show_indicators(self, label: str) -> None:
        self.tabs.setCurrentIndex(1)
        if self._analysis is None: return
        labels = tuple(INDICATORS)[:6] if label == "전체" else tuple(f"EMA {n} 일별 변화율 (%)" for n in EMA_SPANS) if label == "EMA 변화율 전체" else (label,)
        plot, path = self.indicator_plot, self._analysis.path; x = plot.prepare(path.index, path.close); summaries, price_details = [], []
        for index, name in enumerate(labels):
            column = INDICATORS[name]; values = pd.to_numeric(path[column], errors="coerce").to_numpy(); color = pg.intColor(index, hues=max(1, len(labels)))
            plot.plot(x, values, pen=pg.mkPen(color, width=2), name=name); summaries.append(f"{name}: {values[-1]:.2f}")
            price_details.extend((f"EMA {span}", color.name(), path[f"ema_{span}"]) for span in EMA_SPANS if name.startswith(f"EMA {span} "))
            if name.startswith("Bollinger"):
                price_details.extend((label, band_color, path[column]) for label, band_color, column in (
                    ("볼린저 상단", "#1565c0", "bb_upper"), ("볼린저 중심", "#ef6c00", "bb_mid"), ("볼린저 하단", "#7b1fa2", "bb_lower"),
                ))
        plot.set_price_details(price_details)
        self.summary.setText(" | ".join(summaries))
