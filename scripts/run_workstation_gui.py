"""Launch the PySide6/PostgreSQL-only new_stock workstation."""
from __future__ import annotations
from pathlib import Path
from krx_research.database import resolve_database_target

def main()->int:
    project_root=Path(__file__).resolve().parents[1]
    target=resolve_database_target(project_root,read_only=True)
    from krx_research.qt.workstation import launch_workstation
    return int(launch_workstation(target) or 0)
if __name__=='__main__':raise SystemExit(main())
