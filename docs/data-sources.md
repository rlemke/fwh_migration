# Data Sources — World Bank download & cache

**Namespace:** `migration.sources` ·
**FFL:** `src/migration/ffl/migration.ffl` (`DownloadMigration`) ·
**Handler:** `src/migration/handlers/migration_handlers.py` (`handle_download_migration`) ·
**Library:** `src/migration/_lib.py` (`download_migration`, `_fetch_indicator`) ·
**Storage:** `src/migration/storage.py`

## Overview

This is the ingest half of the pipeline: it pulls the two World Bank indicators
the map is built from — **Net migration** (`SM.POP.NETM`, immigrants − emigrants)
and **Total population** (`SP.POP.TOTL`) — for every country over 1960–2025, and
caches a single compact per-country series JSON. It answers "get me the raw
migration + population numbers, once, from an open source with no token" so the
render step ([map-rendering](map-rendering.md)) can run offline against the cache.

Net migration is a UN World Population Prospects–derived estimate (World Bank
republishes it). A positive value means more people arrived than left that year.

## How it works

`download_migration(force=False)` (`_lib.py`):

1. **Cache short-circuit.** The cache key is
   `cache_root()/migration-series.json`. If it exists and `force` is false, the
   function just re-opens it and returns `len(blob["countries"])` — no network.
2. **Two indicator fetches.** `_fetch_indicator(NET_INDICATOR)` then
   `_fetch_indicator(POP_INDICATOR)`. Each is **one** GET to
   `https://api.worldbank.org/v2/country/all/indicator/<code>` with
   `format=json`, `per_page=25000`, `date=1960:2025` and a `User-Agent` header,
   `timeout=(30, 120)`. The response is the World Bank's two-element array
   `[metadata, rows]`; a shape that isn't `list`/`len>=2`/`rows is list` raises
   `RuntimeError(... unexpected response shape)`.
3. **Reshape to `{iso3: {year: value}}`.** Each row contributes
   `out[countryiso3code][date] = float(value)`; rows missing iso/value/date are
   skipped. Country display names are captured as a side-channel on the function
   object (`_fetch_indicator._names`), which `download_migration` reads back
   between the two calls.
4. **Merge + cache.** For every ISO in the net series it writes
   `{name, net: {year: value}, pop: {year: value}}` into `countries`, wraps it as
   `{indicator, year_min, year_max, countries}`, and JSON-dumps it (compact
   separators) to the cache key via `storage.open_write`.

Data shape: `WB JSON array → {iso3: {year: float}} × 2 → merged series JSON`.

## Fan-out

**Single-task — no fan-out.** The whole world comes back in two API calls
(`country/all/...`, `per_page=25000`), so there is nothing to parallelise; the FFL
declares `DownloadMigration` as one event facet with no `foreach`.

## Data & fields

- **World Bank rows** are keyed on `countryiso3code` (ISO3), `date` (year string),
  `value` (float or null). Nulls / missing years are simply absent from the series.
- **Indicator codes** are fixed constants: `NET_INDICATOR = "SM.POP.NETM"`,
  `POP_INDICATOR = "SP.POP.TOTL"`; the window is `YEAR_MIN, YEAR_MAX = 1960, 2025`.
- The cached blob preserves the **raw year→value** maps for both `net` and `pop`
  per country; no rate is computed here (that happens at render time).
- `DownloadMigration` returns only `country_count: Int` (the number of entities in
  the net series). It is reported for visibility, not consumed: the render is
  sequenced by the workflow's `after data` clause, not by any value.

## External libraries / binaries

- **`requests`** (pip) — the **only** runtime dependency (`pyproject.toml`
  `dependencies = ["requests"]`). Used for both World Bank indicator GETs. Imported
  defensively (`try: import requests`); if absent, `_fetch_indicator` raises
  `RuntimeError("requests is required ...")`.
- **`facetwork.runtime.storage`** (via `storage.py`) — backend-aware read/write so
  the cache lands in MinIO on the fleet. See [storage-and-cache](storage-and-cache.md).
- No binaries; the World Bank API needs **no key/token**.

## Facets & workflows

| Facet | Kind | Effect / Cost / Timeout | Purpose |
|---|---|---|---|
| `migration.sources.DownloadMigration(force: Boolean = false) => (country_count: Int)` | event | `Effect(kind="external")` · `Cost(tier="moderate")` · `Timeout(minutes=10)` | Download WB net-migration + population for every country (1960–2025) and cache the per-country series. Open API, no token. |

The handler `handle_download_migration` is a thin wrapper: it calls
`download_migration(force=bool(params.get("force")))`, emits a `_step_log`
success/error line, and returns `{"country_count": n}`.

## Cache / output

- **Cache key:** `cache_root()/migration-series.json`. On the fleet
  `cache_root()` is `s3://afl-cache/cache/migration/cache/` (MinIO); locally it is
  `<FW_DATA_ROOT>/migration-cache/`. Overridable with `FW_MIGRATION_CACHE_DIR`.
- **Format:** one compact JSON blob `{indicator, year_min, year_max, countries:
  {iso3: {name, net, pop}}}`.
- No HTML/GeoJSON here — this feature produces only the cached series that
  [map-rendering](map-rendering.md) consumes.

## Gotchas & notes

- **The names side-channel is order-dependent.** `_fetch_indicator` stashes the
  display names on `_fetch_indicator._names`, and `download_migration` reads them
  back **after the net fetch but before the pop fetch** overwrites them
  (`names = dict(getattr(_fetch_indicator, "_names", {}))`). Reordering the two
  fetches would silently swap the name source. This is also why the tests set
  `_lib._fetch_indicator._names` inside their fake.
- **`force` only bypasses the series cache**, not the Natural Earth geometry cache
  (that lives in the render step). A stale-data refresh is `force=true` on the
  workflow, which flows to `DownloadMigration(force=$.force)`.
- **No key means it can rate-limit** — the World Bank API is open but shared; the
  two calls are deliberately whole-world bulk pulls rather than per-country loops.
- Values are **estimates** (UN WPP–derived) — see the honest-scope note in
  [map-rendering](map-rendering.md) and the repo README.

## Related specs

- [map-rendering](map-rendering.md) — the consumer: joins this cached series onto
  world geometry and renders the year-slider choropleth.
- [workflow](workflow.md) — the composed `BuildMigrationWorldMap` that runs this
  then the render.
- [storage-and-cache](storage-and-cache.md) — where the cached series physically
  lands (local vs MinIO) and the env overrides.
