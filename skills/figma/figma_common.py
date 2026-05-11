#!/usr/bin/env python3
"""Shared Figma credential and HTTP management."""

import os
import sys
import json
import math
import time
import hashlib
import urllib.request
import urllib.error
import urllib.parse
import re

DOTFILE = ".figmaskillrc"
API_BASE = "https://api.figma.com"
HTTP_TIMEOUT = 55

CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".cache", "figma-skill")
CACHE_TTL_DEFAULT = 3600

FILE_RE = re.compile(r"^/v1/files/([A-Za-z0-9]+)/?$")
FILE_NODES_RE = re.compile(r"^/v1/files/([A-Za-z0-9]+)/nodes/?$")


def _find_dotfile():
    path = os.path.abspath(os.getcwd())
    while True:
        candidate = os.path.join(path, DOTFILE)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return None


def load_config():
    dotfile = _find_dotfile()
    if not dotfile:
        print(f"No {DOTFILE} found in any parent directory.", file=sys.stderr)
        print("Run: python3 SCRIPT_DIR/figma-auth.py login", file=sys.stderr)
        sys.exit(1)
    with open(dotfile) as f:
        config = json.load(f)
    name = config.get("name") or os.path.basename(os.path.dirname(dotfile))
    print(f"[figma: {name}]", file=sys.stderr)
    return config


def save_config(path, config):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    os.chmod(path, 0o600)


def load_credentials():
    config = load_config()
    return config["token"]


