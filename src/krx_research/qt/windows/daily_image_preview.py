from __future__ import annotations

from numbers import Number

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QDialog, QDialogButtonBox, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout

COLUMNS = (
    ("report_date", "기준일"), ("category", "테마·분류"), ("ticker", "종목코드"),
    ("stock_name", "종목명"), ("source_return_pct", "이미지 등락률(%)"),
    ("db_return_pct", "DB 등락률(%)"), ("final_return_pct", "확정 등락률(%)"),
    ("source_trading_value_eok", "이미지 거래대금(억원)"),
    ("db_trading_value_eok", "DB 거래대금(억원)"),
    ("final_trading_value_eok", "확정 거래대금(억원)"), ("reason", "사유(이미지 원문)"),
    ("authority", "확정 상태"),
)


class DailyImagePreviewDialog(QDialog):
    def __init__(self, rows: tuple[dict, ...], parent=None) -> None:
        super().__init__(parent); self.resize(1350, 650); self.setWindowTitle("이미지 분석·Stock DB 비교 확인")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Stock DB 값이 있는 항목은 DB 값으로 확정합니다. 확정 등록하면 같은 기준일의 기존 자료를 대체합니다."))
        table = QTableWidget(len(rows), len(COLUMNS)); table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setHorizontalHeaderLabels([label for _, label in COLUMNS])
        for column in range(len(COLUMNS)): table.horizontalHeaderItem(column).setTextAlignment(Qt.AlignCenter)
        for row_index, row in enumerate(rows):
            for column_index, (key, _) in enumerate(COLUMNS):
                value = row.get(key); item = QTableWidgetItem(self._text(value, key))
                item.setTextAlignment(self._alignment(key, value)); table.setItem(row_index, column_index, item)
        table.resizeColumnsToContents(); table.setColumnWidth(10, 480); layout.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("확정 등록")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    @staticmethod
    def _text(value, column: str) -> str:
        if value is None: return ""
        if column == "ticker": return str(value).zfill(6)
        if isinstance(value, Number) and not isinstance(value, bool):
            decimals = 2 if "pct" in column else 1
            return f"{float(value):,.{decimals}f}"
        return str(value)

    @staticmethod
    def _alignment(column: str, value) -> int:
        if column in {"report_date", "ticker"}: return int(Qt.AlignCenter)
        if isinstance(value, Number) and not isinstance(value, bool): return int(Qt.AlignRight | Qt.AlignVCenter)
        return int(Qt.AlignLeft | Qt.AlignVCenter)


__all__ = ["DailyImagePreviewDialog"]
