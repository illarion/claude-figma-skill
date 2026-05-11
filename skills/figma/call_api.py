#!/usr/bin/env python3
"""Make arbitrary Figma API calls without exposing credentials."""

import sys
import json
import argparse
from figma_common import load_credentials, figma_request


def main():
    parser = argparse.ArgumentParser(description="Make a Figma API call")
    parser.add_argument("method", help="HTTP method (GET, POST, PUT, DELETE)")
    parser.add_argument("path", help="API path (e.g. /v1/files/FILE_KEY)")
    parser.add_argument("--data", help="JSON request body")
    args = parser.parse_args()

    token = load_credentials()

    data = None
    if args.data:
        data = json.loads(args.data)

    result = figma_request(token, args.method, args.path, data)
    if result is not None:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
