from __future__ import annotations

import sys

from krx_research_nextgen.infrastructure.gpu_acceleration import (
    configure_gpu_acceleration,
)
from krx_research_nextgen.infrastructure.task_logging import TaskLog


def main() -> int:
    # Must happen before QApplication construction.
    gpu = configure_gpu_acceleration()

    from PyQt6.QtWidgets import QApplication

    with TaskLog("stage4_application_session", **gpu) as session:
        session.info("Creating QApplication with Desktop OpenGL policy.")
        app = QApplication.instance() or QApplication(sys.argv)
        from krx_research_nextgen.application.container import ApplicationContainer

        with ApplicationContainer() as container:
            container.window.show()
            session.info("Stage4MainWindow shown.")
            rc = app.exec()
            session.info(f"QApplication exit_code={rc}")
            return rc


if __name__ == "__main__":
    raise SystemExit(main())
