from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path

from .model import BlockSchema, FieldSchema, TrSchema


class SchemaLoadError(RuntimeError):
    pass


class SchemaLoader(ABC):
    @abstractmethod
    def load(self, path: Path) -> TrSchema:
        raise NotImplementedError


class JsonSchemaLoader(SchemaLoader):
    def load(self, path: Path) -> TrSchema:
        data = json.loads(path.read_text(encoding="utf-8"))
        is_attr = bool(data.get("attribute", False))
        blocks = tuple(
            BlockSchema(
                name=block["name"],
                direction=block["direction"].lower(),
                occurs=bool(block.get("occurs", False)),
                fields=tuple(
                    FieldSchema(
                        name=field["name"],
                        field_type=field["type"],
                        size=int(field["size"]),
                        decimals=int(field.get("decimals", 0)),
                        description=field.get("description", ""),
                    )
                    for field in block["fields"]
                ),
                is_attr=is_attr,
            )
            for block in data["blocks"]
        )
        return TrSchema(
            tr_code=data["tr_code"],
            tr_name=data.get("tr_name", data["tr_code"]),
            blocks=blocks,
            source_kind="json",
            source_path=str(path),
        )


class ResSchemaLoader(SchemaLoader):
    _block_re = re.compile(
        r"^\s*([^,;]+)\s*,\s*([^,;]*)\s*,\s*(input|output)\s*(?:,\s*(occurs))?\s*;\s*$",
        re.I,
    )

    def load(self, path: Path) -> TrSchema:
        text = self._read_text(path)
        tr_code, tr_name, is_attr = self._function_info(text, path)

        lines = text.splitlines()
        blocks: list[BlockSchema] = []
        i = 0
        while i < len(lines):
            match = self._block_re.match(lines[i])
            if not match:
                i += 1
                continue

            block_name = match.group(1).strip()
            direction = match.group(3).lower()
            occurs = bool(match.group(4))
            i += 1

            while i < len(lines) and lines[i].strip().lower() != "begin":
                i += 1
            if i >= len(lines):
                raise SchemaLoadError(f"{path}: begin missing for {block_name}")
            i += 1

            fields: list[FieldSchema] = []
            while i < len(lines):
                line = lines[i].strip()
                i += 1
                if not line or line.startswith("//"):
                    continue
                if line.lower() == "end":
                    break
                field = self._parse_field(line)
                if field:
                    fields.append(field)

            blocks.append(
                BlockSchema(
                    name=block_name,
                    direction=direction,
                    occurs=occurs,
                    fields=tuple(fields),
                    is_attr=is_attr,
                )
            )

        if not blocks:
            raise SchemaLoadError(f"{path}: no data blocks parsed")

        return TrSchema(
            tr_code=tr_code,
            tr_name=tr_name,
            blocks=tuple(blocks),
            source_kind="res",
            source_path=str(path),
        )

    @staticmethod
    def _read_text(path: Path) -> str:
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("latin1")

    @staticmethod
    def _function_info(text: str, path: Path) -> tuple[str, str, bool]:
        for raw in text.splitlines():
            line = raw.strip()
            if not line.lower().startswith(".func,") and not line.lower().startswith(".feed,"):
                continue
            parts = [p.strip() for p in line.rstrip(";").split(",")]
            if len(parts) >= 4:
                name = parts[1]
                code = parts[2]
                is_attr = any(p.lower() == "attr" for p in parts[3:])
                return code, name, is_attr
        return path.stem.replace("_2", ""), path.stem, False

    @staticmethod
    def _parse_field(line: str) -> FieldSchema | None:
        line = line.rstrip(";").strip()
        if not line or "," not in line:
            return None
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 5:
            return None

        description = parts[0]
        name = parts[1]
        field_type = parts[3].lower()
        size_token = parts[4]

        decimals = 0
        if "." in size_token:
            width, decimal_part = size_token.split(".", 1)
            size = int(width)
            decimals = int(decimal_part or 0)
        else:
            size = int(size_token)

        return FieldSchema(
            name=name,
            field_type=field_type,
            size=size,
            decimals=decimals,
            description=description,
        )
