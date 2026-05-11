#!/usr/bin/env python3
"""Show the child tree of a specific Figma node."""

import os
import sys
import json
import argparse
import urllib.parse
from figma_common import load_credentials, figma_get, parse_figma_url


def walk_node(node, max_depth, current_depth=0):
    entry = {
        "id": node["id"],
        "name": node.get("name", ""),
        "type": node.get("type", ""),
    }
    if node.get("type") == "TEXT":
        entry["characters"] = node.get("characters", "")

    if max_depth is not None and current_depth >= max_depth:
        return entry

    if "children" in node:
        entry["children"] = [
            walk_node(child, max_depth, current_depth + 1)
            for child in node["children"]
        ]
    return entry


def main():
    parser = argparse.ArgumentParser(description="Inspect a Figma node tree")
    parser.add_argument("url", nargs="?", help="Figma URL with node-id")
    parser.add_argument("--file", help="File key")
    parser.add_argument("--node", help="Node ID (e.g. 12:34)")
    parser.add_argument("--depth", type=int, default=None, help="Max depth (default: all)")
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

    token = load_credentials()
    data = figma_get(token, f"/v1/files/{file_key}/nodes?ids={urllib.parse.quote(node_id)}")

    nodes = data.get("nodes", {})
    node_data = nodes.get(node_id)
    if not node_data or not node_data.get("document"):
        print(f"Node {node_id} not found", file=sys.stderr)
        sys.exit(1)

    result = walk_node(node_data["document"], args.depth)
    if "_cache" in node_data:
        result["_cache"] = node_data["_cache"]
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
