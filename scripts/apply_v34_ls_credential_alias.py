from __future__ import annotations

from pathlib import Path


MARKER = "# V34_LS_CREDENTIAL_ALIAS_OVERRIDE"
OVERRIDE = """
# V34_LS_CREDENTIAL_ALIAS_OVERRIDE
from .ls_credentials import load_ls_credentials as _load_ls_credentials_v34

def load_credentials(project_root):
    return _load_ls_credentials_v34(project_root)
"""


class LSOpenApiPatcher:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.target = self.project_root / "src" / "krx_research" / "collectors" / "ls_openapi.py"

    def apply(self) -> None:
        if not self.target.is_file():
            raise FileNotFoundError(self.target)
        text = self.target.read_text(encoding="utf-8")
        if MARKER in text:
            return
        self.target.write_text(text.rstrip() + "\n\n" + OVERRIDE.strip() + "\n", encoding="utf-8")


def main(root: str) -> int:
    LSOpenApiPatcher(Path(root)).apply()
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1]))
