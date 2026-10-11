from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any


def literal(node: ast.AST | None, default: Any = None) -> Any:
    if node is None:
        return default
    try:
        return ast.literal_eval(node)
    except Exception:
        return default


def extract(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
        if "job" not in func_name.lower():
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        title = literal(kwargs.get("title"), "")
        batch_name = literal(kwargs.get("batch_name"), "")
        if not isinstance(title, str) or not title.strip():
            continue
        key = literal(kwargs.get("key"), f"legacy_{len(rows)+1}")
        description = literal(kwargs.get("description"), "")
        arguments = literal(kwargs.get("arguments"), ())
        if not isinstance(arguments, (tuple, list)):
            arguments = ()
        signature = (str(title), str(batch_name))
        if signature in seen:
            continue
        seen.add(signature)
        rows.append({
            "key": str(key),
            "title": str(title),
            "description": str(description),
            "batch_name": str(batch_name),
            "arguments": [str(x) for x in arguments],
        })
    return rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    rows = extract(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"V42 legacy jobs migrated: {len(rows)} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
