from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .codec import PacketCodec
from .loaders import JsonSchemaLoader, ResSchemaLoader
from .model import TrSchema


RES_TRS = ("t8424", "t8436", "t8429", "t8451")
JSON_TRS = ("t1516", "t1702")
REQUIRED_TRS = RES_TRS + JSON_TRS


@dataclass(frozen=True, slots=True)
class SchemaSource:
    tr_code: str
    path: Path
    kind: str


class TrSchemaService:
    """Only loaders differ. Everything after load() uses the same TrSchema API."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root).resolve()
        self._res_loader = ResSchemaLoader()
        self._json_loader = JsonSchemaLoader()
        self._cache: dict[str, TrSchema] = {}
        self.codec = PacketCodec()

    def source(self, tr_code: str) -> SchemaSource:
        code = tr_code.lower()
        if code in RES_TRS:
            path = self.project_root / "resources" / "xing" / "current_res" / f"{code}.res"
            return SchemaSource(code, path, "res")
        if code in JSON_TRS:
            path = self.project_root / "resources" / "xing" / "schemas" / f"{code}.json"
            return SchemaSource(code, path, "json")
        raise KeyError(f"unsupported TR: {tr_code}")

    def load(self, tr_code: str) -> TrSchema:
        code = tr_code.lower()
        cached = self._cache.get(code)
        if cached is not None:
            return cached

        source = self.source(code)
        if not source.path.is_file():
            raise FileNotFoundError(source.path)

        loader = self._res_loader if source.kind == "res" else self._json_loader
        schema = loader.load(source.path)
        if schema.tr_code.lower() != code:
            raise ValueError(
                f"TR mismatch: requested={code}, parsed={schema.tr_code}, source={source.path}"
            )
        self._cache[code] = schema
        return schema

    def load_all(self) -> dict[str, TrSchema]:
        return {tr: self.load(tr) for tr in REQUIRED_TRS}

    def clear_cache(self) -> None:
        self._cache.clear()


@dataclass(frozen=True, slots=True)
class XingRequestPlan:
    schema: TrSchema
    input_block_name: str

    @property
    def input_block(self):
        return self.schema.block(self.input_block_name)


class XingRequestPlanner:
    """Common request-plan factory; source format is already hidden by TrSchemaService."""

    def __init__(self, schemas: TrSchemaService) -> None:
        self.schemas = schemas

    def plan(self, tr_code: str, input_block_name: str | None = None) -> XingRequestPlan:
        schema = self.schemas.load(tr_code)
        if input_block_name:
            block_name = input_block_name
        else:
            if not schema.input_blocks:
                raise ValueError(f"{tr_code}: no input block")
            block_name = schema.input_blocks[0].name
        return XingRequestPlan(schema=schema, input_block_name=block_name)
