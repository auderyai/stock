from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from .model import BlockSchema


class PacketCodec:
    """One fixed-width codec for schemas loaded from either RES or JSON."""

    def __init__(self, encoding: str = "cp949") -> None:
        self.encoding = encoding

    def encode(self, block: BlockSchema, values: Mapping[str, Any]) -> bytes:
        """
        Encode one input block.

        LS RES `attr` TRs place one attribute byte after every fixed-width field.
        The official wire convention uses ASCII space for input attribute bytes.
        """
        chunks: list[bytes] = []
        for field in block.fields:
            raw = self._format(field.field_type, field.decimals, values.get(field.name))
            encoded = raw.encode(self.encoding, errors="strict")

            if len(encoded) > field.size:
                raise ValueError(
                    f"{block.name}.{field.name}: encoded length {len(encoded)} > {field.size}"
                )

            pad = b" " * (field.size - len(encoded))
            chunks.append(pad + encoded if field.numeric else encoded + pad)

            if block.is_attr:
                chunks.append(b" ")

        packet = b"".join(chunks)
        if len(packet) != block.wire_size:
            raise AssertionError(
                f"{block.name}: encoded wire size {len(packet)} != {block.wire_size}"
            )
        return packet

    def decode_one(self, block: BlockSchema, packet: bytes) -> dict[str, Any]:
        wire_size = block.wire_size
        if len(packet) < wire_size:
            raise ValueError(
                f"{block.name}: packet too short {len(packet)} < {wire_size}"
            )
        return self._decode_record(block, packet[:wire_size])

    def decode_occurs(self, block: BlockSchema, packet: bytes) -> list[dict[str, Any]]:
        if not block.occurs:
            return [self.decode_one(block, packet)]
        if not packet:
            return []

        wire_size = block.wire_size
        if wire_size <= 0 or len(packet) % wire_size:
            raise ValueError(
                f"{block.name}: OCCURS packet length {len(packet)} is not a multiple "
                f"of wire_size={wire_size} "
                f"(schema_body={block.size}, fields={len(block.fields)}, attr={block.is_attr})"
            )

        return [
            self._decode_record(block, packet[i:i + wire_size])
            for i in range(0, len(packet), wire_size)
        ]

    def _decode_record(self, block: BlockSchema, record: bytes) -> dict[str, Any]:
        if len(record) != block.wire_size:
            raise ValueError(
                f"{block.name}: record size {len(record)} != wire_size {block.wire_size}"
            )

        result: dict[str, Any] = {}
        offset = 0
        for field in block.fields:
            raw = record[offset:offset + field.size]
            offset += field.size

            text = raw.decode(self.encoding, errors="replace")
            result[field.name] = field.parse(text)

            # Attribute byte belongs to DLL wire framing, not to field value.
            # Its value is intentionally ignored, matching LS DLL parsing behavior.
            if block.is_attr:
                offset += 1

        if offset != len(record):
            raise AssertionError(
                f"{block.name}: decoded offset {offset} != record size {len(record)}"
            )
        return result

    def framing_diagnostic(self, block: BlockSchema, packet: bytes) -> dict[str, object]:
        return {
            "packet_length": len(packet),
            "schema_body_size": block.size,
            "field_count": len(block.fields),
            "is_attr": block.is_attr,
            "wire_size": block.wire_size,
            "divisible": bool(block.wire_size and len(packet) % block.wire_size == 0),
            "preview_hex": packet[:96].hex(),
        }

    @staticmethod
    def _format(field_type: str, decimals: int, value: Any) -> str:
        if value is None:
            return ""
        kind = field_type.lower()

        if kind in {"long", "int"}:
            return str(int(value))

        if kind in {"float", "double", "decimal"}:
            number = Decimal(str(value))
            if decimals > 0:
                return f"{number:.{decimals}f}"
            return format(number, "f")

        return str(value)
