---
name: figma
description: "Extract CSS properties, export images, and inspect design files from Figma. Use this skill whenever the user mentions a Figma URL, asks to match a design, extract CSS or styles from Figma, compare a Figma design with code, inspect a Figma file structure, or export a Figma component as an image. Also use when the user pastes a figma.com link."
---

All Python scripts referenced below are located in the same directory as this SKILL.md file.

### IMPORTANT: Credentials — DO NOT ACCESS

The `.figmaskillrc` dotfile contains the Figma Personal Access Token and must **NEVER** be read, printed, displayed, cited, or included in any output. Do not use Read, Bash, cat, or any other tool to access it. Only the Python scripts access it internally.

### Authentication

Credentials are stored in a `.figmaskillrc` file placed at the root directory of a project tree. Scripts auto-detect credentials by traversing up from the current working directory until they find this file. This means each project directory tree uses its own Figma token automatically — no manual switching needed.

If the user explicitly asks to "login" (e.g. `/figma login`) or to "logout" (e.g. `/figma logout`), run the interactive setup flow below or the `figma-auth.py logout` command respectively, even if a `.figmaskillrc` already exists. For login while one already exists, ask the user to confirm overwriting before deleting the existing dotfile and re-running setup.

**Interactive setup via AskUserQuestion:**

When no `.figmaskillrc` is found (auth failure or first use), or when the user explicitly requests login, collect credentials using `AskUserQuestion` with 2 questions:

1. **Project name** (header: `Project name`) — "What name should identify this Figma configuration?"
   - Option 1: `crm` — "Current project name"
   - Option 2: `my-project` — "Other project name"

2. **Personal Access Token** (header: `Figma PAT`) — "What is your Figma Personal Access Token? Generate one at figma.com → Settings → Personal access tokens"
   - Option 1: `I have a token` — "Paste your existing token via Other"
   - Option 2: `I need to create one` — "Go to Figma Settings → Security → Personal access tokens"

After collecting answers, run:
```
python3 SCRIPT_DIR/figma-auth.py login --name NAME --token TOKEN --dir /path/to/project
```

**Manual setup:**
```
python3 SCRIPT_DIR/figma-auth.py login                          # interactive prompts
python3 SCRIPT_DIR/figma-auth.py login --name NAME --token TOKEN --dir /path/to/project  # non-interactive
python3 SCRIPT_DIR/figma-auth.py logout                         # removes .figmaskillrc from current directory
```

Scripts print the detected config name to stderr automatically.

### Caching

GET responses are cached on disk under `~/.cache/figma-skill/<account_name>/<file_key>/` for 60 minutes, where `<account_name>` is the `name` field from the `.figmaskillrc` that served the call. Each account has its own isolated cache, so data fetched under one account is never served to another. Identical and **overlapping** requests are served locally — for example, after `inspect_node.py X` populates the node cache, a subsequent `extract_css.py --node X` (or `--node` for any descendant of X) returns without an API call. This is the primary defense against Figma's aggressive throttling, which can return multi-day `Retry-After` values when many similar requests hit the API in quick succession.

Cache hits are logged to stderr: `[figma cache: response-hit]` or `[figma cache: node-hit Nx]`.

Image exports (`export_image.py`) are also cached — the downloaded file at `/tmp/figma-exports/...` is returned with `"cached": true` in the JSON output if it already exists.

At session start, the skill runs a hook that deletes TTL-stale entries and then trims the total cache size below ~500 MB by evicting least-recently-used files first. Both `~/.cache/figma-skill/<account>/` and `/tmp/figma-exports/<account>/` are swept; throttled accounts (see Throttle awareness) are preserved while their throttle is active.

Env knobs:
- `FIGMA_SKILL_NO_CACHE=1` — skip both reads and writes (also disables the SessionStart evictor)
- `FIGMA_SKILL_REFRESH=1` — ignore existing entries on read, but write fresh ones
- `FIGMA_SKILL_CACHE_TTL=<seconds>` — override the 60-minute freshness window
- `FIGMA_SKILL_CACHE_MAX_BYTES=<bytes>` — override the 500 MB total-size cap

### Reading cache state

Every user-facing script emits cache age information so you (and the user) can tell whether they're looking at fresh or cached data:

- **Stderr** carries human-readable markers:
  - `[figma cache: response-hit (12m old)]` — entire response served from cache
  - `[figma cache: node-hit 3x (oldest 12m)]` — multiple nodes synthesized from per-node cache
  - `[figma cache: partial-hit 2/3 (oldest 12m), fetching 1]` — some nodes cached, rest fetched
  - `[figma export: cached (12m old)]` — image short-circuited to local file
- **JSON output** carries a `_cache` block on every result: `{"hit": true, "fetched_at": "2026-05-11T14:32:00Z", "age_seconds": 720, "account": "crm"}`. The `account` field tells you which `.figmaskillrc` served the data. For `extract_css.py --nodes A B C` the array has a `_cache` block per element.

When relaying results to the user, **briefly mention the age** if it's a cache hit ("*This is from cache, fetched 12m ago.*"). The user can then decide whether to ask for a refresh.

Every script accepts `--refresh` to bypass the cache for that one call and re-fetch from Figma. Use it whenever:
- The user says the design changed, was just updated, or asks to re-fetch
- The age in `_cache.age_seconds` is large enough that you suspect the data may be stale
- The user explicitly says "refresh" / "force fresh" / "ignore cache"

For wholesale invalidation of a single file under one account, suggest `rm -rf ~/.cache/figma-skill/<account>/<file_key>/`. To wipe an entire account's cache: `rm -rf ~/.cache/figma-skill/<account>/`. These are documented escape hatches, not script features.

