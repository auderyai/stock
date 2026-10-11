from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget

from krx_research.application.xing_runtime import XingRuntimeQualificationService
from krx_research.collectors.xing.bridge import XingBridgeClient


class RuntimeWorker(QObject):
    progress = Signal(str)
    completed = Signal(bool, str)

    @Slot()
    def run(self) -> None:
        bridge = XingBridgeClient(ROOT, delay=.08, timeout=30.0)
        try:
            service = XingRuntimeQualificationService(bridge)

            def on_progress(step, total, label, result):
                if result is None:
                    self.progress.emit(f"[{step}/{total}] {label}: PASS")
                    return
                state = "PASS" if result.passed else "FAIL"
                suffix = f" ({result.row_count} rows)" if result.row_count else ""
                detail = "" if result.passed else f" - {result.message}"
                self.progress.emit(f"[{step}/{total}] {label}: {state}{suffix}{detail}")

            report = service.qualify(on_progress)
            if report.passed:
                self.completed.emit(
                    True,
                    "V39 DLL runtime: READY\n"
                    f"sector={report.sector_code}, stock={report.stock_code}",
                )
            else:
                self.completed.emit(
                    False,
                    "V39 DLL runtime: NOT READY / " + ", ".join(report.failed_trs),
                )
        except Exception as exc:
            self.completed.emit(False, f"{type(exc).__name__}: {exc}")
        finally:
            bridge.close()


class RuntimeController(QObject):
    progress = Signal(str)
    state_changed = Signal(bool, str)
    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: RuntimeWorker | None = None

    @Slot()
    def start(self) -> None:
        if self._thread is not None:
            return
        self.busy_changed.emit(True)
        thread = QThread(self)
        worker = RuntimeWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress)
        worker.completed.connect(self._complete)
        worker.completed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_thread)
        self._thread = thread
        self._worker = worker
        thread.start()

    @Slot(bool, str)
    def _complete(self, ok: bool, message: str) -> None:
        self.state_changed.emit(ok, message)
        self.busy_changed.emit(False)

    @Slot()
    def _clear_thread(self) -> None:
        self._thread = None
        self._worker = None


class RuntimeWindow(QMainWindow):
    run_requested = Signal()

    def __init__(self, controller: RuntimeController) -> None:
        super().__init__()
        self.setWindowTitle("Stock V39 LS DLL Runtime Qualification")
        self.resize(760, 520)

        self.status = QLabel("V38.5 기준선 보존 / 6개 필수 TR 전체 검증")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.run_button = QPushButton("전체 런타임 검증 실행")

        layout = QVBoxLayout()
        layout.addWidget(self.status)
        layout.addWidget(self.log, 1)
        layout.addWidget(self.run_button)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.run_button.clicked.connect(self._request_run)
        self.run_requested.connect(controller.start)
        controller.progress.connect(self.log.append)
        controller.busy_changed.connect(self._set_busy)
        controller.state_changed.connect(self._show_result)

    @Slot()
    def _request_run(self) -> None:
        self.log.clear()
        self.run_requested.emit()

    @Slot(bool)
    def _set_busy(self, busy: bool) -> None:
        self.run_button.setEnabled(not busy)
        self.status.setText("검증 중..." if busy else self.status.text())

    @Slot(bool, str)
    def _show_result(self, ok: bool, message: str) -> None:
        self.log.append("")
        self.log.append(message)
        self.status.setText("READY" if ok else "NOT READY")


def main() -> int:
    app = QApplication(sys.argv)
    controller = RuntimeController()
    window = RuntimeWindow(controller)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
