#!/usr/bin/env python3
"""List pages, frames, and components in a Figma file."""

import os
import sys
import json
import argparse
from figma_common import load_account, figma_get, parse_figma_url


def walk_tree(node, max_depth, current_depth=0):
    entry = {
        "id": node["id"],
        "name": node.get("name", ""),
        "type": node.get("type", ""),
    }
    if current_depth < max_depth and "children" in node:
        entry["children"] = [
            walk_tree(child, max_depth, current_depth + 1)
            for child in node["children"]
        ]
    return entry


def main():
    parser = argparse.ArgumentParser(description="List Figma file structure")
    parser.add_argument("url", nargs="?", help="Figma file URL")
    parser.add_argument("--file", help="File key")
    parser.add_argument("--depth", type=int, default=2, help="Traversal depth (default: 2)")
    parser.add_argument("--refresh", action="store_true", help="Bypass cache for this call and re-fetch from Figma")
    args = parser.parse_args()

    if args.refresh:
        os.environ["FIGMA_SKILL_REFRESH"] = "1"

    file_key = args.file
    if args.url:
        file_key, _ = parse_figma_url(args.url)

    if not file_key:
        print("Provide a Figma URL or --file FILE_KEY", file=sys.stderr)
        sys.exit(1)

    cfg = load_account()
    data = figma_get(cfg["token"], f"/v1/files/{file_key}?depth={args.depth}", account=cfg["name"])

    pages = []
    for page in data.get("document", {}).get("children", []):
        pages.append(walk_tree(page, args.depth - 1))

    result = {
        "file_key": file_key,
        "name": data.get("name", ""),
        "pages": pages,
    }
    if "_cache" in data:
        result["_cache"] = data["_cache"]
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
