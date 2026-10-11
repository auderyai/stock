from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class FieldSchema:
    name: str
    field_type: str
    size: int
    decimals: int = 0
    description: str = ""

    @property
    def numeric(self) -> bool:
        return self.field_type.lower() in {"long", "int", "float", "double", "decimal"}

    def parse(self, raw: str) -> Any:
        value = raw.strip()
        if value == "":
            return None if self.numeric else ""
        kind = self.field_type.lower()
        if kind in {"long", "int"}:
            try:
                return int(value)
            except ValueError:
                return value
        if kind in {"float", "double", "decimal"}:
            try:
                return Decimal(value)
            except Exception:
                return value
        return value


@dataclass(frozen=True, slots=True)
class BlockSchema:
    name: str
    direction: str
    occurs: bool
    fields: tuple[FieldSchema, ...]
    is_attr: bool = False

    @property
    def size(self) -> int:
        """Declared schema body size (without attribute separator bytes)."""
        return sum(field.size for field in self.fields)

    @property
    def wire_size(self) -> int:
        """DLL wire size. Attribute TRs add one byte after every field."""
        return self.size + (len(self.fields) if self.is_attr else 0)


@dataclass(frozen=True, slots=True)
class TrSchema:
    tr_code: str
    tr_name: str
    blocks: tuple[BlockSchema, ...]
    source_kind: str
    source_path: str

    def block(self, name: str) -> BlockSchema:
        for block in self.blocks:
            if block.name == name:
                return block
        raise KeyError(f"{self.tr_code}: block not found: {name}")

    @property
    def input_blocks(self) -> tuple[BlockSchema, ...]:
        return tuple(b for b in self.blocks if b.direction == "input")

    @property
    def output_blocks(self) -> tuple[BlockSchema, ...]:
        return tuple(b for b in self.blocks if b.direction == "output")
