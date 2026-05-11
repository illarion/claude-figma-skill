#!/usr/bin/env python3
"""Trim figma-skill caches at session start. Per-account: skip eviction for any
account with an active .throttle file; LRU-evict the rest under
FIGMA_SKILL_CACHE_MAX_BYTES."""

import json
import os
import shutil
import sys
import time
import tempfile

CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".cache", "figma-skill")
EXPORTS_ROOT = os.path.join(tempfile.gettempdir(), "figma-exports")
CACHE_DIRS = [CACHE_ROOT, EXPORTS_ROOT]
DEFAULT_MAX_BYTES = 500 * 1024 * 1024
DEFAULT_TTL = 3600
IMAGE_EXTS = (".png", ".svg", ".jpg", ".jpeg", ".pdf")


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


def _format_age(seconds):
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        h = s // 3600
        m = (s % 3600) // 60
        if m:
            return f"{h}h{m}m"
        return f"{h}h"
    d = s // 86400
    h = (s % 86400) // 3600
    if h:
        return f"{d}d{h}h"
    return f"{d}d"


def _read_throttle(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    retry_until = data.get("retry_until")
    if not isinstance(retry_until, (int, float)):
        return None
    return data


def _account_from_path(path, root):
    rel = os.path.relpath(path, root)
    parts = rel.split(os.sep)
    if not parts or parts[0] in ("", "."):
        return None
    return parts[0]


def _prune_empty_dirs(root):
    for dirpath, _, _ in os.walk(root, topdown=False):
        if dirpath == root:
            continue
        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:
            pass


def _migrate_legacy_layout():
    removed = []

    legacy_throttle = os.path.join(CACHE_ROOT, ".throttle")
    if os.path.isfile(legacy_throttle):
        if _remove(legacy_throttle):
            removed.append("legacy .throttle")

    if os.path.isdir(CACHE_ROOT):
        for entry in os.listdir(CACHE_ROOT):
            full = os.path.join(CACHE_ROOT, entry)
            if not os.path.isdir(full):
                continue
            if os.path.isdir(os.path.join(full, "responses")) or os.path.isdir(os.path.join(full, "nodes")):
                try:
                    shutil.rmtree(full)
                    removed.append(f"legacy cache dir '{entry}'")
                except OSError:
                    pass

    if os.path.isdir(EXPORTS_ROOT):
        for entry in os.listdir(EXPORTS_ROOT):
            full = os.path.join(EXPORTS_ROOT, entry)
            if os.path.isfile(full) and entry.lower().endswith(IMAGE_EXTS):
                if _remove(full):
                    removed.append(f"legacy export '{entry}'")

    if removed:
        print(
            f"[figma cache evict: migrated from pre-namespace layout, removed {len(removed)} item(s)]",
            file=sys.stderr,
        )


def _classify_accounts(now):
    throttled = set()
    notes = []
    if not os.path.isdir(CACHE_ROOT):
        return throttled, notes
    for entry in sorted(os.listdir(CACHE_ROOT)):
        account_dir = os.path.join(CACHE_ROOT, entry)
        if not os.path.isdir(account_dir):
            continue
        throttle_path = os.path.join(account_dir, ".throttle")
        state = _read_throttle(throttle_path)
        if state is None:
            continue
        retry_until = state["retry_until"]
        if retry_until > now:
            throttled.add(entry)
            until_str = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(retry_until))
            remaining = _format_age(retry_until - now)
            rate_limit_type = state.get("rate_limit_type")
            tier_qualifier = f"{rate_limit_type} tier, " if rate_limit_type else ""
            notes.append(
                f"[figma cache evict: throttle active for '{entry}' ({tier_qualifier}until {until_str}, ~{remaining}) — preserving '{entry}' cache]"
            )
            continue
        _remove(throttle_path)
        notes.append(f"[figma cache evict: throttle expired for '{entry}', resuming normal eviction]")
    return throttled, notes


def main():
    if _flag("FIGMA_SKILL_NO_CACHE"):
        return

    _migrate_legacy_layout()

    ttl = _int_env("FIGMA_SKILL_CACHE_TTL", DEFAULT_TTL)
    max_bytes = _int_env("FIGMA_SKILL_CACHE_MAX_BYTES", DEFAULT_MAX_BYTES)
    now = time.time()

    throttled, notes = _classify_accounts(now)
    for line in notes:
        print(line, file=sys.stderr)

    stale_removed = 0
    stale_bytes = 0
    tmp_removed = 0
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
                    tmp_removed += 1
                    stale_bytes += st.st_size
                continue
            account = _account_from_path(path, root)
            if account in throttled:
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

    if not stale_removed and not lru_removed and not tmp_removed:
        return

    parts = []
    total_stale = stale_removed + tmp_removed
    if total_stale:
        parts.append(f"{total_stale} stale ({stale_bytes // 1024} KB)")
    if lru_removed:
        parts.append(f"{lru_removed} LRU ({lru_bytes // 1024} KB)")
    preserved = (
        f", preserved {', '.join(sorted(repr(a) for a in throttled))} under throttle"
        if throttled
        else ""
    )
    print(f"[figma cache evict: {', '.join(parts)}{preserved}]", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[figma cache evict: error {e}]", file=sys.stderr)