### Throttle awareness

When Figma returns 429 for an account, the skill writes `~/.cache/figma-skill/<account>/.throttle` recording the `retry_until` timestamp. The SessionStart evictor reads this file and **preserves that account's cache** while throttle is active — TTL-stale entries that we cannot re-fetch are kept, only `.tmp` files are cleaned up. Other accounts continue to evict normally. The throttle file is automatically cleared on the next successful API call from that same account.

Stderr signals to watch for (each carries the account name):
- `[figma cache evict: throttle active for 'crm' until 2026-05-13 14:32 UTC (~39h) — preserving 'crm' cache]` — fired at session start when a long throttle is in effect.
- `[figma cache evict: throttle expired for 'crm', resuming normal eviction]` — fired once when the recorded throttle has elapsed.
- `[figma: throttle active for 'crm' until <date> — attempting fresh fetch (may fail)]` — fired in `figma_get` before a cache-miss network call when throttle is recorded.

In-process retry sleep is capped at 30s per attempt (max 3 attempts ≈ 90s total) so scripts never hang for hours waiting on a long `Retry-After`. If a 429 persists past the cap, the script exits with an HTTP error and the throttle file is left in place for the next session.

Escape hatch: `rm ~/.cache/figma-skill/<account>/.throttle` to clear recorded state for one account if you believe Figma has lifted the throttle and want normal eviction back.

**Guidance:** prefer `extract_css.py --nodes A B C` over multiple invocations. The cache makes overlap free at the network level, but a single batched call still avoids extra process starts and produces denser cache entries.

### Scripts Reference

**Extract CSS from a node:**
```
python3 SCRIPT_DIR/extract_css.py "https://www.figma.com/design/FILE_KEY/Name?node-id=12-34"
python3 SCRIPT_DIR/extract_css.py --file FILE_KEY --node "12:34"
python3 SCRIPT_DIR/extract_css.py "URL" --with-children
python3 SCRIPT_DIR/extract_css.py --file FILE_KEY --nodes "12:34" "56:78" "90:12"
```
Returns JSON with `css` (layout, colors, sizing), `typography` (font properties), and `effects` (shadows, blur) sections. Use `--with-children` to also extract CSS for direct children. Use `--nodes` to extract CSS from multiple nodes in a single API call (returns a JSON array). This is the primary script — use it whenever CSS properties are needed from a Figma design.

**Export node as image:**
```
python3 SCRIPT_DIR/export_image.py "https://www.figma.com/design/FILE_KEY/Name?node-id=12-34"
python3 SCRIPT_DIR/export_image.py --file FILE_KEY --node "12:34" --format svg --scale 2
```
Downloads the rendered image to `/tmp/figma-exports/`. Supports `png` (default), `svg`, `jpg`, `pdf`. Scale factor 1-4 (default: 2) for raster formats. After running, use the Read tool on the `local_path` from the JSON output to view the exported image.

**List file structure:**
```
python3 SCRIPT_DIR/inspect_file.py "https://www.figma.com/design/FILE_KEY/Name"
python3 SCRIPT_DIR/inspect_file.py --file FILE_KEY --depth 2
```
Returns pages with their direct children (frames, components). Use `--depth` to control traversal depth (default: 2). Use this first to discover node IDs before drilling into specific nodes.

**Inspect node tree:**
```
python3 SCRIPT_DIR/inspect_node.py "https://www.figma.com/design/FILE_KEY/Name?node-id=12-34"
python3 SCRIPT_DIR/inspect_node.py --file FILE_KEY --node "12:34" --depth 3
```
Shows the node's children with their types, names, and (for TEXT nodes) text content. Use this to understand component structure before extracting CSS.

**Generic API call:**
```
python3 SCRIPT_DIR/call_api.py GET /v1/files/FILE_KEY/styles
python3 SCRIPT_DIR/call_api.py GET /v1/me
```
For one-off API calls not covered by other scripts. Keeps credentials in-process.

### Argument Handling

- If the user provides a Figma URL, parse it automatically — scripts accept URLs directly
- "Extract CSS" / "get styles" / "what styles does this use" → `extract_css.py`
- "Export" / "screenshot" / "render" a Figma node → `export_image.py`
- "List" / "browse" / "show pages" in a Figma file → `inspect_file.py`
- "Inspect" / "show children" / "what's inside" a node → `inspect_node.py`
- "Compare with code" → run `extract_css.py` then read the relevant CSS file and diff
- If only a file URL is given (no node-id), use `inspect_file.py` first

### Error Handling

- **Auth failure** (403 / "Invalid token") — use AskUserQuestion to re-collect credentials
- **No config** — no `.figmaskillrc` found; use AskUserQuestion setup flow
- **File not found** (404) — verify the URL with the user
- **Node not found** — use `inspect_file.py` to find valid node IDs
- **Rate limited** (429) — scripts retry automatically with backoff

### Tips

- Use `inspect_file.py` first to find the right node ID, then `extract_css.py` for styles
- The CSS output is split into `css`, `typography`, and `effects` for easy copy-paste
- For TEXT nodes, color appears in `typography` (not `css`)
- Use `--with-children` to get a full component's CSS in one call
- Rate limits: ~10-20 requests/minute. Scripts retry automatically on 429. When extracting CSS from multiple nodes in the same file, use `--nodes` instead of parallel script calls to avoid rate limiting
- For large files, use `inspect_file.py --depth 1` first to avoid timeouts
- After extracting CSS, export the image too so you can visually verify
- Figma node IDs use `:` in the API but `-` in URLs — scripts handle conversion automatically
