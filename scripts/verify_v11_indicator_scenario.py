"""Regression checks for V11 original-workstation indicator scenario migration."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "krx_research"
errors: list[str] = []

required = (
    "analytics/indicator_scenario.py",
    "database/scenario_market.py",
    "qt/models/scenario.py",
    "qt/services/scenario_service.py",
    "qt/controllers/scenario_controller.py",
    "qt/windows/scenario_window.py",
    "qt/presentation/scenario_presenter.py",
    "qt/presentation/scenario_plotter.py",
    "qt/scenario_window.py",
)
for rel in required:
    if not (SRC / rel).exists():
        errors.append(f"missing scenario layer: {rel}")

view_text = (SRC / "qt/windows/scenario_window.py").read_text(encoding="utf-8")
controller_text = (SRC / "qt/controllers/scenario_controller.py").read_text(encoding="utf-8")
service_text = (SRC / "qt/services/scenario_service.py").read_text(encoding="utf-8")
repo_text = (SRC / "database/scenario_market.py").read_text(encoding="utf-8")
legacy_entry = (SRC / "ui/run_scenario_gui.py").read_text(encoding="utf-8")
requirements = (ROOT / "requirements.in").read_text(encoding="utf-8")

for forbidden in ("tkinter", "FigureCanvasTkAgg", "sqlite", "PyQt5", "PyQt6"):
    if forbidden.lower() in view_text.lower() + controller_text.lower() + service_text.lower():
        errors.append(f"prohibited scenario dependency: {forbidden}")
if "krx_research.database" in view_text or "psycopg" in view_text.lower():
    errors.append("scenario View accesses database directly")
if "from krx_research.qt.scenario_window" not in legacy_entry:
    errors.append("legacy scenario entry is not a thin PySide6 facade")
if "fetch_index" not in repo_text or "BaseDataRepository" not in repo_text:
    errors.append("scenario market context is not PostgreSQL/SQL repository-backed")
if "evaluate(" not in service_text or "scenario_path(" not in service_text:
    errors.append("original evaluate/scenario_path engine is not used by ScenarioService")
if "scikit-learn" not in requirements:
    errors.append("scikit-learn runtime dependency missing")
for text in (
    "AI 기본 예상가", "AI 지표변경 예상가", "목표 도달 가상가격", "AI 10~90% 범위",
    "전체 보조지표 변동", "EMA 변화율 전체", "과거 학습 기간",
):
    if text not in view_text + (SRC / "qt/presentation/scenario_presenter.py").read_text(encoding="utf-8"):
        errors.append(f"original scenario UX element missing: {text}")

print("V11_INDICATOR_SCENARIO_CHECK:", "PASS" if not errors else "FAIL")
for error in errors:
    print(" -", error)
sys.exit(1 if errors else 0)
