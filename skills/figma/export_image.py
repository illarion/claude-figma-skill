#!/usr/bin/env python3
"""Export a Figma node as an image file."""

import os
import sys
import json
import time
import tempfile
import argparse
import urllib.parse
import urllib.request
from figma_common import (
    load_account, figma_get, parse_figma_url,
    _format_age, _meta_hit, _meta_miss, _env_flag,
)


EXPORTS_ROOT = os.path.join(tempfile.gettempdir(), "figma-exports")


def main():
    parser = argparse.ArgumentParser(description="Export a Figma node as image")
    parser.add_argument("url", nargs="?", help="Figma URL with node-id")
    parser.add_argument("--file", help="File key")
    parser.add_argument("--node", help="Node ID (e.g. 12:34)")
    parser.add_argument("--format", default="png", choices=["png", "svg", "jpg", "pdf"],
                        help="Export format (default: png)")
    parser.add_argument("--scale", type=int, default=2, choices=[1, 2, 3, 4],
                        help="Scale factor (default: 2, raster only)")
    parser.add_argument("--refresh", action="store_true", help="Bypass cache for this call and re-fetch from Figma")
    args = parser.parse_args()

    if args.refresh:
        os.environ["FIGMA_SKILL_REFRESH"] = "1"

    file_key = args.file
    node_id = args.node
    if args.url:
        file_key, node_id = parse_figma_url(args.url)

    if not file_key or not node_id:
        print("Provide a Figma URL with node-id, or --file and --node", file=sys.stderr)
        sys.exit(1)

    cfg = load_account()
    exports_dir = os.path.join(EXPORTS_ROOT, cfg["name"])
    os.makedirs(exports_dir, exist_ok=True)
    safe_node = node_id.replace(":", "-")
    filename = f"{file_key}_{safe_node}_{args.scale}x.{args.format}"
    dest = os.path.join(exports_dir, filename)

    no_cache = _env_flag("FIGMA_SKILL_NO_CACHE")
    refresh = _env_flag("FIGMA_SKILL_REFRESH")
    now = time.time()

    try:
        mtime = os.path.getmtime(dest) if not no_cache and not refresh else None
    except OSError:
        mtime = None

    if mtime is not None:
        print(f"[figma export: cached for '{cfg['name']}' ({_format_age(now - mtime)} old)]", file=sys.stderr)
        print(json.dumps({
            "node_id": node_id,
            "format": args.format,
            "scale": args.scale,
            "local_path": dest,
            "cached": True,
            "_cache": _meta_hit(mtime, now, cfg["name"]),
        }, indent=2))
        return

    params = {
        "ids": node_id,
        "format": args.format,
    }
    if args.format in ("png", "jpg"):
        params["scale"] = str(args.scale)

    query = urllib.parse.urlencode(params)
    data = figma_get(cfg["token"], f"/v1/images/{file_key}?{query}", account=cfg["name"])

    images = data.get("images", {})
    image_url = images.get(node_id)
    if not image_url:
        print(f"No image generated for node {node_id}", file=sys.stderr)
        sys.exit(1)

    req = urllib.request.Request(image_url)
    with urllib.request.urlopen(req, timeout=55) as resp:
        with open(dest, "wb") as f:
            f.write(resp.read())

    result = {
        "node_id": node_id,
        "format": args.format,
        "scale": args.scale,
        "local_path": dest,
        "_cache": _meta_miss(time.time(), cfg["name"]),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
