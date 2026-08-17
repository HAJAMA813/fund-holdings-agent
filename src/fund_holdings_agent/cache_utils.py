from __future__ import annotations

import logging
from pathlib import Path


def read_cache_text(path: Path) -> str | None:
    """Return usable UTF-8 cache text; quarantine physically corrupt files."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        quarantined = quarantine_cache(path)
        logging.warning("缓存读取失败，已旁路保存 %s -> %s: %s", path, quarantined, exc)
        return None
    if not text.strip() or "\x00" in text:
        quarantined = quarantine_cache(path)
        logging.warning("缓存为空或含空字节，已旁路保存 %s -> %s", path, quarantined)
        return None
    return text


def atomic_write_cache(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return path


def quarantine_cache(path: Path) -> Path:
    candidate = path.with_suffix(path.suffix + ".corrupt")
    index = 1
    while candidate.exists():
        candidate = path.with_suffix(path.suffix + f".corrupt.{index}")
        index += 1
    path.replace(candidate)
    return candidate
