from pathlib import Path
import ast

root = Path(__file__).resolve().parents[1]
path = root / "scripts" / "import_xing_res_to_managed_dir_gui.py"
text = path.read_text(encoding="utf-8")
ast.parse(text)

for marker in (
    'MANAGED = ROOT / "resources" / "xing" / "res"',
    'REQUIRED = ("t8424", "t8436", "t1516", "t8429", "t8451", "t1702")',
    "QFileDialog.getOpenFileName",
    "QFileDialog.getExistingDirectory",
    "shutil.copy2",
    'EnvRepository(ROOT / ".env").save("LS_XING_RES_DIR"',
):
    assert marker in text, marker

print("V36_7_XING_RES_IMPORTER_CHECK: PASS")
