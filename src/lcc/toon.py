"""TOON (Token-Oriented Object Notation) Encoder for Python.

High-efficiency, zero-dependency serialization format engineered to reduce
LLM token consumption by stripping structural overhead (braces, quotes, repeated keys).
"""

from typing import Any


def _escape_value(val: Any) -> str:
    if val is None:
        return ""
    s = str(val)
    if "\n" in s:
        s_escaped = s.replace('"', '\\"').replace("\n", "\\n")
        return f'"{s_escaped}"'
    if "," in s:
        s_escaped = s.replace('"', '\\"')
        return f'"{s_escaped}"'
    return s


def _encode_array(name: str, arr: list[Any], depth: int = 0) -> str:
    indent = "  " * depth
    if not arr:
        return f"{indent}{name}[0]:"

    all_are_dicts = all(isinstance(item, dict) for item in arr)
    if all_are_dicts:
        # Collect all unique keys maintaining order
        keys: list[str] = []
        for item in arr:
            for k in item:
                if k not in keys:
                    keys.append(k)

        keys_str = ",".join(keys)
        header = f"{indent}{name}[{len(arr)}]{{{keys_str}}}:"
        rows: list[str] = []
        for item in arr:
            vals = [_escape_value(item.get(k)) for k in keys]
            rows.append(f"{indent}{','.join(vals)}")
        return "\n".join([header, *rows])

    # Primitive array
    header = f"{indent}{name}[{len(arr)}]:"
    items = [f"{indent}  - {_escape_value(item)}" for item in arr]
    return "\n".join([header, *items])


def encode_toon(data: Any, root_name: str = "data") -> str:
    """Encodes a Python object/list into TOON string representation."""
    if isinstance(data, list):
        return _encode_array(root_name, data, 0)

    if not isinstance(data, dict):
        return f"{root_name}: {_escape_value(data)}"

    lines: list[str] = []
    for key, value in data.items():
        if value is None:
            continue

        if isinstance(value, list):
            lines.append(_encode_array(key, value, 0))
        elif isinstance(value, dict):
            lines.append(f"{key}:")
            sub = encode_toon(value, root_name=key)
            indented = "\n".join("  " + line for line in sub.split("\n"))
            lines.append(indented)
        else:
            lines.append(f"{key}: {_escape_value(value)}")

    return "\n".join(lines)
