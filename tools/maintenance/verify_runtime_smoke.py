"""Start the real PySide6 application briefly without requiring a display."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer

from krx_research.database import resolve_database_target
from krx_research.qt.application.app import NewStockApplication
from krx_research.qt.job_menu.window import KrxJobMenuWindow


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    application = NewStockApplication(resolve_database_target(root, read_only=True))
    application.controller.initialize()
    application.window.show()
    application.qt_app.processEvents()
    if not application.window.isVisible():
        raise RuntimeError("메인 창이 표시 상태가 아닙니다.")
    title = application.window.windowTitle()
    QTimer.singleShot(3000, application.qt_app.quit)
    result = int(application.qt_app.exec() or 0)
    application.window.close()
    menu = KrxJobMenuWindow(root)
    menu.show()
    application.qt_app.processEvents()
    if not menu.isVisible():
        raise RuntimeError("작업 메뉴 창이 표시 상태가 아닙니다.")
    menu_title = menu.windowTitle()
    QTimer.singleShot(1000, application.qt_app.quit)
    menu_result = int(application.qt_app.exec() or 0)
    print(
        f"RUNTIME_SMOKE: PASS workstation={title!r} menu={menu_title!r} "
        f"exit={result}/{menu_result}"
    )
    return result or menu_result


if __name__ == "__main__":
    raise SystemExit(main())
