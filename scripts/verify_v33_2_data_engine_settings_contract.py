from __future__ import annotations

import ast
from pathlib import Path

root = Path(__file__).resolve().parents[1]
config_path = root / "src" / "krx_research" / "data_engine" / "config.py"
postgresql_path = root / "src" / "krx_research" / "data_engine" / "postgresql.py"

config_text = config_path.read_text(encoding="utf-8")
tree = ast.parse(config_text)

settings_class = next(
    node for node in tree.body
    if isinstance(node, ast.ClassDef) and node.name == "DataEngineSettings"
)
methods = {
    node.name for node in settings_class.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}

assert "from_environment" in methods
assert "validate" in methods

postgresql_text = postgresql_path.read_text(encoding="utf-8")
assert "self.settings.validate()" in postgresql_text

print("V33_2_DATA_ENGINE_SETTINGS_CONTRACT_CHECK: PASS")
