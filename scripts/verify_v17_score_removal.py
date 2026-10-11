from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "krx_research"
errors=[]

# Score is allowed only as an internal optimization variable in indicator_scenario
# and as a legacy PostgreSQL schema column for existing DB compatibility.
allowed = {
    SRC / "analytics" / "indicator_scenario.py",
    SRC / "database" / "postgresql_schema.py",
}
for path in SRC.rglob("*.py"):
    text=path.read_text(encoding="utf-8")
    if path in allowed:
        continue
    if re.search(r"(?:\[\"score\"\]|\bscore\b|점수)", text):
        # investor presenter may defensively hide legacy DB score, and global policy must hide it.
        if path.name == "investor_presenter.py" and '"score"' in text:
            continue
        if path.name == "table_policy.py" and 'hidden_columns: tuple[str, ...] = ("score",)' in text:
            continue
        if path.name == "screen_presenter.py" and 'drop(columns=["score"], errors="ignore")' in text:
            continue
        errors.append(str(path.relative_to(ROOT)))

# Explicit UI guarantees
policy=(SRC/"qt/presentation/table_policy.py").read_text(encoding="utf-8")
if 'hidden_columns: tuple[str, ...] = ("score",)' not in policy:
    errors.append("global table policy does not hide score")
catalog=(SRC/"qt/presentation/column_catalog.py").read_text(encoding="utf-8")
if '"score": "점수"' in catalog or '"score"' in catalog.split('SCREEN_BASE_COLUMNS',1)[1].split(')',1)[0]:
    errors.append("score still exists in presentation catalog/base columns")
presenter=(SRC/"qt/presentation/screen_presenter.py").read_text(encoding="utf-8")
if 'drop(columns=["score"], errors="ignore")' not in presenter:
    errors.append("screen presenter does not strip legacy score")

if errors:
    print("V17_SCORE_REMOVAL_CHECK: FAIL")
    for e in errors: print(" -",e)
    sys.exit(1)
print("V17_SCORE_REMOVAL_CHECK: PASS")
