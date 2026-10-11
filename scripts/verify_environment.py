from __future__ import annotations
import importlib.util,json,platform,sys
from pathlib import Path
from krx_research.database import database_label,resolve_database_target
def main():
    root=Path(__file__).resolve().parents[1];target=resolve_database_target(root,read_only=True);expected=root/'.venv'/'Scripts'/'python.exe';actual=Path(sys.executable).resolve();drivers={n:importlib.util.find_spec(n) is not None for n in ('psycopg','PySide6','matplotlib','pandas')};result={'project_root':str(root),'python_executable':str(actual),'expected_python':str(expected),'python_version':platform.python_version(),'architecture':platform.architecture()[0],'database_engine':'postgresql','database_target':database_label(target),'dependencies':drivers,'shared_storage':str(root)};print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if all(drivers.values()) else 3
if __name__=='__main__':raise SystemExit(main())
