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
MAX_RETRY_SLEEP = 30
DEFAULT_ACCOUNT = "default"
_ACCOUNT_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")

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


def _safe_account_name(name):
    if not name:
        return DEFAULT_ACCOUNT
    cleaned = _ACCOUNT_SAFE_RE.sub("_", name).strip("._")
    if not cleaned or cleaned in (".", ".."):
        return DEFAULT_ACCOUNT
    return cleaned[:64]


def load_account():
    config = load_config()
    raw_name = config.get("name") or DEFAULT_ACCOUNT
    return {
        "name": _safe_account_name(raw_name),
        "token": config["token"],
    }


def _die_on_http_error(e):
    try:
        body = json.loads(e.read())
    except Exception:
        print(f"HTTP {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(1)

    msg = body.get("err") or body.get("message") or body.get("error") or json.dumps(body)
    print(f"HTTP {e.code}: {msg}", file=sys.stderr)
    sys.exit(1)


def _urlopen_with_retry(req, max_attempts=3, account=None):
    saw_low_tier = False
    for attempt in range(max_attempts):
        try:
            return urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            retry_after = int(e.headers.get("Retry-After", 10))
            rate_limit_type = e.headers.get("X-Figma-Rate-Limit-Type") or None
            plan_tier = e.headers.get("X-Figma-Plan-Tier") or None
            upgrade_link = e.headers.get("X-Figma-Upgrade-Link") or None
            if account is not None:
                _throttle_write(account, retry_after, time.time(),
                                rate_limit_type=rate_limit_type, plan_tier=plan_tier)
            qualifier = []
            if rate_limit_type:
                qualifier.append(f"{rate_limit_type} tier")
            if plan_tier:
                qualifier.append(f"plan={plan_tier}")
            qualifier.append(f"Retry-After: {retry_after}s")
            if rate_limit_type == "low" and not saw_low_tier:
                saw_low_tier = True
                print(
                    "[figma: 'low' rate-limit tier — the file is likely in a non-upgraded team. "
                    "See README → Rate limits.]",
                    file=sys.stderr,
                )
                if upgrade_link:
                    print(f"[figma: upgrade info: {upgrade_link}]", file=sys.stderr)
            is_final = attempt == max_attempts - 1
            sleep_for = min(retry_after, MAX_RETRY_SLEEP)
            suffix = "giving up" if is_final else f"sleeping {sleep_for}s and retrying..."
            print(f"Rate limited ({', '.join(qualifier)}); {suffix}", file=sys.stderr)
            if is_final:
                raise
            time.sleep(sleep_for)


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


def _meta_hit(mtime, now, account=None):
    meta = {"hit": True, "fetched_at": _iso_utc(mtime), "age_seconds": int(max(0, now - mtime))}
    if account is not None:
        meta["account"] = account
    return meta


def _meta_miss(now, account=None):
    meta = {"hit": False, "fetched_at": _iso_utc(now), "age_seconds": 0}
    if account is not None:
        meta["account"] = account
    return meta


def _attach_nodes_meta(body, hits_mtimes, now, account=None):
    if not isinstance(body, dict):
        return
    nodes = body.get("nodes") or {}
    for node_id, entry in nodes.items():
        if not isinstance(entry, dict):
            continue
        if node_id in hits_mtimes:
            entry["_cache"] = _meta_hit(hits_mtimes[node_id], now, account)
            continue
        entry["_cache"] = _meta_miss(now, account)


def _attach_top_level_meta(body, mtime, now, account=None):
    if not isinstance(body, dict):
        return
    if mtime is None:
        body["_cache"] = _meta_miss(now, account)
        return
    body["_cache"] = _meta_hit(mtime, now, account)


def _throttle_file(account):
    return os.path.join(CACHE_ROOT, account, ".throttle")


def _throttle_read(account):
    try:
        with open(_throttle_file(account)) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "retry_until" not in data:
        return None
    return data


def _throttle_write(account, retry_after_seconds, now, rate_limit_type=None, plan_tier=None):
    account_dir = os.path.join(CACHE_ROOT, account)
    try:
        os.makedirs(account_dir, exist_ok=True)
        for d in (CACHE_ROOT, account_dir):
            try:
                os.chmod(d, 0o700)
            except OSError:
                pass
    except OSError:
        return
    path = _throttle_file(account)
    payload = {
        "retry_until": int(now + retry_after_seconds),
        "set_at": int(now),
        "retry_after_seconds": int(retry_after_seconds),
    }
    if rate_limit_type:
        payload["rate_limit_type"] = rate_limit_type
    if plan_tier:
        payload["plan_tier"] = plan_tier
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _throttle_clear(account):
    try:
        os.remove(_throttle_file(account))
    except OSError:
        pass


def _throttle_active(account, state=None, now=None):
    if state is None:
        state = _throttle_read(account)
    if not state:
        return False
    if now is None:
        now = time.time()
    return state.get("retry_until", 0) > now


def _throttle_describe(state, now):
    retry_until = state.get("retry_until", now)
    until_str = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(retry_until))
    remaining = _format_age(retry_until - now)
    rate_limit_type = state.get("rate_limit_type")
    tier_qualifier = f"{rate_limit_type} tier, " if rate_limit_type else ""
    return f"{tier_qualifier}until {until_str}, ~{remaining}"


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


