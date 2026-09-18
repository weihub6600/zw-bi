from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any


_LEGACY_CATEGORY_SEPARATOR_RE = re.compile(r"[,，、;；|\r\n]+")


def normalize_category_names(values: Iterable[Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = str(value or "").strip()
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


def parse_category_names(value: Any, *, known_names: Iterable[str] = ()) -> list[str]:
    """Parse the canonical JSON format and historical delimiter formats.

    JSON arrays are the unambiguous exchange format. For legacy scalar text,
    an exact dictionary match wins before delimiter parsing so an existing
    category such as ``礼盒、套装`` remains one category.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return normalize_category_names(value)

    raw = str(value).strip()
    if not raw:
        return []
    raw = raw.replace(r"\r\n", "\n").replace(r"\n", "\n").replace(r"\r", "\r")

    if raw.startswith("[") and raw.endswith("]"):
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            decoded = None
        if isinstance(decoded, list):
            return normalize_category_names(decoded)

    known = {str(name).strip() for name in known_names if str(name).strip()}
    if raw in known:
        return [raw]
    return normalize_category_names(_LEGACY_CATEGORY_SEPARATOR_RE.split(raw))


def serialize_category_names(values: Iterable[Any]) -> str | None:
    names = normalize_category_names(values)
    if not names:
        return None
    return json.dumps(names, ensure_ascii=False, separators=(",", ":"))


def display_category_names(values: Iterable[Any]) -> str:
    return "、".join(normalize_category_names(values))
