from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal


class ScenarioWorker(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, controller, frame, request, parent=None) -> None:
        super().__init__(parent); self._controller, self._frame, self._request = controller, frame, request

    def run(self) -> None:
        try: self.succeeded.emit(self._controller.analyze_scenario(self._frame, self._request))
        except Exception as exc: self.failed.emit(str(exc))