def _die_on_http_error(e):
    try:
        body = json.loads(e.read())
    except Exception:
        print(f"HTTP {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(1)

    msg = body.get("err") or body.get("message") or body.get("error") or json.dumps(body)
    print(f"HTTP {e.code}: {msg}", file=sys.stderr)
    sys.exit(1)


def _urlopen_with_retry(req, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            return urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == max_attempts - 1:
                raise
            retry_after = int(e.headers.get("Retry-After", 10))
            print(f"Rate limited, retrying in {retry_after}s...", file=sys.stderr)
            time.sleep(retry_after)


def _env_flag(name):
    raw = os.environ.get(name, "").strip().lower()
    return raw not in ("", "0", "false", "no")


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


def _iso_utc(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _meta_hit(mtime, now):
    return {"hit": True, "fetched_at": _iso_utc(mtime), "age_seconds": int(max(0, now - mtime))}


def _meta_miss(now):
    return {"hit": False, "fetched_at": _iso_utc(now), "age_seconds": 0}


def _attach_nodes_meta(body, hits_mtimes, now):
    if not isinstance(body, dict):
        return
    nodes = body.get("nodes") or {}
    for node_id, entry in nodes.items():
        if not isinstance(entry, dict):
            continue
        if node_id in hits_mtimes:
            entry["_cache"] = _meta_hit(hits_mtimes[node_id], now)
            continue
        entry["_cache"] = _meta_miss(now)


def _attach_top_level_meta(body, mtime, now):
    if not isinstance(body, dict):
        return
    if mtime is None:
        body["_cache"] = _meta_miss(now)
        return
    body["_cache"] = _meta_hit(mtime, now)


def _cache_disabled():
    return _env_flag("FIGMA_SKILL_NO_CACHE")


def _cache_refresh_only():
    return _env_flag("FIGMA_SKILL_REFRESH")


def _cache_ttl():
    raw = os.environ.get("FIGMA_SKILL_CACHE_TTL")
    if not raw:
        return CACHE_TTL_DEFAULT
    try:
        return max(0, int(raw))
    except ValueError:
        return CACHE_TTL_DEFAULT


def _cache_dirs(file_key):
    base = os.path.join(CACHE_ROOT, file_key)
    responses = os.path.join(base, "responses")
    nodes = os.path.join(base, "nodes")
    os.makedirs(responses, exist_ok=True)
    os.makedirs(nodes, exist_ok=True)
    for d in (CACHE_ROOT, base):
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
    return responses, nodes


def _cache_response_path(file_key, normalized_path):
    responses, _ = _cache_dirs(file_key)
    digest = hashlib.sha1(normalized_path.encode("utf-8")).hexdigest()
    return os.path.join(responses, f"{digest}.json")


def _cache_node_path(file_key, node_id):
    _, nodes = _cache_dirs(file_key)
    safe = node_id.replace(":", "_").replace("/", "_").replace("..", "_")
    return os.path.join(nodes, f"{safe}.json")


def _cache_read(path):
    if not os.path.exists(path):
        return None
    try:
        if time.time() - os.path.getmtime(path) > _cache_ttl():
            return None
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _cache_write(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _normalize_path(path):
    parsed = urllib.parse.urlsplit(path)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    file_key = None
    kind = "other"
    ids = None

    nodes_match = FILE_NODES_RE.match(parsed.path)
    file_match = FILE_RE.match(parsed.path)

    if nodes_match:
        kind = "nodes"
        file_key = nodes_match.group(1)
        raw_ids = query.get("ids", [""])[0]
        ids = sorted(i for i in raw_ids.split(",") if i)
        query["ids"] = [",".join(ids)]
        if "geometry" not in query:
            query["geometry"] = ["paths"]
    elif file_match:
        kind = "file"
        file_key = file_match.group(1)

    pairs = []
    for k in sorted(query.keys()):
        for v in query[k]:
            pairs.append((k, v))
    new_query = urllib.parse.urlencode(pairs)
    normalized = urllib.parse.urlunsplit(("", "", parsed.path, new_query, ""))

    has_depth = "depth" in query
    return file_key, normalized, kind, ids, has_depth


def _rewrite_nodes_path(path, new_ids):
    parsed = urllib.parse.urlsplit(path)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    query["ids"] = [",".join(new_ids)]
    pairs = [(k, v) for k in query for v in query[k]]
    new_query = urllib.parse.urlencode(pairs)
    return urllib.parse.urlunsplit(("", "", parsed.path, new_query, ""))


def _walk_index_nodes(file_key, node):
    if not isinstance(node, dict) or "id" not in node or "type" not in node:
        return
    _cache_write(_cache_node_path(file_key, node["id"]), node)
    for child in node.get("children", []) or []:
        _walk_index_nodes(file_key, child)


def _index_nodes_from_response(file_key, body):
    nodes = (body or {}).get("nodes") or {}
    for entry in nodes.values():
        doc = (entry or {}).get("document")
        if not doc:
            continue
        _walk_index_nodes(file_key, doc)


def _synthesize_node_entries(file_key, ids):
    hits = {}
    missing = []
    mtimes = {}
    for node_id in ids:
        path = _cache_node_path(file_key, node_id)
        cached = _cache_read(path)
        if cached is None:
            missing.append(node_id)
            continue
        hits[node_id] = cached
        try:
            mtimes[node_id] = os.path.getmtime(path)
        except OSError:
            mtimes[node_id] = time.time()
    return hits, missing, mtimes


def _wrap_nodes(hits):
    return {
        node_id: {
            "document": doc,
            "components": {},
            "componentSets": {},
            "schemaVersion": 0,
            "styles": {},
        }
        for node_id, doc in hits.items()
    }


def figma_get(token, path):
    file_key, normalized, kind, ids, has_depth = _normalize_path(path)

    use_cache = file_key is not None and not _cache_disabled()
    read_cache = use_cache and not _cache_refresh_only()
    response_path = _cache_response_path(file_key, normalized) if use_cache else None
    now = time.time()

    hits = {}
    hits_mtimes = {}
    fetch_path = normalized

    if read_cache and kind == "nodes" and ids and not has_depth:
        hits, missing, hits_mtimes = _synthesize_node_entries(file_key, ids)
        if hits and not missing:
            oldest = min(hits_mtimes.values())
            age = _format_age(now - oldest)
            label = f"{age} old" if len(hits) == 1 else f"oldest {age}"
            print(f"[figma cache: node-hit {len(hits)}x ({label})]", file=sys.stderr)
            body = {"nodes": _wrap_nodes(hits)}
            _attach_nodes_meta(body, hits_mtimes, now)
            return body
        if hits:
            oldest = min(hits_mtimes.values())
            print(
                f"[figma cache: partial-hit {len(hits)}/{len(ids)} "
                f"(oldest {_format_age(now - oldest)}), fetching {len(missing)}]",
                file=sys.stderr,
            )
            fetch_path = _rewrite_nodes_path(normalized, missing)

    if read_cache and not hits:
        cached = _cache_read(response_path)
        if cached is not None:
            try:
                mtime = os.path.getmtime(response_path)
            except OSError:
                mtime = now
            print(f"[figma cache: response-hit ({_format_age(now - mtime)} old)]", file=sys.stderr)
            if kind == "nodes" and isinstance(cached, dict) and isinstance(cached.get("nodes"), dict):
                uniform = {nid: mtime for nid in cached["nodes"]}
                _attach_nodes_meta(cached, uniform, now)
            else:
                _attach_top_level_meta(cached, mtime, now)
            return cached

    url = f"{API_BASE}{fetch_path}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "X-Figma-Token": token,
    })
    try:
        with _urlopen_with_retry(req) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        _die_on_http_error(e)

    if use_cache and kind == "nodes" and not has_depth:
        _index_nodes_from_response(file_key, body)

    if hits:
        merged = dict(body.get("nodes") or {})
        for node_id, entry in _wrap_nodes(hits).items():
            merged.setdefault(node_id, entry)
        body = dict(body)
        body["nodes"] = merged

    if use_cache:
        _cache_write(response_path, body)

    if kind == "nodes":
        _attach_nodes_meta(body, hits_mtimes, now)
    else:
        _attach_top_level_meta(body, None, now)

    return body


def figma_request(token, method, path, data=None):
    if method.upper() == "GET" and data is None:
        return figma_get(token, path)

    url = f"{API_BASE}{path}"
    headers = {
        "Accept": "application/json",
        "X-Figma-Token": token,
    }
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method=method.upper(), headers=headers)
    try:
        with _urlopen_with_retry(req) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        _die_on_http_error(e)


def parse_figma_url(url):
    """Extract (file_key, node_id_or_None) from a Figma URL."""
    parsed = urllib.parse.urlparse(url)
    path_match = re.match(r"^/(?:file|design|proto|board|slides|deck)/([A-Za-z0-9]+)", parsed.path)
    if not path_match:
        print(f"Invalid Figma URL: {url}", file=sys.stderr)
        sys.exit(1)

    file_key = path_match.group(1)
    params = urllib.parse.parse_qs(parsed.query)
    node_id = None
    if "node-id" in params:
        node_id = params["node-id"][0].replace("-", ":")

    return file_key, node_id


def rgba_to_hex(r, g, b, a=1.0):
    """Convert Figma 0-1 RGBA to CSS color string."""
    ri, gi, bi = round(r * 255), round(g * 255), round(b * 255)
    if a >= 0.999:
        return f"#{ri:02X}{gi:02X}{bi:02X}"
    return f"rgba({ri}, {gi}, {bi}, {round(a, 2)})"


def figma_length(value):
    """Convert a numeric value to CSS px string."""
    if value == 0:
        return "0"
    rounded = round(value)
    if rounded == value:
        return f"{rounded}px"
    return f"{round(value, 1)}px"
