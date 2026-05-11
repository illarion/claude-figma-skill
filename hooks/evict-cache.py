#!/usr/bin/env python3
"""Trim figma-skill caches at session start: drop TTL-stale entries, then evict
LRU-first until total cache size is under FIGMA_SKILL_CACHE_MAX_BYTES."""

import os
import sys
import time
import tempfile

CACHE_DIRS = [
    os.path.join(os.path.expanduser("~"), ".cache", "figma-skill"),
    os.path.join(tempfile.gettempdir(), "figma-exports"),
]
DEFAULT_MAX_BYTES = 500 * 1024 * 1024
DEFAULT_TTL = 3600


def _flag(name):
    raw = os.environ.get(name, "").strip().lower()
    return raw not in ("", "0", "false", "no")


def _int_env(name, default):
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _iter_files(root):
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            yield os.path.join(dirpath, name)


def _remove(path):
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def _prune_empty_dirs(root):
    for dirpath, _, _ in os.walk(root, topdown=False):
        if dirpath == root:
            continue
        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:
            pass


def main():
    if _flag("FIGMA_SKILL_NO_CACHE"):
        return

    ttl = _int_env("FIGMA_SKILL_CACHE_TTL", DEFAULT_TTL)
    max_bytes = _int_env("FIGMA_SKILL_CACHE_MAX_BYTES", DEFAULT_MAX_BYTES)
    now = time.time()

    stale_removed = 0
    stale_bytes = 0
    survivors = []

    for root in CACHE_DIRS:
        if not os.path.isdir(root):
            continue
        for path in _iter_files(root):
            try:
                st = os.stat(path)
            except OSError:
                continue
            if path.endswith(".tmp"):
                if _remove(path):
                    stale_removed += 1
                    stale_bytes += st.st_size
                continue
            if (now - st.st_mtime) > ttl:
                if _remove(path):
                    stale_removed += 1
                    stale_bytes += st.st_size
                continue
            survivors.append((path, st.st_atime, st.st_size))

    total = sum(size for _, _, size in survivors)
    lru_removed = 0
    lru_bytes = 0

    if max_bytes > 0 and total > max_bytes:
        survivors.sort(key=lambda x: x[1])
        for path, _, size in survivors:
            if total <= max_bytes:
                break
            if _remove(path):
                lru_removed += 1
                lru_bytes += size
                total -= size

    for root in CACHE_DIRS:
        if os.path.isdir(root):
            _prune_empty_dirs(root)

    if not stale_removed and not lru_removed:
        return

    parts = []
    if stale_removed:
        parts.append(f"{stale_removed} stale ({stale_bytes // 1024} KB)")
    if lru_removed:
        parts.append(f"{lru_removed} LRU ({lru_bytes // 1024} KB)")
    print(f"[figma cache evict: {', '.join(parts)}]", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[figma cache evict: error {e}]", file=sys.stderr)
