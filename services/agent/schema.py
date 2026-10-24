"""Convert MCP tool input JSON Schemas into Pydantic models.

LangChain (and the Gemini function-calling API) need a concrete argument
schema per tool. MCP servers publish JSON Schema, so we translate the subset we
care about into a ``pydantic`` model. Anything we do not understand degrades to
``Any`` rather than failing the whole request.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

_SCALAR_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


def _literal(values: list[Any]) -> Any:
    from typing import Literal

    return Literal[tuple(values)]  # type: ignore[valid-type]


def _field_type(schema: dict[str, Any]) -> Any:
    if not isinstance(schema, dict):
        return Any

    if "enum" in schema and isinstance(schema["enum"], list) and schema["enum"]:
        if all(isinstance(item, str) for item in schema["enum"]):
            return _literal(schema["enum"])

    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        types = [option for option in schema["anyOf"] if option.get("type") != "null"]
        nullable = len(types) != len(schema["anyOf"])
        resolved = _field_type(types[0]) if len(types) == 1 else Any
        return resolved | None if nullable else resolved  # type: ignore[operator]

    json_type = schema.get("type")
    if isinstance(json_type, list):
        non_null = [item for item in json_type if item != "null"]
        nullable = len(non_null) != len(json_type)
        resolved = _field_type({"type": non_null[0]}) if len(non_null) == 1 else Any
        return resolved | None if nullable else resolved  # type: ignore[operator]

    if json_type in _SCALAR_TYPES:
        return _SCALAR_TYPES[json_type]
    if json_type == "array":
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        return list[_field_type(item_schema)]  # type: ignore[valid-type]
    if json_type == "object":
        return dict[str, Any]
    return Any


def json_schema_to_model(name: str, schema: dict[str, Any] | None) -> type[BaseModel]:
    """Build a Pydantic model for one tool's ``inputSchema``.

    Non-object or malformed schemas yield an empty model so the tool can still
    be advertised (with no arguments) instead of disappearing.
    """
    schema = schema or {}
    if schema.get("type") not in (None, "object") or not isinstance(
        schema.get("properties"), dict
    ):
        return create_model(name)

    required = set(schema.get("required") or [])
    fields: dict[str, tuple[Any, Any]] = {}
    for prop_name, prop_schema in schema["properties"].items():
        prop_schema = prop_schema if isinstance(prop_schema, dict) else {}
        annotation = _field_type(prop_schema)
        description = prop_schema.get("description")
        default: Any = ...
        if prop_name not in required:
            annotation = annotation | None  # type: ignore[operator]
            default = prop_schema.get("default", None)
        fields[prop_name] = (
            annotation,
            Field(default, description=description) if description else Field(default),
        )
    # Unknown arguments are rejected instead of silently dropped: a model that
    # misspells an argument would otherwise get a successful call that quietly
    # used default values.
    return create_model(name, __config__=ConfigDict(extra="forbid"), **fields)
