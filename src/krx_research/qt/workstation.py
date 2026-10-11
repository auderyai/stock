"""Compatibility entrypoint. Real implementation lives in layered qt packages."""
from krx_research.qt.application.app import NewStockApplication, launch

def launch_workstation(database_target) -> int:
    return launch(database_target)

__all__=["NewStockApplication","launch_workstation"]
