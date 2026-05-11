#!/usr/bin/env python3
"""CLI for setting up Figma authentication in the current directory."""

import argparse
import os
import sys
from getpass import getpass

from figma_common import save_config, DOTFILE


def cmd_login(args):
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--dir", default="")
    parsed = parser.parse_args(args)

    target_dir = parsed.dir or os.getcwd()
    dotfile = os.path.join(target_dir, DOTFILE)

    if os.path.exists(dotfile):
        print(f"{DOTFILE} already exists in {target_dir}. Remove it first to reconfigure.", file=sys.stderr)
        sys.exit(1)

    interactive = not parsed.token

    if interactive:
        name = parsed.name or input("Project name (e.g. crm): ").strip()
        token = getpass("Figma Personal Access Token: ").strip()
    else:
        name = parsed.name
        token = parsed.token

    if not token:
        print("Token is required.", file=sys.stderr)
        sys.exit(1)

    config = {
        "name": name or os.path.basename(target_dir),
        "token": token,
    }

    save_config(dotfile, config)

    print(f"Created {DOTFILE} in {target_dir}")
    print(f"Add {DOTFILE} to your .gitignore.")


def cmd_logout(args):
    dotfile = os.path.join(os.getcwd(), DOTFILE)

    if not os.path.exists(dotfile):
        print(f"No {DOTFILE} in this directory.", file=sys.stderr)
        sys.exit(1)

    os.remove(dotfile)
    print(f"Removed {DOTFILE} from {os.getcwd()}")


COMMANDS = {
    "login": cmd_login,
    "logout": cmd_logout,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Usage: figma-auth.py {login|logout}")
        print("  --name PROJECT_NAME")
        print("  --token FIGMA_PAT")
        print("  --dir TARGET_DIR")
        sys.exit(1)

    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
