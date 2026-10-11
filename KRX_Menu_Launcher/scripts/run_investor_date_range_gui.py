from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDateEdit,
    QFormLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from run_job_progress_gui import ProgressJob, ProgressWindow


@dataclass(frozen=True)
class DateRangeRequest:
    start: dt.date
    end: dt.date

    def validate(self) -> None:
        if self.start > self.end:
            raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")


class InvestorDateRangeJobFactory:
    @staticmethod
    def build(request: DateRangeRequest) -> tuple[ProgressJob, tuple[str, ...]]:
        job = ProgressJob(
            "investor_date_range",
            f"5. LS 수급 원본 갱신 · {request.start} ~ {request.end}",
            "완료 체크포인트 BYPASS / 미완료 종목·날짜만 LS t1702 수집",
            ("update_ls_investor_date_range.py",),
        )
        return job, ("--start", request.start.isoformat(), "--end", request.end.isoformat())


class DateRangeDialog(QMainWindow):
    run_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("5. LS 수급 원본 갱신 - 날짜 지정")
        self.resize(520, 260)
        host = QWidget()
        self.setCentralWidget(host)
        layout = QVBoxLayout(host)
        form = QFormLayout()
        layout.addLayout(form)
        self.start = QDateEdit(calendarPopup=True)
        self.end = QDateEdit(calendarPopup=True)
        today = QDate.currentDate()
        self.start.setDate(today)
        self.end.setDate(today)
        form.addRow("시작일", self.start)
        form.addRow("종료일", self.end)
        button = QPushButton("실행")
        button.clicked.connect(self._emit_request)
        layout.addWidget(button)

    def _emit_request(self) -> None:
        self.run_requested.emit(DateRangeRequest(self.start.date().toPython(), self.end.date().toPython()))


class DateRangeController:
    def __init__(self, view: DateRangeDialog) -> None:
        self.view = view
        self.progress: ProgressWindow | None = None
        view.run_requested.connect(self.run)

    def run(self, request: DateRangeRequest) -> None:
        try:
            request.validate()
            job, args = InvestorDateRangeJobFactory.build(request)
            self.progress = ProgressWindow(job, args)
            self.progress.show()
            self.view.close()
        except Exception as exc:
            QMessageBox.critical(self.view, "실행 오류", str(exc))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    view = DateRangeDialog()
    view.controller = DateRangeController(view)
    view.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
