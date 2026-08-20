"""
JSON Schema validation for tool arguments.

Capability boundary (built-in subset, always available):
  type (object/array/string/integer/number/boolean),
  properties, required, additionalProperties,
  items, minItems, maxItems,
  enum, minimum, maximum, minLength, maxLength, pattern (re).

Optional: set EMMERCE_JSONSCHEMA=1 (or pass use_jsonschema=True) to prefer the
`jsonschema` package when installed; falls back to the subset on ImportError.
"""

from __future__ import annotations

import os
import re
from typing import Any

from emmerce_agent.domain.errors import ValidationFailed

# Documented subset keywords — keep in sync with validate_json_schema_subset
SUPPORTED_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "enum",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
    }
)


def validate_json_schema(
    instance: Any,
    schema: dict[str, Any],
    *,
    path: str = "$",
    use_jsonschema: bool | None = None,
) -> None:
    if use_jsonschema is None:
        use_jsonschema = os.getenv("EMMERCE_JSONSCHEMA", "").lower() in {"1", "true", "yes"}
    if use_jsonschema:
        try:
            import jsonschema  # type: ignore[import-untyped]

            jsonschema.validate(instance=instance, schema=schema)
            return
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001 — map to domain error
            raise ValidationFailed(f"{path} schema 校验失败: {e}") from e
    validate_json_schema_subset(instance, schema, path=path)


def validate_json_schema_subset(instance: Any, schema: dict[str, Any], *, path: str = "$") -> None:
    """Built-in subset — enough for current tool specs without external deps."""
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(instance, dict):
            raise ValidationFailed(f"{path} 应为 object")
        required = schema.get("required") or []
        for key in required:
            if key not in instance:
                raise ValidationFailed(f"{path}.{key} 为必填")
        props = schema.get("properties") or {}
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in props:
                validate_json_schema_subset(value, props[key], path=f"{path}.{key}")
            elif additional is False:
                raise ValidationFailed(f"{path} 不允许额外字段: {key}")
        return

    if expected == "array":
        if not isinstance(instance, list):
            raise ValidationFailed(f"{path} 应为 array")
        min_items = schema.get("minItems")
        if min_items is not None and len(instance) < min_items:
            raise ValidationFailed(f"{path} 至少 {min_items} 项")
        max_items = schema.get("maxItems")
        if max_items is not None and len(instance) > max_items:
            raise ValidationFailed(f"{path} 至多 {max_items} 项")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(instance):
                validate_json_schema_subset(item, item_schema, path=f"{path}[{i}]")
        return

    if expected == "string":
        if not isinstance(instance, str):
            raise ValidationFailed(f"{path} 应为 string")
        if "minLength" in schema and len(instance) < schema["minLength"]:
            raise ValidationFailed(f"{path} 长度小于 minLength")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            raise ValidationFailed(f"{path} 长度大于 maxLength")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            raise ValidationFailed(f"{path} 不匹配 pattern")
    elif expected == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            raise ValidationFailed(f"{path} 应为 integer")
        if "minimum" in schema and instance < schema["minimum"]:
            raise ValidationFailed(f"{path} 小于 minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            raise ValidationFailed(f"{path} 大于 maximum")
    elif expected == "number":
        if not isinstance(instance, (int, float)) or isinstance(instance, bool):
            raise ValidationFailed(f"{path} 应为 number")
        if "minimum" in schema and instance < schema["minimum"]:
            raise ValidationFailed(f"{path} 小于 minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            raise ValidationFailed(f"{path} 大于 maximum")
    elif expected == "boolean":
        if not isinstance(instance, bool):
            raise ValidationFailed(f"{path} 应为 boolean")

    if "enum" in schema and instance not in schema["enum"]:
        raise ValidationFailed(f"{path} 不在枚举 {schema['enum']} 内: {instance}")