_ENSURED_CACHE_DIRS = set()


def _cache_dirs(account, file_key):
    account_dir = os.path.join(CACHE_ROOT, account)
    base = os.path.join(account_dir, file_key)
    responses = os.path.join(base, "responses")
    nodes = os.path.join(base, "nodes")
    if base in _ENSURED_CACHE_DIRS:
        return responses, nodes
    os.makedirs(responses, exist_ok=True)
    os.makedirs(nodes, exist_ok=True)
    for d in (CACHE_ROOT, account_dir, base):
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
    _ENSURED_CACHE_DIRS.add(base)
    return responses, nodes


def _cache_response_path(account, file_key, normalized_path):
    responses, _ = _cache_dirs(account, file_key)
    digest = hashlib.sha1(normalized_path.encode("utf-8")).hexdigest()
    return os.path.join(responses, f"{digest}.json")


def _cache_node_path(account, file_key, node_id):
    _, nodes = _cache_dirs(account, file_key)
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


def _walk_index_nodes(account, file_key, node):
    if not isinstance(node, dict) or "id" not in node or "type" not in node:
        return
    _cache_write(_cache_node_path(account, file_key, node["id"]), node)
    for child in node.get("children", []) or []:
        _walk_index_nodes(account, file_key, child)


def _index_nodes_from_response(account, file_key, body):
    nodes = (body or {}).get("nodes") or {}
    for entry in nodes.values():
        doc = (entry or {}).get("document")
        if not doc:
            continue
        _walk_index_nodes(account, file_key, doc)


def _synthesize_node_entries(account, file_key, ids):
    hits = {}
    missing = []
    mtimes = {}
    for node_id in ids:
        path = _cache_node_path(account, file_key, node_id)
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


def figma_get(token, path, account):
    file_key, normalized, kind, ids, has_depth = _normalize_path(path)

    use_cache = file_key is not None and not _cache_disabled()
    read_cache = use_cache and not _cache_refresh_only()
    response_path = _cache_response_path(account, file_key, normalized) if use_cache else None
    now = time.time()

    hits = {}
    hits_mtimes = {}
    fetch_path = normalized

    if read_cache and kind == "nodes" and ids and not has_depth:
        hits, missing, hits_mtimes = _synthesize_node_entries(account, file_key, ids)
        if hits and not missing:
            oldest = min(hits_mtimes.values())
            age = _format_age(now - oldest)
            label = f"{age} old" if len(hits) == 1 else f"oldest {age}"
            print(f"[figma cache: node-hit {len(hits)}x ({label})]", file=sys.stderr)
            body = {"nodes": _wrap_nodes(hits)}
            _attach_nodes_meta(body, hits_mtimes, now, account)
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
                _attach_nodes_meta(cached, uniform, now, account)
            else:
                _attach_top_level_meta(cached, mtime, now, account)
            return cached

    throttle_state = _throttle_read(account)
    if _throttle_active(account, throttle_state, now):
        print(
            f"[figma: throttle active for '{account}' ({_throttle_describe(throttle_state, now)}) — attempting fresh fetch (may fail)]",
            file=sys.stderr,
        )

    url = f"{API_BASE}{fetch_path}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "X-Figma-Token": token,
    })
    try:
        with _urlopen_with_retry(req, account=account) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        _die_on_http_error(e)

    _throttle_clear(account)

    if use_cache and kind == "nodes" and not has_depth:
        _index_nodes_from_response(account, file_key, body)

    if hits:
        merged = dict(body.get("nodes") or {})
        for node_id, entry in _wrap_nodes(hits).items():
            merged.setdefault(node_id, entry)
        body = dict(body)
        body["nodes"] = merged

    if use_cache:
        _cache_write(response_path, body)

    if kind == "nodes":
        _attach_nodes_meta(body, hits_mtimes, now, account)
    else:
        _attach_top_level_meta(body, None, now, account)

    return body


def figma_request(token, method, path, data=None, account=None):
    if method.upper() == "GET" and data is None:
        if account is None:
            print("figma_request GET requires account=", file=sys.stderr)
            sys.exit(1)
        return figma_get(token, path, account)

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
        with _urlopen_with_retry(req, account=account) as resp:
            raw = resp.read()
            if account is not None:
                _throttle_clear(account)
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
