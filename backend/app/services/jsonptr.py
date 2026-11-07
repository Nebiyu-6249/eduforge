"""Minimal RFC 6901 JSON Pointer + RFC 6902 add/replace/remove on plain dicts."""

from __future__ import annotations

import copy
from typing import Any

_MISSING = object()


class PatchError(ValueError):
    pass


def parse(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise PatchError(f"Path must start with '/': {path!r}")
    return [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")]


def _step(container: Any, token: str, path: str) -> Any:
    if isinstance(container, dict):
        if token not in container:
            raise PatchError(f"No field '{token}' at {path}")
        return container[token]
    if isinstance(container, list):
        try:
            i = int(token)
        except ValueError:
            raise PatchError(f"Expected a list index at {path}, got '{token}'") from None
        if not 0 <= i < len(container):
            raise PatchError(f"Index {i} out of range at {path}")
        return container[i]
    raise PatchError(f"Cannot descend into a value at {path}")


def get(doc: Any, path: str, default: Any = _MISSING) -> Any:
    cur = doc
    try:
        for t in parse(path):
            cur = _step(cur, t, path)
    except PatchError:
        if default is not _MISSING:
            return default
        raise
    return cur


def apply(doc: dict, op: str, path: str, value: Any = None) -> tuple[dict, Any]:
    """Return (new_doc, old_value). ``doc`` is not modified."""
    tokens = parse(path)
    if not tokens:
        raise PatchError("Cannot replace the whole record.")
    new = copy.deepcopy(doc)
    parent = new
    for t in tokens[:-1]:
        parent = _step(parent, t, path)
    last = tokens[-1]
    if isinstance(parent, dict):
        old = parent.get(last)
        if op == "remove":
            if last not in parent:
                raise PatchError(f"No field '{last}' at {path}")
            del parent[last]
        elif op in ("replace", "add"):
            if op == "replace" and last not in parent:
                raise PatchError(f"No field '{last}' at {path}")
            parent[last] = value
        else:
            raise PatchError(f"Unsupported op '{op}'")
        return new, old
    if isinstance(parent, list):
        if last == "-" and op == "add":
            parent.append(value)
            return new, None
        try:
            i = int(last)
        except ValueError:
            raise PatchError(f"Expected a list index at {path}") from None
        if op == "add":
            if not 0 <= i <= len(parent):
                raise PatchError(f"Index {i} out of range at {path}")
            parent.insert(i, value)
            return new, None
        if not 0 <= i < len(parent):
            raise PatchError(f"Index {i} out of range at {path}")
        old = parent[i]
        if op == "replace":
            parent[i] = value
        elif op == "remove":
            del parent[i]
        else:
            raise PatchError(f"Unsupported op '{op}'")
        return new, old
    raise PatchError(f"Cannot modify a value at {path}")
