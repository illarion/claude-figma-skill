# Figma Skill for Claude Code

A Claude Code plugin that provides Figma integration — extract CSS properties, export images, and inspect design file structure directly from Figma URLs.

## Features

- **CSS extraction** — pull layout, colors, sizing, typography, and effects from any Figma node as ready-to-paste CSS
- **Batch extraction** — extract CSS from multiple nodes in a single API call to avoid rate limits
- **Children traversal** — include direct children's CSS for full-component snapshots
- **Image export** — render nodes as `png`, `svg`, `jpg`, or `pdf` (1x–4x scale for raster formats)
- **File inspection** — list pages, frames, and components at configurable depth to discover node IDs
- **Node inspection** — walk a node's child tree (with text content for TEXT nodes) to understand structure before extracting CSS
- **Auto URL parsing** — paste a Figma URL and the skill extracts file key and node ID automatically
- **Multi-instance auto-switching** — per-directory `.figmaskillrc` lets each project use its own token
- **Custom API calls** — access any Figma REST endpoint via `call_api.py` for advanced use cases

## Installation

In Claude Code, run:

```
/plugin marketplace add illarion/claude-figma-skill
/plugin install claude-figma-skill
```

See [INSTALL.md](INSTALL.md) for manual installation options.

## Prerequisites

- Python 3.8+
- A Figma Personal Access Token ([create one here](https://www.figma.com/settings) under Security → Personal access tokens)

## Setup

You'll need a Figma Personal Access Token. Create one in Figma → Settings → Security → Personal access tokens.

Then start a Claude Code session in your project root and type `/figma login`. The skill will prompt you for a project name and your token. Credentials are stored locally in a `.figmaskillrc` file with restricted permissions.

### Multiple Figma workspaces

If you work across different Figma accounts or workspaces, place a separate `.figmaskillrc` (by performing a `/figma login`) in each directory tree. The skill picks up the nearest one automatically — no manual switching needed. Each account's cache is isolated under `~/.cache/figma-skill/<name>/`, so cached data and rate-limit state from one account is never served to another.

```
~/work/
├── a/               ← .figmaskillrc (token A)
│   ├── repo-1/
│   └── repo-2/
└── b/               ← .figmaskillrc (token B)
    └── repo-3/
```

## Usage

| Action | Example |
|--------|---------|
| Extract CSS from a node | `/figma extract https://www.figma.com/design/FILE/Name?node-id=12-34` |
| | `/figma what styles does this button use? <URL>` |
| Extract a full component | `/figma get CSS for this card with children: <URL>` |
| Compare design with code | `/figma compare this Figma node with src/components/Button.tsx: <URL>` |
| Export a node as image | `/figma export this frame as PNG: <URL>` |
| | `/figma render this icon as SVG: <URL>` |
| List file structure | `/figma show me the pages in this file: <FILE_URL>` |
| Inspect a node tree | `/figma what's inside this component? <URL>` |

## Why this over Figma's Dev Mode MCP?

Figma's official Dev Mode MCP server requires a Professional/Organization seat with Dev Mode enabled, the Figma desktop app running with MCP toggled on, and works only against files you can open in the desktop client. This skill uses the public REST API:

| | Official Dev Mode MCP | This skill |
|--|:--:|:--:|
| Extract CSS / inspect nodes | Yes | Yes |
| Export rendered images | Yes | Yes |
| Batch CSS extraction (multiple nodes, single call) | No | Yes |
| Works without the desktop app | No | Yes |
| Works on a free Figma seat | No | Yes |
| Multi-account auto-switching | No | Yes |
| Requires Dev Mode toggle | Yes | No |
| Requires Professional+ seat | Yes | No |

**When to use the official MCP instead:** if you need variable-binding metadata, component-prop linkage, or Code Connect mappings — these are only exposed through the desktop MCP, not the public REST API.

## License

[MIT](LICENSE)
