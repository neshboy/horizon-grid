"""Shared JSON Schema helpers for AI backends whose structured-output mode
doesn't resolve `$ref`/`$defs` pointers the way Pydantic's
model_json_schema() emits them for nested models (e.g. FinalAssessment's
list[MitreMapping]). Used by both gemini_client.py and ollama_client.py.
"""
from typing import Any


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively replaces every {"$ref": "#/$defs/X"} with the actual X
    definition, then drops the now-unused top-level $defs block.
    """
    defs = schema.get("$defs", {})

    def _resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_name = node["$ref"].rsplit("/", 1)[-1]
                return _resolve(defs.get(ref_name, {}))
            return {k: _resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [_resolve(item) for item in node]
        return node

    return _resolve(schema)
