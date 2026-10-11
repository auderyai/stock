from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MENU = ROOT / "KRX_Menu_Launcher" / "scripts" / "run_krx_menu.py"
PROGRESS = ROOT / "KRX_Menu_Launcher" / "scripts" / "run_job_progress_gui.py"


def source(path: Path) -> tuple[str, ast.Module]:
    text = path.read_text(encoding="utf-8")
    return text, ast.parse(text)


def job_modes(tree: ast.AST) -> dict[str, str]:
    modes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "JobDefinition":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
            continue
        key = node.args[0].value
        mode = "window"
        if len(node.args) >= 6 and isinstance(node.args[5], ast.Constant) and isinstance(node.args[5].value, str):
            mode = node.args[5].value
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                mode = kw.value.value
        modes[key] = mode
    return modes


menu, menu_tree = source(MENU)
progress, _ = source(PROGRESS)
modes = job_modes(menu_tree)

assert modes.get("daily") == "progress"
assert modes.get("supplement") == "progress"
assert modes.get("investor_date_range") == "launcher"
assert "JobExecutionService" in menu and "QProcess.startDetached" in menu
assert 'if job.mode == "progress"' in menu and 'if job.mode == "launcher"' in menu
assert 'if __name__ == "__main__"' in progress
assert "errorOccurred.connect" in progress
assert "PYTHONUTF8" in progress and "PYTHONIOENCODING" in progress
assert '"--no-investor"' not in menu and '"--no-investor"' not in progress
print("V21_LAUNCHER_EXECUTION_CHECK: PASS")
