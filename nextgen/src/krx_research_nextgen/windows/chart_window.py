from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from krx_research_nextgen.models.chart_data import ChartBundle, STRATEGY_OPTIONS, TIMEFRAME_LABELS
from krx_research_nextgen.models.screening import ScreeningResult
from krx_research_nextgen.presentation.embedded_finplot_widget import EmbeddedFinplotWidget
from krx_research_nextgen.presentation.screening_table import HEADERS, row_values


class ChartWindow(QMainWindow):
    reload_requested = pyqtSignal(str, int, int, str)
    ticker_changed = pyqtSignal(str)
    scenario_requested = pyqtSignal(object, str)

    def __init__(self, navigation: bool = False) -> None:
        super().__init__()
        self._code, self._guard, self._bundle, self._task_title = "", False, None, "차트"
        self._splitter_initialized = False
        self.setWindowTitle("KRX 차트")
        self.resize(1680, 980)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.setCentralWidget(self.splitter)

        page = QWidget(); layout = QVBoxLayout(page)
        page.setMinimumWidth(0); page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.chart = EmbeddedFinplotWidget(); layout.addWidget(self.chart, 1)
        insight = QHBoxLayout(); layout.addLayout(insight)
        strategy = QGroupBox("차트 고전전략 판정 · 쉬운 설명"); strategy_row = QHBoxLayout(strategy)
        self.strategy_mode = QComboBox(); self.strategy_mode.addItems(STRATEGY_OPTIONS)
        self.strategy_text = QLabel("차트 자료를 불러온 뒤 자동으로 판정합니다."); self.strategy_text.setWordWrap(True)
        self.strategy_mode.currentTextChanged.connect(self._show_strategy)
        strategy_row.addWidget(self.strategy_mode); strategy_row.addWidget(self.strategy_text, 1)
        reason = QGroupBox("당일 상승 사유"); reason_row = QVBoxLayout(reason)
        reason_text = QTextEdit("상승 사유는 별도 뉴스 조회 기능에서 확인할 수 있습니다.")
        reason_text.setReadOnly(True); reason_text.setMaximumHeight(92); reason_row.addWidget(reason_text)
        insight.addWidget(strategy, 5); insight.addWidget(reason, 7)

        controls = QGroupBox("차트 표시 선택"); row = QHBoxLayout(controls)
        row.addWidget(QLabel("봉 주기")); self.timeframe = QComboBox()
        for code, label in TIMEFRAME_LABELS.items(): self.timeframe.addItem(label, code)
        row.addWidget(self.timeframe)
        row.addWidget(QLabel("표시 봉수")); self.days = QSpinBox(); self.days.setRange(0, 100000); self.days.setSpecialValueText("전체"); self.days.setValue(500); row.addWidget(self.days)
        row.addWidget(QLabel("매물대 구간")); self.profile = QSpinBox(); self.profile.setRange(6, 20); self.profile.setValue(15); row.addWidget(self.profile)
        apply_button = QPushButton("적용"); apply_button.clicked.connect(self._reload); row.addWidget(apply_button)
        full_button = QPushButton("전체기간"); full_button.clicked.connect(lambda: (self.days.setValue(0), self._reload())); row.addWidget(full_button)
        self.scenario_button = QPushButton("보조지표 시나리오·AI"); self.scenario_button.clicked.connect(self._scenario); row.addWidget(self.scenario_button)
        self.flags = {}
        for key, title, checked in (
            ("volume", "거래량", True), ("rsi", "RSI(14,9)", True), ("macd", "MACD 오실레이터", True),
            ("stochastic", "스토캐스틱 슬로우(5,3,3)", True), ("institution", "기관 수급", False),
            ("foreign", "외국인 수급", False), ("individual", "개인 수급", False),
        ):
            box = QCheckBox(title); box.setChecked(checked); box.toggled.connect(self._visibility); self.flags[key] = box; row.addWidget(box)
        row.addStretch(1); layout.addWidget(controls)
        self.status = QLabel("차트 자료를 불러오는 중입니다..."); layout.addWidget(self.status)
        self.splitter.addWidget(page)

        nav = QWidget(); nav_layout = QVBoxLayout(nav)
        title = QLabel("조회 결과 종목"); title.setStyleSheet("font-size:14px;font-weight:700"); nav_layout.addWidget(title)
        self.navigation = QTableWidget(0, len(HEADERS) - 1)
        self.navigation.setHorizontalHeaderLabels(HEADERS[1:])
        self.navigation.verticalHeader().setVisible(False)
        self.navigation.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.navigation.horizontalHeader().setSectionsMovable(True)
        for col in range(self.navigation.columnCount()):
            self.navigation.horizontalHeaderItem(col).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.navigation.itemSelectionChanged.connect(self._navigate); nav_layout.addWidget(self.navigation, 1)
        self.splitter.addWidget(nav); nav.setVisible(navigation)
        self.splitter.setOpaqueResize(True)
        self.splitter.setSizes([1360, 320] if navigation else [1680, 0])
        self._navigation_enabled = navigation
        self.chart.initialize_finplot()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._splitter_initialized:
            self._splitter_initialized = True
            QTimer.singleShot(0, lambda: self.splitter.setSizes([1360, 320] if self._navigation_enabled else [1680, 0]))

    def show_bundle(self, code: str, bundle: ChartBundle, task_title: str | None = None) -> None:
        timeframe = str(self.timeframe.currentData())
        if task_title: self._task_title = task_title
        self._code, self._bundle = code, bundle; self.chart.render(bundle, profile_bins=self.profile.value(), timeframe=timeframe); self._visibility(); self._show_strategy()
        self.setWindowTitle(f"{self._task_title} · PyQt6 · Finplot")
        self.status.setText(f"{bundle.symbol} · {TIMEFRAME_LABELS[timeframe]} · 최근 {len(bundle.frame):,}개 봉")

    def set_navigation(self, rows: list[ScreeningResult], selected: str) -> None:
        self.set_navigation_data(HEADERS[1:],
                                 [{"code": item.stock_code, "values": row_values(item, include_date=False)} for item in rows],
                                 selected)

    def set_navigation_data(self, headers, items, selected: str, alignments=None) -> None:
        self._guard = True; self.navigation.setColumnCount(len(headers)); self.navigation.setHorizontalHeaderLabels(headers)
        for column in range(self.navigation.columnCount()):
            self.navigation.horizontalHeaderItem(column).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.navigation.setRowCount(len(items))
        for row, entry in enumerate(items):
            values = entry["values"]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if alignments:
                    alignment = {"center": Qt.AlignmentFlag.AlignCenter,
                                 "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                                 "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter}[alignments[col]]
                else:
                    alignment = (Qt.AlignmentFlag.AlignCenter if col == 1 else
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter if col in (0, 4, 5, 6, 7, 8, 9, 10, 11, 13) else
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                cell.setTextAlignment(alignment)
                self.navigation.setItem(row, col, cell)
            self.navigation.item(row, 0).setData(Qt.ItemDataRole.UserRole, str(entry["code"]))
            if str(entry["code"]) == selected: self.navigation.selectRow(row)
        self._guard = False
        self.navigation.resizeColumnsToContents()

    def _navigate(self) -> None:
        if self._guard or self.navigation.currentRow() < 0: return
        first = self.navigation.item(self.navigation.currentRow(), 0)
        code = first.data(Qt.ItemDataRole.UserRole) if first else None
        if code: self.ticker_changed.emit(str(code))

    def _reload(self) -> None:
        if self._code:
            limit = self.days.value() or 100000
            self.reload_requested.emit(self._code, limit, self.profile.value(), str(self.timeframe.currentData()))

    def _visibility(self) -> None:
        self.chart.set_panel_visibility(
            volume=self.flags["volume"].isChecked(), rsi=self.flags["rsi"].isChecked(),
            stochastic=self.flags["stochastic"].isChecked(), macd=self.flags["macd"].isChecked(),
            institution=self.flags["institution"].isChecked(), foreign=self.flags["foreign"].isChecked(),
            individual=self.flags["individual"].isChecked(),
        )

    def _scenario(self) -> None:
        if self._bundle is not None: self.scenario_requested.emit(self._bundle.frame.copy(), self._code)

    def _show_strategy(self, *_args) -> None:
        if self._bundle is None: return
        selected = self.strategy_mode.currentText()
        rows = self._bundle.assessments if selected == "전체" else tuple(row for row in self._bundle.assessments if row.strategy == selected)
        text = "\n\n".join(row.text() for row in rows)
        self.strategy_text.setText(text + "\n※ 과거 DB 자료에 규칙을 적용한 참고 결과이며, 매매 지시나 미래 예측이 아닙니다.")
        self.chart.set_strategy(rows[0] if selected != "전체" and rows else None, self._bundle.frame)
