from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
view = (ROOT / "src/krx_research/qt/windows/scenario_window.py").read_text(encoding="utf-8")
presenter = (ROOT / "src/krx_research/qt/presentation/scenario_presenter.py").read_text(encoding="utf-8")
plotter = (ROOT / "src/krx_research/qt/presentation/scenario_plotter.py").read_text(encoding="utf-8")
policy = (ROOT / "src/krx_research/qt/presentation/table_policy.py").read_text(encoding="utf-8")

assert "QIntValidator" in view and "빈칸=전체" in view
assert "self.lookback.text()" in view
assert "ScenarioPresenter.TABLE_POLICY" in view
for name in ("days", "baseline_price", "scenario_price", "required_price", "range", "validation"):
    assert f'"{name}"' in presenter
assert 'center_columns=("signal",)' in presenter
assert 'axis.set_ylabel("σ"' not in plotter
assert "right_columns" in policy
print("V13_SCENARIO_PRESENTATION_CHECK: PASS")
