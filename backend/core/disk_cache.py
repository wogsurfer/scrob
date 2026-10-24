"""A small JSON cache on disk for slow lookups (award lists, Wikidata), so a
backend restart doesn't send every page back to the slow path.

Each entry is one file: data/cache/<namespace>/<key>.json.
"""
import json
import time

from core.config import settings


def _path(namespace: str, key):
    return settings.data_dir / "cache" / namespace / f"{key}.json"


def load(namespace: str, key, ttl: float):
    """The saved value and when it was saved, or None if missing or older than ttl."""
    try:
        with open(_path(namespace, key), encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return None
    if time.time() - saved.get("saved_at", 0) > ttl:
        return None
    return saved["saved_at"], saved["value"]


def save(namespace: str, key, value) -> None:
    path = _path(namespace, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"saved_at": time.time(), "value": value}, f)
        tmp.replace(path)
    except OSError as e:
        print(f"Couldn't save {namespace}/{key} to the disk cache: {e!r}")
