"""PySide6 application package for ``new_stock``.

This package intentionally performs no eager imports.

Keeping the package initializer side-effect free is important because widgets,
controllers and services import each other through explicit layered modules.
Import public classes from their concrete modules, for example::

    from krx_research.qt.application.app import NewStockApplication
    from krx_research.qt.windows.chart_window import ChartWindow

This avoids circular imports during Qt application startup.
"""

__all__: list[str] = []
