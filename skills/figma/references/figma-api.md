# Figma REST API Reference

## Authentication
All requests use `X-Figma-Token: {personal_access_token}` header.

## Endpoints

### Files
- `GET /v1/files/:file_key` — Full file data. Use `?depth=N` to limit traversal.
- `GET /v1/files/:file_key/nodes?ids=:node_ids` — Specific nodes. Comma-separate multiple IDs. Add `&geometry=paths` for bounding boxes.
- `GET /v1/files/:file_key/styles` — Style metadata (IDs + names, not values).
- `GET /v1/files/:file_key/meta` — File metadata only.

### Images
- `GET /v1/images/:file_key?ids=:node_ids&format=png&scale=2` — Export nodes as images. Returns `{images: {node_id: presigned_url}}`.
  - Formats: `png`, `svg`, `jpg`, `pdf`
  - Scale: 1-4 (raster only)

### Users
- `GET /v1/me` — Current user info. Good for auth verification.

## Rate Limits
- Tier 1 (file_content:read, includes `/v1/files/:key`, `/v1/files/:key/nodes`, `/v1/images`): 10/15/20 req/min for Starter/Professional/Organization (Full or Dev seat).
- **File location, not your seat, determines the tier.** A file in a Starter-plan team is capped at **6 reads/month** even from a Pro/Org account — Figma will return a multi-day `Retry-After`. Source: [help.figma.com/hc/en-us/articles/34963238552855](https://help.figma.com/hc/en-us/articles/34963238552855).
- 429 response includes `Retry-After`, `X-Figma-Rate-Limit-Type` (`low`/`high`), and `X-Figma-Plan-Tier`. A `low` value on a Full seat = file is in a non-upgraded team.
- The skill caches GET responses on disk for 60min by default (per-file under `~/.cache/figma-skill/`) and maintains a per-node index so overlapping requests skip the network. See `SKILL.md` § Caching for env knobs (`FIGMA_SKILL_NO_CACHE`, `FIGMA_SKILL_REFRESH`, `FIGMA_SKILL_CACHE_TTL`).
- On 429, the skill records `retry_until` in `~/.cache/figma-skill/<account>/.throttle` (per-account) and the SessionStart evictor preserves that account's cache while its throttle is active. Other accounts continue normal eviction. In-process retry sleep is capped at 30s per attempt to prevent multi-hour hangs.

## Response Size Limits
- 55 second timeout
- ~500KB practical limit via CloudFront
- Use `depth` parameter to reduce response size

## Node ID Format
- In URLs: `123-456` (dash-separated)
- In API: `123:456` (colon-separated)
- Max 500 node IDs per request

## Common Node Types
- `DOCUMENT`, `CANVAS` (page), `FRAME`, `GROUP`
- `COMPONENT`, `COMPONENT_SET`, `INSTANCE`
- `TEXT`, `RECTANGLE`, `ELLIPSE`, `VECTOR`, `LINE`
- `SECTION`, `TABLE`, `BOOLEAN_OPERATION`
