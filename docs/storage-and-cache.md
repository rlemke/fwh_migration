# Storage & Cache — backend-aware paths (local / MinIO)

**Module:** `src/migration/storage.py` (imported as `cstore` in `_lib.py`) ·
**Backend:** `facetwork.runtime.storage` · **Config:** `facetwork.config.get_output_base`

## Overview

Every artifact this domain reads or writes — the cached World Bank series, the
Natural Earth geometry, and the rendered `index.html` / `migration.geojson` — goes
through `storage.py`, a thin backend-aware wrapper. It lets terminal use (local
disk) and fleet runs (shared MinIO/S3) share **one** cache rooted at
`$FW_DATA_ROOT/cache/migration/`, so a map rendered on one runner is readable by
any other host without a shared filesystem. It is the same shape census-us /
save-earth use.

## How it works

- **Root selection.** `_data_root()` returns `FW_DATA_ROOT` if set, else
  `facetwork.config.get_output_base()`. `is_remote(path)` is simply `"://" in path`
  — that one test drives every local-vs-remote branch.
- **Roots** (both overridable, both split on `is_remote`):
  - `cache_root()` → `FW_MIGRATION_CACHE_DIR`, else `<root>/cache/migration/cache`
    (remote) or `<root>/migration-cache` (local).
  - `output_root()` → `FW_MIGRATION_OUTPUT_DIR`, else `<root>/cache/migration/output`
    (remote) or `<root>/migration-output` (local).
- **`join(*parts)`** — a `/`-joiner that keeps the scheme on the first part
  (`rstrip("/")` on the base, `strip("/")` on the rest) so `s3://…` URIs survive.
- **Read/write.**
  - `exists(path)` / `localize(path)` delegate to
    `_fws.get_storage_backend(path)` / `_fws.localize`.
  - `open_read` opens `localize(path)` (a remote object is pulled to a local temp
    first).
  - `open_write` is a context manager: **local** paths `makedirs` the parent and
    open directly; **remote** paths write to a `tempfile.mkstemp` scratch file, then
    on close stream the temp bytes into `get_storage_backend(path).open(path,
    "wb")` and unlink the temp. This "stage-local, finalize-on-close" shape is
    required because object stores do not do partial writes.

## Fan-out

Not applicable — a storage helper, not a workflow step.

## Data & fields

No data shaping. It moves bytes for four logical objects:
`migration-series.json` and `world-countries.geojson` (under `cache_root()`), and
`index.html` + `migration.geojson` (under `output_root()`).

## External libraries / binaries

- **`facetwork.runtime.storage`** + **`facetwork.config`** — the runtime storage
  backend + output-base resolution. Standard-library `os` / `tempfile` /
  `contextlib` otherwise. No third-party deps, no binaries.

## Facets & workflows

None — this module declares no facets. It is a library imported by `_lib.py`.

## Cache / output

The single source of truth for where things live:

| Object | Root | Local default | Fleet (remote) |
|---|---|---|---|
| `migration-series.json` | `cache_root()` | `<FW_DATA_ROOT>/migration-cache/` | `s3://afl-cache/cache/migration/cache/` |
| `world-countries.geojson` | `cache_root()` | same | same |
| `index.html` | `output_root()` | `<FW_DATA_ROOT>/migration-output/` | `s3://afl-cache/cache/migration/output/` |
| `migration.geojson` | `output_root()` | same | same |

Env overrides: `FW_DATA_ROOT` (whole tree), `FW_MIGRATION_CACHE_DIR`,
`FW_MIGRATION_OUTPUT_DIR`.

## Gotchas & notes

- **The module docstring is a copy-paste artifact.** It says the cache holds "the
  cached UCDP aggregate" and references census-us / save-earth — that wording is
  inherited from the conflict domain this was cloned from. The **code** is generic
  and correct; only the prose mentions UCDP. Don't be misled: this domain caches the
  World Bank series + Natural Earth geometry, not any UCDP data.
- **Keep scratch/output-base local.** Remote writes stage through a local
  `mkstemp`; `FW_OUTPUT_BASE` / local scratch must be a real local path or the
  finalize step has nowhere to stage.
- **`is_remote` is purely lexical** (`"://" in path`) — a local path containing
  `"://"` would be misclassified, but that does not occur with the derived roots.

## Related specs

- [data-sources](data-sources.md) — writes/reads `migration-series.json` through
  these helpers.
- [map-rendering](map-rendering.md) — reads the series + geometry cache, writes
  `index.html` / `migration.geojson` to `output_root()`.
- [workflow](workflow.md) — the composed pipeline whose artifacts land here.
