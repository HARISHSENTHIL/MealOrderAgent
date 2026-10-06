"""Small helpers shared across tools and agents."""

from typing import Any


def find_key(obj: Any, key: str) -> Any:
    """Depth-first search for the first value under `key` in nested dicts/lists."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = find_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_key(v, key)
            if found is not None:
                return found
    return None
