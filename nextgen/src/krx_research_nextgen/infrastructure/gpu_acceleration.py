from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, Qt
import pyqtgraph as pg

from krx_research_nextgen.infrastructure.task_logging import TaskLog


def configure_gpu_acceleration() -> dict[str, object]:
    """Configure Qt/PyQtGraph for AMD/NVIDIA/Intel desktop OpenGL rendering.

    AMD RX6600 path:
    - Force Qt Desktop OpenGL on Windows.
    - Enable PyQtGraph GraphicsView OpenGL.
    - Disable antialiasing to favor throughput for dense financial plots.

    CuPy is intentionally not enabled: it is CUDA-centric and not appropriate
    for AMD RX6600 in this Windows stack.
    """

    enabled = os.environ.get("NEXTGEN_GPU_OPENGL", "1").strip() not in {"0", "false", "False"}

    if enabled:
        os.environ.setdefault("QT_OPENGL", "desktop")
        QCoreApplication.setAttribute(
            Qt.ApplicationAttribute.AA_UseDesktopOpenGL,
            True,
        )
        QCoreApplication.setAttribute(
            Qt.ApplicationAttribute.AA_ShareOpenGLContexts,
            True,
        )
        pg.setConfigOptions(
            useOpenGL=True,
            antialias=False,
        )
    else:
        pg.setConfigOptions(
            useOpenGL=False,
            antialias=False,
        )

    return {
        "enabled": enabled,
        "qt_opengl": os.environ.get("QT_OPENGL", ""),
        "pyqtgraph_useOpenGL": pg.getConfigOption("useOpenGL"),
        "pyqtgraph_antialias": pg.getConfigOption("antialias"),
        "gpu_policy": "Desktop OpenGL / AMD RX6600 preferred" if enabled else "OpenGL disabled",
    }


def log_gpu_configuration() -> Path:
    config = configure_gpu_acceleration()
    with TaskLog("gpu_configuration", **config) as task:
        task.info("GPU configuration initialized.")
        task.info("CuPy/CUDA path disabled for AMD RX6600 compatibility.")
        return task.path
